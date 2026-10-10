"""Thin wrapper that runs the world engine for one world package.

The generation logic lives in :mod:`src.world`; this module only wires the
pieces a run needs around it: backend and model resolution from the
configuration, one self-contained package directory, the run manifest (engine
configuration, budget, seed, backend/model, stop reason) and the quality
report.  ``Pipeline`` therefore keeps a small, coherent Python API::

    pipeline = Pipeline(model=..., seed=7, budget={"max_iterations": 50})
    result = pipeline.run(open("my_input.yaml", encoding="utf-8").read())
    result.stop_reason
"""

from __future__ import annotations

import dataclasses
import hashlib
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Union

from loguru import logger

from .llm import LLMBackend
from .llm.factory import build_backend_clients
from .output_layout import world_package_path
from .run_manifest import RunManifest, file_sha256, snapshot_files, utc_now
from .utils import load_config
from .world.explore import (
    BACKEND_WAIT_MAX_SECONDS, ExplorationResult, load_explore_config, run_world_engine,
)
from .world.operators import OperatorConfig

BUDGET_KEYS = ("max_iterations", "max_wall_seconds", "max_generation_calls")
DEFAULT_INPUT_NAME = "user_input.txt"


class ConfiguredBackend:
    """Apply the configured generation defaults to every backend call.

    A call that passes its own value for a key keeps it; keys configured as
    ``null`` are not sent at all.
    """

    def __init__(self, inner: Any, defaults: Mapping[str, Any]) -> None:
        self._inner = inner
        self._defaults = {k: v for k, v in defaults.items() if v is not None}

    def _merged(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(self._defaults)
        merged.update(kwargs)
        return merged

    def generate_schema(self, *args: Any, **kwargs: Any) -> Any:
        return self._inner.generate_schema(*args, **self._merged(kwargs))

    def generate_text(self, *args: Any, **kwargs: Any) -> Any:
        return self._inner.generate_text(*args, **self._merged(kwargs))

    def generate_long_text(self, *args: Any, **kwargs: Any) -> Any:
        return self._inner.generate_long_text(*args, **self._merged(kwargs))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _operator_config(values: Mapping[str, Any]) -> Optional[OperatorConfig]:
    if not values:
        return None
    known = {f.name for f in dataclasses.fields(OperatorConfig)}
    unknown = sorted(set(values) - known)
    if unknown:
        raise ValueError(f"Unknown engine.operator settings: {unknown}")
    return OperatorConfig(**dict(values))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Pipeline:
    """Run the world engine for exactly one world package."""

    def __init__(
        self,
        config_path: str = "config/ollama_config.yaml",
        model: Optional[str] = None,
        run_id: Optional[str] = None,
        seed: Optional[int] = None,
        output_dir: Optional[Union[str, Path]] = None,
        vision_model: Optional[str] = None,
        backend: Optional[Union[str, LLMBackend]] = None,
        budget: Optional[Mapping[str, Any]] = None,
        judge_model: Optional[str] = None,
    ) -> None:
        """
        Args:
            config_path: Backend/engine configuration file.
            model: Generation model (overrides the configuration).
            run_id: Package id. The package is ``<output>/world_<run_id>``;
                an existing package with this id is continued.
            seed: Run seed. A stored seed of an existing package is
                authoritative; a different explicit seed is an error.
            output_dir: Root for packages (default ``output.base_dir``).
            vision_model: Model that reads ``--image`` input (Ollama only).
            backend: ``"ollama"``, ``"anthropic"`` or an injected backend
                object (used by tests and custom integrations).
            budget: ``max_iterations`` / ``max_wall_seconds`` /
                ``max_generation_calls``; unset keys fall back to the
                configured budget.
            judge_model: Model for the judging tasks (``real_world_check``,
                ``review``) on the same backend type; overrides
                ``engine.judge_model``. Empty means the generation model.
        """
        self.config_path = config_path
        self.config = load_config(config_path)
        engine_cfg = self.config.get("engine") or {}
        self.structured_config = {"max_attempts": 3, "max_conversions": 2,
                                  **(engine_cfg.get("structured") or {})}
        self.backend_wait_max_seconds = float(
            engine_cfg.get("backend_wait_max_seconds", BACKEND_WAIT_MAX_SECONDS))
        self.explore_config = load_explore_config(
            overrides=engine_cfg.get("explore") or {})
        self.operator_config = _operator_config(engine_cfg.get("operator") or {})
        self.generation_defaults = dict(self.config.get("generation") or {})
        self.budget_requested = {
            k: v for k, v in (budget or {}).items()
            if k in BUDGET_KEYS and v is not None}
        unknown = sorted(set(budget or {}) - set(BUDGET_KEYS))
        if unknown:
            raise ValueError(f"Unknown budget keys: {unknown}")
        self.budget = {
            **{k: self.explore_config["budget"].get(k) for k in BUDGET_KEYS},
            **self.budget_requested}

        injected = backend if backend is not None and not isinstance(
            backend, str) else None
        configured = self.config.get("backend", "ollama")
        backend_name = (
            backend if isinstance(backend, str)
            else (getattr(injected, "backend_name", None) or "custom")
            if injected is not None else configured)
        if injected is None and backend_name not in {"ollama", "anthropic"}:
            raise ValueError(
                f"Unsupported LLM backend: {backend_name}. "
                "Choose 'ollama' or 'anthropic'.")

        root = Path(output_dir if output_dir is not None
                    else (self.config.get("output") or {}).get(
                        "base_dir", "./output"))
        if run_id:
            self.run_id = run_id
        else:
            self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            while world_package_path(root, self.run_id).exists():
                self.run_id = f"{self.run_id}_{secrets.token_hex(2)}"
        self.package_dir = world_package_path(root, self.run_id)
        self.base_dir = str(self.package_dir)
        self.package_dir.mkdir(parents=True, exist_ok=True)

        manifest_path = self.package_dir / "run_manifest.json"
        stored: Dict[str, Any] = {}
        if manifest_path.exists():
            stored = RunManifest(manifest_path, {}).data
        # Resuming keeps the environment that created the run unless the
        # caller explicitly overrides it.
        explicit_backend = backend is not None
        if stored and not explicit_backend \
                and stored.get("backend") in {"ollama", "anthropic"}:
            backend_name = stored["backend"]
        self.backend_name = backend_name
        stored_models = stored.get("models") if isinstance(
            stored.get("models"), dict) else {}
        use_stored = bool(stored_models) and model is None \
            and vision_model is None
        self.model_names = self._resolve_models(
            backend_name, model, vision_model,
            stored_models if use_stored else {}, injected)

        # Resuming keeps the judge of the run unless a model is given.
        configured_judge = judge_model or (
            stored.get("judge_model") if use_stored else None) \
            or engine_cfg.get("judge_model") or ""
        self.judge_model = str(configured_judge) or self.model_names["generation"]
        client_models = dict(self.model_names)
        separate_judge = self.judge_model != self.model_names["generation"]
        if separate_judge:
            client_models["judge"] = self.judge_model

        clients = build_backend_clients(
            backend_name, client_models,
            self.config.get("server") or {},
            self.config.get("anthropic") or {},
            injected_backend=injected)
        self.judge_client = (
            ConfiguredBackend(clients["judge"], self.generation_defaults)
            if separate_judge else None)
        self.client = ConfiguredBackend(
            clients["generation"], self.generation_defaults)
        self.vision_client = ConfiguredBackend(
            clients["vision"], self.generation_defaults)
        self.model = self.model_names["generation"]

        initial_seed = int(seed) if seed is not None else secrets.randbits(32)
        self.manifest = RunManifest(manifest_path, self._initial_manifest(
            initial_seed, seed))
        if stored:
            self.manifest.reconcile_interrupted()
        stored_seed = self.manifest.run_seed
        if stored_seed is None:
            raise ValueError(f"Run manifest has no run_seed: {manifest_path}")
        if stored and seed is not None and int(seed) != stored_seed:
            raise ValueError(
                f"Seed {seed} does not match existing run seed "
                f"{stored_seed} for run_id={self.run_id}")
        self.run_seed = stored_seed
        if stored and stored.get("models") != self.model_names:
            self.manifest.update(
                backend=self.backend_name, model=self.model,
                models=dict(self.model_names))
        if self.manifest.data.get("judge_model") != self.judge_model:
            self.manifest.update(judge_model=self.judge_model)
        self.manifest.update(budget={
            "requested": dict(self.budget_requested),
            "effective": dict(self.budget)})
        logger.info(
            f"Pipeline initialized (run_id={self.run_id}, "
            f"run_seed={self.run_seed}, model={self.model})")

    # ------------------------------------------------------------ set-up
    def _resolve_models(
        self, backend_name: str, model: Optional[str],
        vision_model: Optional[str], stored: Mapping[str, Any],
        injected: Any = None,
    ) -> Dict[str, str]:
        if stored.get("generation"):
            return {"generation": stored["generation"],
                    "vision": stored.get("vision") or stored["generation"]}
        if backend_name == "anthropic":
            generation = model or (self.config.get("anthropic") or {}).get(
                "model")
            if not generation:
                raise ValueError(
                    "Anthropic backend requires a model. Set anthropic.model "
                    "in the configuration or pass --model.")
            return {"generation": generation, "vision": generation}
        if injected is not None:
            generation = model or getattr(injected, "model", None) \
                or backend_name
            return {"generation": generation,
                    "vision": vision_model or generation}
        generation = model or (self.config.get("model") or {}).get("name")
        if not generation:
            raise ValueError(
                "No model configured. Set model.name in the configuration "
                "or pass --model.")
        vision = vision_model or (self.config.get("models") or {}).get(
            "vision") or generation
        return {"generation": generation, "vision": vision}

    def _initial_manifest(
        self, seed: int, requested: Optional[int],
    ) -> Dict[str, Any]:
        config_file = Path(self.config_path)
        config_dir = Path("config")
        sources = [p for pattern in ("prompts/*.yaml", "prompts/world/*.yaml",
                                     "world/*.yaml", "schemas/*.json", "schemas/steps/*.json")
                   for p in config_dir.glob(pattern)]
        return {
            "schema_version": 2,
            "layout_version": 3,
            "artifact_type": "world_output",
            "engine": "world",
            "run_id": self.run_id,
            "backend": self.backend_name,
            "model": self.model_names["generation"],
            "models": dict(self.model_names),
            "judge_model": self.judge_model,
            "run_seed": seed,
            "seed_source": "argument" if requested is not None
            else "generated",
            "config": {"path": str(config_file.resolve()),
                       "sha256": file_sha256(config_file)},
            "engine_config": {
                "explore": self.explore_config,
                "operator": (dataclasses.asdict(self.operator_config)
                             if self.operator_config else {}),
                "generation": self.generation_defaults,
                "structured": self.structured_config},
            "files": snapshot_files(sources, Path.cwd()),
            "paths": {"input": "input", "world": "world",
                      "checkpoints": "checkpoints", "final": "final"},
            "created_at": utc_now(),
            "status": "initialized",
        }

    # ------------------------------------------------------------- run
    def check_prerequisites(self, include_vision: bool = False) -> bool:
        """Return whether the backend(s) can accept requests."""
        clients = [("generation", self.client)]
        if include_vision and self.model_names["vision"] \
                != self.model_names["generation"]:
            clients.append(("vision", self.vision_client))
        if self.judge_client is not None:
            clients.append(("judge", self.judge_client))
        for role, client in clients:
            if not client.check_ready():
                logger.error(
                    f"Model for {role} is not available: {client.model}")
                return False
        return True

    def _stored_input(self) -> Optional[str]:
        raw = (self.manifest.data.get("input") or {}).get("raw_file")
        path = self.package_dir / "input" / raw if raw else None
        if path is not None and path.is_file():
            return path.read_text(encoding="utf-8")
        return None

    def run(
        self,
        raw_input: Union[str, bytes, Path, None] = None,
        images: Optional[Sequence[Any]] = None,
        source_name: Optional[str] = None,
    ) -> ExplorationResult:
        """Generate (or continue) the world; return the loop result.

        ``raw_input`` may be omitted when continuing a package whose input is
        already stored.  Writes ``final/`` and ``quality_report.*``.
        """
        resume_text = None
        if raw_input is None:
            resume_text = self._stored_input()
            if resume_text is None:
                raise ValueError(
                    "No input supplied and the package has no stored input")
            raw_input = resume_text
        text = raw_input.decode("utf-8") if isinstance(raw_input, bytes) \
            else raw_input.read_text(encoding="utf-8") \
            if isinstance(raw_input, Path) else raw_input
        digest = _sha256_text(text)
        previous = (self.manifest.data.get("input") or {}).get("sha256")
        if previous and previous != digest:
            raise ValueError(
                f"Input differs from the one stored for run_id={self.run_id}; "
                "use a new run id to generate a different world")
        name = Path(source_name).name if source_name else DEFAULT_INPUT_NAME
        if not previous:
            self.manifest.update(input={
                "raw_file": name, "sha256": digest, "characters": len(text),
                "images": [Path(str(i)).name for i in images or []
                           if not isinstance(i, bytes)]})
        if images is None:
            stored_images = sorted(
                (self.package_dir / "input" / "images").glob("*")) \
                if (self.package_dir / "input" / "images").is_dir() else []
            images = stored_images or None
        raw_name = (self.manifest.data.get("input") or {}).get(
            "raw_file", name)

        try:
            result = run_world_engine(
                text, images, self.package_dir, self.client,
                self.budget, self.run_seed,
                config=self.explore_config,
                operator_config=self.operator_config,
                vision_backend=self.vision_client,
                source_name=raw_name, resume=True, render=True,
                structured_max_attempts=self.structured_config["max_attempts"],
                structured_max_conversions=self.structured_config["max_conversions"],
                judge_backend=self.judge_client,
                backend_wait_max_seconds=self.backend_wait_max_seconds,
                models={"generation": self.model, "judge": self.judge_model})
        finally:
            # The engine updates the manifest file through its own handle.
            self.manifest = RunManifest(self.manifest.path, {})
        self.manifest.update(
            stop_reason=result.stop_reason, iterations=result.iterations,
            counters=dict(result.counters))
        self._write_quality_report()
        return result

    def resume(self) -> ExplorationResult:
        """Continue this package from its last checkpoint."""
        return self.run(None)

    def _write_quality_report(self) -> None:
        try:
            from .quality import create_quality_reports

            _, json_path, md_path = create_quality_reports(self.package_dir)
            self.manifest.update(quality_report={
                "json": json_path.name, "markdown": md_path.name})
        except Exception as exc:  # the report must never fail a finished run
            logger.warning(f"Quality report generation failed: {exc}")
