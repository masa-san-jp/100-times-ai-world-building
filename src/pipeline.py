"""
Pipeline Module
Main pipeline orchestration for 100 TIMES AI WORLD BUILDING
"""

import hashlib
import secrets
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Sequence, Union

import yaml as yaml_lib
from loguru import logger
from tqdm import tqdm

from .ollama_client import OllamaClient
from .checkpoint_manager import CheckpointManager
from .output_layout import resolve_world_package, world_package_name
from .run_manifest import RunManifest, file_sha256, snapshot_files, utc_now
from .utils import (
    load_config,
    load_prompts,
    format_prompt,
    dict_to_yaml,
    save_yaml,
    save_text,
)
from .validation import (
    OutputValidationError,
    assert_valid_artifact,
    validate_artifact,
    validate_phase_state,
)


def phase_lifecycle(phase_name: str):
    """Decorate a phase so its running/completed/failed state is persisted."""
    def decorator(function):
        def wrapped(self, *args, **kwargs):
            self._mark_phase(phase_name, "running")
            try:
                result = function(self, *args, **kwargs)
                if phase_name == "phase0_context":
                    if not isinstance(result, str) or not result.strip():
                        raise OutputValidationError(
                            phase_name, ["user context must be non-empty"]
                        )
                elif phase_name == "phase2_characters":
                    self._validate_phase_state(
                        phase_name, {"characters_list": result}
                    )
                else:
                    self._validate_phase_state(phase_name, result)
            except KeyboardInterrupt:
                self._mark_phase(phase_name, "cancelled")
                raise
            except Exception as exc:
                self._mark_phase(phase_name, "failed", error=str(exc))
                raise
            self._mark_phase(phase_name, "completed")
            return result

        wrapped.__name__ = function.__name__
        wrapped.__doc__ = function.__doc__
        return wrapped
    return decorator


def run_lifecycle(function):
    """Decorate top-level execution methods with run status persistence."""
    def wrapped(self, *args, **kwargs):
        self.manifest.set_status("running")
        try:
            result = function(self, *args, **kwargs)
            if not result:
                self.manifest.set_status("failed", error="pipeline returned no results")
            else:
                self.manifest.set_status("completed")
            return result
        except KeyboardInterrupt:
            self.manifest.set_status("cancelled")
            raise
        except Exception as exc:
            self.manifest.set_status("failed", error=str(exc))
            raise

    wrapped.__name__ = function.__name__
    wrapped.__doc__ = function.__doc__
    return wrapped


class Pipeline:
    """Main pipeline for AI world building"""

    def __init__(
        self,
        config_path: str = "config/ollama_config.yaml",
        prompts_dir: str = "config/prompts",
        model: Optional[str] = None,
        run_id: Optional[str] = None,
        seed: Optional[int] = None,
        output_dir: Optional[Union[str, Path]] = None,
        structured_model: Optional[str] = None,
        story_model: Optional[str] = None,
        reference_model: Optional[str] = None,
        vision_model: Optional[str] = None,
    ):
        """
        Initialize pipeline

        Args:
            config_path: Path to configuration file
            prompts_dir: Directory containing prompt templates
            model: Model name to use (overrides config value).  Pass one of:
                   "gpt-oss:20b"    – standard local model (default)
                   "gpt-oss:20b-q8" – 8-bit quantized (16-24 GB VRAM)
                   "gpt-oss:20b-q4" – 4-bit quantized (8-16 GB VRAM)
                   "gpt-oss:120b"   – high-end model (60+ GB VRAM)
            run_id: Unique identifier for this run (default: current timestamp
                    "YYYYMMDD_HHMMSS_microseconds").  Each run stores its outputs under
                    ``<base_dir>/world_<run_id>/`` so that all intermediate and
                    final artifacts for one generated world stay together.
            seed: Optional fixed seed. When omitted, a new run seed is generated
                  and persisted in the run manifest.
            output_dir: Optional root directory for generated runs. When omitted,
                        ``output.base_dir`` from the configuration is used.
            structured_model: Optional Ollama model for JSON-producing phases.
            story_model: Optional Ollama model for novel generation.
            reference_model: Optional Ollama model for reference generation.
            vision_model: Optional Ollama vision model for image input.
        """
        # Load configuration
        self.config = load_config(config_path)

        output_config = self.config.get("output", {})
        base_dir_root_value = (
            str(output_dir)
            if output_dir is not None
            else output_config.get("base_dir", "./output")
        )
        base_dir_root = Path(base_dir_root_value)

        # Determine run ID (one unique world package per execution)
        if run_id:
            self.run_id = run_id
        else:
            self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            while (
                (base_dir_root / world_package_name(self.run_id)).exists()
                or (base_dir_root / f"run_{self.run_id}").exists()
            ):
                self.run_id = f"{self.run_id}_{secrets.token_hex(2)}"

        # Initialize components.  The default remains one local model, while
        # each role can be assigned a different Ollama model for Colab parity.
        server_config = self.config.get("server", {})
        model_config = self.config.get("model", {})
        role_config = self.config.get("models", {})

        # Model selection: explicit argument > config value > built-in default
        resolved_model = model or model_config.get("name", "gpt-oss:20b")

        def configured_role(role: str, explicit: Optional[str]) -> str:
            if explicit:
                return explicit
            if role == "vision" and role_config.get("vision"):
                return role_config["vision"]
            if model:
                return resolved_model
            return role_config.get(role, resolved_model)

        self.model_names = {
            "structured": configured_role("structured", structured_model),
            "story": configured_role("story", story_model),
            "reference": configured_role("reference", reference_model),
            "vision": configured_role("vision", vision_model),
        }

        client_kwargs = {
            "host": server_config.get("host", "http://localhost"),
            "port": server_config.get("port", 11434),
            "timeout": server_config.get("timeout", 300),
            "max_retries": server_config.get("max_retries", 3),
            "retry_delay": server_config.get("retry_delay", 5),
        }
        self.clients = {
            role: OllamaClient(model=model_name, **client_kwargs)
            for role, model_name in self.model_names.items()
        }
        # Backwards-compatible alias used by existing callers and tests.
        self.client = self.clients["structured"]

        # One package contains the input, all intermediate artifacts,
        # checkpoints, and final deliverables for exactly one world.
        self.base_dir_path, self.legacy_layout = resolve_world_package(
            base_dir_root, self.run_id
        )
        run_dir_already_exists = self.base_dir_path.exists()
        self.base_dir_path.mkdir(parents=True, exist_ok=True)
        self.base_dir = str(self.base_dir_path)

        if self.legacy_layout:
            # Keep old packages resumable in place. New packages use the
            # clearer input/final split below.
            self.input_dir = self.base_dir_path / "intermediate"
            self.intermediate_dir = self.base_dir_path / "intermediate"
            self.checkpoints_dir = self.base_dir_path / "checkpoints"
            self.novels_dir = self.base_dir_path / "novels"
            self.references_dir = self.base_dir_path / "references"
        else:
            layout_config = output_config.get("subdirs", {})
            self.input_dir = self.base_dir_path / layout_config.get("input", "input")
            self.intermediate_dir = self.base_dir_path / layout_config.get(
                "intermediate", "intermediate"
            )
            self.checkpoints_dir = self.base_dir_path / layout_config.get(
                "checkpoints", "checkpoints"
            )
            final_dir = self.base_dir_path / layout_config.get("final", "final")
            self.novels_dir = final_dir / "novels"
            self.references_dir = final_dir / "references"
            for directory in (
                self.input_dir,
                self.intermediate_dir,
                self.checkpoints_dir,
                self.novels_dir,
                self.references_dir,
            ):
                directory.mkdir(parents=True, exist_ok=True)

        # Each new run gets a fresh seed. An existing manifest is authoritative
        # so that resuming a run never silently changes its random stream.
        generation_config = model_config.get("generation", {})
        configured_seed = generation_config.get("seed")
        requested_seed = seed if seed is not None else configured_seed
        initial_seed = requested_seed if requested_seed is not None else secrets.randbits(32)
        manifest_path = self.base_dir_path / "run_manifest.json"
        manifest_already_exists = manifest_path.exists()
        initial_data = {
            "schema_version": 1,
            "layout_version": 1 if self.legacy_layout else 2,
            "artifact_type": "world_output",
            "run_id": self.run_id,
            "run_seed": int(initial_seed),
            "seed_source": (
                "argument" if seed is not None
                else "config" if configured_seed is not None
                else "legacy_retrofit" if run_dir_already_exists
                else "generated"
            ),
            "models": dict(self.model_names),
            "config": {
                "path": str(Path(config_path).resolve()),
                "sha256": file_sha256(Path(config_path)),
            },
            "prompts": snapshot_files(
                Path(prompts_dir).glob("*.yaml"),
                Path.cwd(),
            ),
            "paths": {
                "input": str(self.input_dir.relative_to(self.base_dir_path)),
                "intermediate": str(
                    self.intermediate_dir.relative_to(self.base_dir_path)
                ),
                "checkpoints": str(
                    self.checkpoints_dir.relative_to(self.base_dir_path)
                ),
                "novels": str(self.novels_dir.relative_to(self.base_dir_path)),
                "references": str(
                    self.references_dir.relative_to(self.base_dir_path)
                ),
            },
            "created_at": utc_now(),
            "status": "initialized",
            "phases": {},
        }
        self.manifest = RunManifest(manifest_path, initial_data)
        if manifest_already_exists:
            self.manifest.reconcile_interrupted()
        if run_dir_already_exists and not manifest_already_exists:
            logger.warning(
                "Existing run directory had no manifest; a new run_seed was "
                "recorded, but requests from the previous execution cannot be "
                "reproduced exactly."
            )
        stored_seed = self.manifest.run_seed
        if stored_seed is None:
            raise ValueError(f"Run manifest has no run_seed: {manifest_path}")
        if requested_seed is not None and int(requested_seed) != stored_seed:
            raise ValueError(
                f"Seed {requested_seed} does not match existing run seed "
                f"{stored_seed} for run_id={self.run_id}"
            )
        self.run_seed = stored_seed

        # Resuming without an explicit model override must use the models that
        # created the run. This prevents an interactive default choice from
        # silently changing the continuation environment.
        stored_models = self.manifest.data.get("models")
        explicit_model_override = any(
            value is not None
            for value in (model, structured_model, story_model, reference_model, vision_model)
        )
        if (
            manifest_already_exists
            and isinstance(stored_models, dict)
            and not explicit_model_override
        ):
            self.model_names = {
                role: stored_models.get(role, name)
                for role, name in self.model_names.items()
            }
            self.clients = {
                role: OllamaClient(model=model_name, **client_kwargs)
                for role, model_name in self.model_names.items()
            }
            self.client = self.clients["structured"]
        elif manifest_already_exists and isinstance(stored_models, dict):
            if stored_models != self.model_names:
                self.manifest.update(model_override=dict(self.model_names))

        checkpoint_config = self.config.get("checkpointing", {})
        self.checkpoint_manager = CheckpointManager(
            checkpoint_dir=self.checkpoints_dir,
            auto_save=checkpoint_config.get("auto_save", True),
            compression=checkpoint_config.get("compression", False),
            max_checkpoints_per_phase=checkpoint_config.get(
                "max_checkpoints_per_phase", 100
            ),
        )

        # Load prompts
        self.prompts = load_prompts(prompts_dir)

        # Output configuration (kept for reference; actual paths use self.base_dir)
        self.output_config = output_config
        self._resume_mode = False

        logger.info(
            f"Pipeline initialized (run_id={self.run_id}, run_seed={self.run_seed}, "
            f"model={resolved_model})"
        )
        logger.info(f"Output directory: {self.base_dir}")

    def _client_for(self, role: str = "structured") -> OllamaClient:
        """Return the local Ollama client assigned to a pipeline role."""
        return self.clients[role]

    def _num_ctx(self, phase_config: Dict[str, Any]) -> Optional[int]:
        """Resolve the configured Ollama context window for a phase."""
        return phase_config.get(
            "num_ctx",
            self.config.get("performance", {}).get("max_context_length"),
        )

    def _derive_seed(self, request_key: str, continuation_index: int = 0) -> int:
        """Derive a stable Ollama seed for one request in this run."""
        material = f"{self.run_seed}:{request_key}:{continuation_index}".encode(
            "utf-8"
        )
        return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % (
            2**31 - 1
        )

    def _generation_options(
        self,
        phase_config: Dict[str, Any],
        request_key: str,
    ) -> Dict[str, Any]:
        """Merge model defaults and phase overrides for Ollama options."""
        defaults = self.config.get("model", {}).get("generation", {})
        options: Dict[str, Any] = {}
        for key in (
            "temperature",
            "top_p",
            "top_k",
            "repeat_penalty",
            "num_predict",
        ):
            if key in defaults:
                options[key] = defaults[key]
            if key in phase_config:
                options[key] = phase_config[key]

        num_ctx = self._num_ctx(phase_config)
        if num_ctx is not None:
            options["num_ctx"] = num_ctx
        if "think" in phase_config:
            options["think"] = phase_config["think"]
        options["seed"] = self._derive_seed(request_key)

        if phase_config.get("streaming"):
            raise NotImplementedError(
                "Streaming output is not supported by the current Pipeline; "
                "set phases.<phase>.streaming to false."
            )
        requests = self.manifest.data.setdefault("requests", {})
        requests[request_key] = dict(options)
        self.manifest.update(requests=requests)
        return options

    def _mark_phase(
        self,
        phase_name: str,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """Keep checkpoint and run-manifest phase state in sync."""
        self.checkpoint_manager.mark_phase(phase_name, status, error=error)
        self.manifest.set_phase_status(phase_name, status, error=error)

    def _generate_quality_report(self) -> None:
        """Generate quality reports after a complete pipeline run."""
        try:
            from .quality import create_quality_reports

            report, json_path, markdown_path = create_quality_reports(
                self.base_dir_path,
                config=self.config,
            )
            self.manifest.update(
                quality_report={
                    "status": report["status"],
                    "json_path": str(json_path.relative_to(self.base_dir_path)),
                    "markdown_path": str(markdown_path.relative_to(self.base_dir_path)),
                }
            )
        except Exception as exc:
            logger.warning(f"Quality report generation failed: {exc}")

    def _validate_json_output(
        self,
        artifact: str,
        response: Dict[str, Any],
        chapter_number: Optional[int] = None,
    ) -> None:
        """Validate a model response before it becomes a checkpoint artifact."""
        if not self.config.get("safety", {}).get("validate_outputs", True):
            return
        try:
            assert_valid_artifact(artifact, response, chapter_number=chapter_number)
        except OutputValidationError as exc:
            self.manifest.update(
                last_validation_error={
                    "artifact": artifact,
                    "chapter_number": chapter_number,
                    "errors": exc.errors,
                    "at": utc_now(),
                }
            )
            raise

    def _validate_phase_state(self, phase_name: str, data: Any) -> None:
        """Reject incomplete phase output before reporting a run as complete."""
        if not self.config.get("safety", {}).get("validate_outputs", True):
            return
        errors = validate_phase_state(phase_name, data)
        if errors:
            self.manifest.update(
                last_validation_error={
                    "phase": phase_name,
                    "errors": errors,
                    "at": utc_now(),
                }
            )
            raise OutputValidationError(phase_name, errors)

    def _resume_json_is_valid(
        self,
        artifact: str,
        data: Any,
        chapter_number: Optional[int] = None,
    ) -> bool:
        """Check a resumable artifact without turning a stale checkpoint into a failure."""
        if not self.config.get("safety", {}).get("validate_outputs", True):
            return True
        # Checkpoints store generated JSON as YAML strings for the prompts and
        # intermediate files. Parse that representation before applying the
        # same artifact contract used for fresh model responses.
        candidate = data
        if isinstance(data, str):
            try:
                candidate = yaml_lib.safe_load(data)
            except yaml_lib.YAMLError:
                return False
        return not bool(
            validate_phase_state("phase1_expansion", candidate)
            if artifact == "phase1_expansion"
            else self._artifact_errors(artifact, candidate, chapter_number)
        )

    @staticmethod
    def _artifact_errors(
        artifact: str,
        data: Any,
        chapter_number: Optional[int] = None,
    ) -> List[str]:
        return validate_artifact(artifact, data, chapter_number=chapter_number)

    def _generate_json(
        self,
        prompt: str,
        phase_config: Dict[str, Any],
        system_prompt: Optional[str] = None,
        role: str = "structured",
        images: Optional[List[Union[str, Path, bytes]]] = None,
        request_key: str = "json",
    ) -> Optional[Dict[str, Any]]:
        options = self._generation_options(phase_config, request_key)
        num_ctx = options.pop("num_ctx", None)
        max_tokens = options.pop("num_predict", 4096)
        temperature = options.pop("temperature", 0.7)
        return self._client_for(role).generate_json(
            prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            images=images,
            num_ctx=num_ctx,
            **options,
        )

    def _generate_text(
        self,
        prompt: str,
        phase_config: Dict[str, Any],
        system_prompt: Optional[str] = None,
        role: str = "story",
        long_form: bool = False,
        request_key: str = "text",
    ) -> Optional[str]:
        client = self._client_for(role)
        options = self._generation_options(phase_config, request_key)
        num_ctx = options.pop("num_ctx", None)
        max_tokens = options.pop("num_predict", 4096)
        temperature = options.pop("temperature", 1.0)
        request_seed = options.pop("seed", None)
        common = {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "system_prompt": system_prompt,
            "num_ctx": num_ctx,
            "format": phase_config.get("format") or None,
            **options,
        }
        if long_form:
            return client.generate_long_text(
                prompt,
                **common,
                seed=request_seed,
                max_continuations=phase_config.get("max_continuations", 3),
                seed_factory=lambda index: self._derive_seed(request_key, index),
            )
        common["seed"] = request_seed
        return client.generate_text(prompt, **common)

    def _resume_data(self, phase_name: str) -> Dict[str, Any]:
        """Load partial phase data only when this Pipeline is in resume mode."""
        if not self._resume_mode:
            return {}
        return self.checkpoint_manager.load_checkpoint(phase_name) or {}

    def _next_phase1_batch_index(self, prompt_key: str) -> int:
        """Return the next stable batch number for a Phase 1 list.

        A model can return fewer items than requested.  In that case the
        following request must get a new seed/key instead of overwriting the
        earlier batch, and the same numbering must survive a resume.
        """
        prefix = f"phase1_{prompt_key}_batch_"
        indices = []
        for request_key in self.manifest.data.get("requests", {}):
            if not request_key.startswith(prefix):
                continue
            suffix = request_key[len(prefix):]
            if suffix.isdigit():
                indices.append(int(suffix))
        return max(indices, default=0) + 1

    def check_prerequisites(self, include_vision: bool = False) -> bool:
        """
        Check if all prerequisites are met

        Returns:
            True if ready, False otherwise
        """
        logger.info("Checking prerequisites...")

        # Check Ollama server once, then ensure every model needed by this run.
        if not self.client.check_server():
            logger.error("Ollama server is not running. Please start it with: ollama serve")
            return False

        roles = ["structured", "story", "reference"]
        if include_vision:
            roles.append("vision")
        seen_models = set()
        for role in roles:
            client = self._client_for(role)
            if client.model in seen_models:
                continue
            seen_models.add(client.model)
            if not client.ensure_model_ready():
                logger.error(f"Model for {role} is not available: {client.model}")
                return False

        logger.info("✓ All prerequisites met")
        return True

    def _save_user_context(self, user_context: str) -> None:
        """Persist the input inside the same package as its generated world."""
        if self.legacy_layout:
            # Preserve the old filename and wrapper for legacy resumable runs.
            save_yaml(
                {"user_context": user_context},
                str(self.input_dir / "00_user_context.yaml"),
            )
        else:
            save_text(user_context, str(self.input_dir / "user_context.yaml"))

    @phase_lifecycle("phase0_context")
    def run_phase0_context_extraction(
        self,
        user_input: Optional[str] = None,
        image_paths: Optional[Sequence[Union[str, Path, bytes]]] = None,
        extract: bool = False,
    ) -> str:
        """
        Phase 0: User context extraction
        Interactive dialog to extract user context

        Returns:
            User context as YAML string
        """
        logger.info("=== Phase 0: User Context Extraction ===")

        phase_config = self.config.get("phases", {}).get("phase0_context_extraction", {})
        images = list(image_paths or [])

        if user_input is None:
            user_input = input(
                "物語のアイデアを入力してください（1行。画像だけの場合は空欄）: "
            ).strip()

        # A supplied YAML/text context is already equivalent to Colab's
        # editable `user_context` cell.  Extraction is opt-in for text and is
        # automatically enabled when images are supplied.
        if images or extract:
            prompt_template = self.prompts.get("context_extraction", {})
            if not prompt_template:
                logger.error("No context_extraction prompt found")
                return user_input
            prompt = format_prompt(
                prompt_template.get("user", ""),
                user_input=user_input or "（テキスト入力なし）",
            )
            role = "vision" if images else "structured"
            response = self._generate_json(
                prompt,
                phase_config,
                system_prompt=prompt_template.get("system"),
                role=role,
                images=images or None,
                request_key="phase0_context_extraction",
            )
            if response:
                self._validate_json_output("context", response)
                context_data = response.get("context", response)
                user_context = dict_to_yaml(context_data)
            else:
                user_context = user_input
        else:
            user_context = user_input

        # Save checkpoint
        self.checkpoint_manager.save_checkpoint(
            "phase0_context",
            {"user_context": user_context}
        )

        # The user context is input to the world package, not an intermediate
        # result. Keep it beside the generated artifacts for self-contained
        # reruns and inspection.
        self._save_user_context(user_context)

        logger.info("✓ Phase 0 completed")
        return user_context

    @phase_lifecycle("phase1_expansion")
    def run_phase1_expansion(self, user_context: str) -> Dict[str, str]:
        """
        Phase 1: 100x expansion
        Generate desire list, ability list, role list, plot types

        Args:
            user_context: User context YAML string

        Returns:
            Dictionary of generated lists
        """
        logger.info("=== Phase 1: 100x Expansion ===")

        # Phase 1 can be run directly, so persist its input here as well as in
        # the full-pipeline Phase 0 path.
        self._save_user_context(user_context)

        phase_config = self.config.get("phases", {}).get("phase1_expansion", {})
        results = self._resume_data("phase1_expansion")

        # 1-3. Generate desire, ability, and role lists
        list_definitions = [
            ("desire_list", "01_desire_list", "desires"),
            ("ability_list", "02_ability_list", "abilities"),
            ("role_list", "03_role_list", "roles"),
        ]
        items_per_request = int(phase_config.get("items_per_request", 100))
        if items_per_request < 1:
            raise ValueError("phase1_expansion.items_per_request must be positive")

        for prompt_key, filename, item_key in list_definitions:
            logger.info(f"Generating {prompt_key}...")
            if prompt_key in results:
                if self._resume_json_is_valid(prompt_key, results[prompt_key]):
                    continue
                results.pop(prompt_key, None)
            partial_key = f"_partial_{prompt_key}"
            partial_items = results.get(partial_key, [])
            if not isinstance(partial_items, list):
                partial_items = []
            partial_items = partial_items[:100]
            list_prompt = self.prompts.get(prompt_key, {})
            if list_prompt:
                while len(partial_items) < 100:
                    start = len(partial_items)
                    batch_index = self._next_phase1_batch_index(prompt_key)
                    batch_count = min(items_per_request, 100 - start)
                    prompt = format_prompt(
                        list_prompt.get("user", ""),
                        user_context=user_context,
                        item_count=batch_count,
                    )
                    prompt += (
                        "\n\n追加条件: このリクエストでは全体の一部として、"
                        f"{batch_count}件だけを生成してください。"
                        f"JSONの{item_key}配列にも{batch_count}件だけを入れてください。"
                    )
                    response = self._generate_json(
                        prompt,
                        phase_config,
                        system_prompt=list_prompt.get("system", None),
                        request_key=f"phase1_{prompt_key}_batch_{batch_index}",
                    )
                    if not response or not isinstance(response.get(item_key), list):
                        raise OutputValidationError(
                            prompt_key,
                            [f"{item_key} batch {batch_index} did not return a list"],
                        )
                    batch_items = response[item_key]
                    if not batch_items:
                        raise OutputValidationError(
                            prompt_key,
                            [f"{item_key} batch {batch_index} was empty"],
                        )
                    partial_items.extend(batch_items[: 100 - len(partial_items)])
                    results[partial_key] = partial_items
                    self.checkpoint_manager.save_checkpoint("phase1_expansion", results)
                if len(partial_items) != 100:
                    raise OutputValidationError(
                        prompt_key,
                        [f"{item_key} must contain 100 items (got {len(partial_items)})"],
                    )
                response = {item_key: partial_items}
                self._validate_json_output(prompt_key, response)
                results[prompt_key] = dict_to_yaml(response)
                results.pop(partial_key, None)
                save_yaml(response, str(self.intermediate_dir / f"{filename}.yaml"))
                self.checkpoint_manager.save_checkpoint("phase1_expansion", results)

        # 4. Plot type list
        logger.info("Generating plot type list...")
        plottype_list_prompt = self.prompts.get("plottype_list", {})
        if plottype_list_prompt and (
            "plottype_list" not in results
            or not self._resume_json_is_valid(
                "plottype_list", results.get("plottype_list")
            )
        ):
            results.pop("plottype_list", None)
            partial_key = "_partial_plottype_list"
            partial_items = results.get(partial_key, [])
            if not isinstance(partial_items, list):
                partial_items = []
            partial_items = partial_items[:10]
            items_per_request = int(
                phase_config.get("plottype_items_per_request", 5)
            )
            if items_per_request < 1:
                raise ValueError(
                    "phase1_expansion.plottype_items_per_request must be positive"
                )
            while len(partial_items) < 10:
                start = len(partial_items)
                batch_index = self._next_phase1_batch_index("plottype_list")
                batch_count = min(items_per_request, 10 - start)
                prompt = format_prompt(
                    plottype_list_prompt.get("user", ""),
                    item_count=batch_count,
                )
                prompt += (
                    "\n\n追加条件: このリクエストでは全体の一部として、"
                    f"{batch_count}件だけを生成してください。"
                    f"JSONのplot_types配列にも{batch_count}件だけを入れてください。"
                )
                response = self._generate_json(
                    prompt,
                    phase_config,
                    system_prompt=plottype_list_prompt.get("system", None),
                    request_key=f"phase1_plottype_list_batch_{batch_index}",
                )
                if not response or not isinstance(response.get("plot_types"), list):
                    raise OutputValidationError(
                        "plottype_list",
                        [f"plot_types batch {batch_index} did not return a list"],
                    )
                batch_items = response["plot_types"]
                if not batch_items:
                    raise OutputValidationError(
                        "plottype_list",
                        [f"plot_types batch {batch_index} was empty"],
                    )
                partial_items.extend(batch_items[: 10 - len(partial_items)])
                results[partial_key] = partial_items
                self.checkpoint_manager.save_checkpoint("phase1_expansion", results)
            response = {"plot_types": partial_items}
            self._validate_json_output("plottype_list", response)
            results["plottype_list"] = dict_to_yaml(response)
            results.pop(partial_key, None)
            save_yaml(response, str(self.intermediate_dir / "04_plottype_list.yaml"))
            self.checkpoint_manager.save_checkpoint("phase1_expansion", results)

        # 5. Select plot type
        logger.info("Selecting plot type...")
        plottype_selection_prompt = self.prompts.get("plottype_selection", {})
        if (
            plottype_selection_prompt
            and "plottype_list" in results
            and (
                "plottype" not in results
                or not self._resume_json_is_valid(
                    "plottype", results.get("plottype")
                )
            )
        ):
            results.pop("plottype", None)
            prompt = format_prompt(
                plottype_selection_prompt.get("user", ""),
                user_context=user_context,
                plottype_list=results["plottype_list"]
            )
            response = self._generate_json(
                prompt,
                phase_config,
                system_prompt=plottype_selection_prompt.get("system", None),
                request_key="phase1_plottype_selection",
            )
            if response:
                self._validate_json_output("plottype", response)
                results["plottype"] = dict_to_yaml(response)
                save_yaml(response, str(self.intermediate_dir / "05_plottype.yaml"))
                self.checkpoint_manager.save_checkpoint("phase1_expansion", results)

        # Save checkpoint
        self.checkpoint_manager.save_checkpoint("phase1_expansion", results)

        logger.info("✓ Phase 1 completed")
        return results

    @phase_lifecycle("phase2_characters")
    def run_phase2_characters(self, user_context: str, phase1_results: Dict[str, str]) -> str:
        """
        Phase 2: Character generation
        Generate 4 main characters

        Args:
            user_context: User context YAML string
            phase1_results: Results from Phase 1

        Returns:
            Characters list as YAML string
        """
        logger.info("=== Phase 2: Character Generation ===")

        phase_config = self.config.get("phases", {}).get("phase2_characters", {})

        existing = self._resume_data("phase2_characters")
        if existing.get("characters_list") and self._resume_json_is_valid(
            "characters", existing["characters_list"]
        ):
            return existing["characters_list"]

        characters_prompt = self.prompts.get("characters", {})
        if characters_prompt:
            prompt = format_prompt(
                characters_prompt.get("user", ""),
                user_context=user_context,
                plottype=phase1_results.get("plottype", ""),
                desire_list=phase1_results.get("desire_list", ""),
                ability_list=phase1_results.get("ability_list", ""),
                role_list=phase1_results.get("role_list", ""),
            )
            response = self._generate_json(
                prompt,
                phase_config,
                system_prompt=characters_prompt.get("system", None),
                request_key="phase2_characters",
            )
            if response:
                self._validate_json_output("characters", response)
                characters_yaml = dict_to_yaml(response)
                save_yaml(response, str(self.intermediate_dir / "06_characters_list.yaml"))
                self.checkpoint_manager.save_checkpoint("phase2_characters", {"characters_list": characters_yaml})
                logger.info("✓ Phase 2 completed")
                return characters_yaml

        logger.warning("Phase 2 failed")
        return ""

    @phase_lifecycle("phase3_world")
    def run_phase3_world_building(self, phase1_results: Dict[str, str]) -> Dict[str, str]:
        """
        Phase 3: World building
        Generate all world setting elements

        Args:
            phase1_results: Results from Phase 1

        Returns:
            Dictionary of world settings
        """
        logger.info("=== Phase 3: World Building ===")

        phase_config = self.config.get("phases", {}).get("phase3_world", {})
        world_data = self._resume_data("phase3_world")

        # List of world elements to generate (in order)
        elements = [
            ("events", {}),
            ("observation", {"events": "events"}),
            ("interpretation", {"events": "events", "observation": "observation"}),
            ("media", {"events": "events", "observation": "observation", "interpretation": "interpretation"}),
            ("important_past_events", {"events": "events", "observation": "observation", "interpretation": "interpretation", "media": "media"}),
            ("social_structure", {"events": "events", "observation": "observation", "interpretation": "interpretation", "media": "media", "important_past_events": "important_past_events"}),
            (
                "living_environment",
                {
                    "events": "events",
                    "observation": "observation",
                    "interpretation": "interpretation",
                    "media": "media",
                    "important_past_events": "important_past_events",
                    "social_structure": "social_structure",
                },
            ),
            (
                "social_groups",
                {
                    "events": "events",
                    "observation": "observation",
                    "interpretation": "interpretation",
                    "media": "media",
                    "important_past_events": "important_past_events",
                    "social_structure": "social_structure",
                    "living_environment": "living_environment",
                },
            ),
            (
                "people_list",
                {
                    "events": "events",
                    "observation": "observation",
                    "interpretation": "interpretation",
                    "media": "media",
                    "important_past_events": "important_past_events",
                    "social_structure": "social_structure",
                    "living_environment": "living_environment",
                    "social_groups": "social_groups",
                },
            ),
            ("future_scenarios", {"events": "events", "observation": "observation", "interpretation": "interpretation", "media": "media", "important_past_events": "important_past_events", "social_structure": "social_structure", "living_environment": "living_environment", "social_groups": "social_groups", "people_list": "people_list"}),
        ]

        for i, (element_name, dependencies) in enumerate(elements, start=10):
            logger.info(f"Generating {element_name}...")

            if element_name in world_data:
                if self._resume_json_is_valid(element_name, world_data[element_name]):
                    continue
                world_data.pop(element_name, None)

            element_prompt = self.prompts.get(element_name, {})
            if not element_prompt:
                logger.warning(f"No prompt found for {element_name}")
                continue

            # Build prompt with dependencies
            prompt_vars = {"plottype": phase1_results.get("plottype", "")}
            for dep_key, dep_value in dependencies.items():
                prompt_vars[dep_key] = world_data.get(dep_value, "")

            prompt = format_prompt(element_prompt.get("user", ""), **prompt_vars)

            # A 100-person JSON response is too large and brittle for many
            # local models. Generate it in bounded batches, just like the
            # Phase 1 lists, and retain the partial list in the checkpoint so
            # an interrupted run can continue without losing completed people.
            if element_name == "people_list":
                batch_size = int(phase_config.get("people_items_per_request", 20))
                if batch_size < 1:
                    raise ValueError(
                        "phase3_world.people_items_per_request must be positive"
                    )
                partial_people = world_data.get("_partial_people_list", [])
                if not isinstance(partial_people, list):
                    partial_people = []
                partial_people = partial_people[:100]
                batch_prefix = "phase3_people_list_batch_"
                previous_batches = [
                    int(request_key[len(batch_prefix):])
                    for request_key in self.manifest.data.get("requests", {})
                    if request_key.startswith(batch_prefix)
                    and request_key[len(batch_prefix):].isdigit()
                ]
                batch_index = (
                    max(previous_batches) + 1
                    if previous_batches
                    else (len(partial_people) + batch_size - 1) // batch_size + 1
                )
                while len(partial_people) < 100:
                    batch_count = min(batch_size, 100 - len(partial_people))
                    batch_prompt = (
                        f"{prompt}\n\nこのリクエストは100人分の分割生成です。"
                        f"今回は{batch_count}人だけを生成してください。"
                        f"JSONのpeople配列にも{batch_count}人だけを入れてください。"
                    )
                    batch_response = self._generate_json(
                        batch_prompt,
                        phase_config,
                        system_prompt=element_prompt.get("system", None),
                        request_key=f"phase3_people_list_batch_{batch_index}",
                    )
                    if not isinstance(batch_response, dict):
                        raise OutputValidationError(
                            "people_list", [f"people batch {batch_index} was not an object"]
                        )
                    batch_people = batch_response.get("people")
                    if not isinstance(batch_people, list) or not batch_people:
                        raise OutputValidationError(
                            "people_list",
                            [f"people batch {batch_index} did not return a non-empty list"],
                        )
                    batch_errors = []
                    for item_index, person in enumerate(batch_people, start=1):
                        if not isinstance(person, dict):
                            batch_errors.append(
                                f"people batch {batch_index}[{item_index}] must be an object"
                            )
                            continue
                        for field in ("name", "age", "gender", "residence", "role"):
                            if not person.get(field):
                                batch_errors.append(
                                    f"people batch {batch_index}[{item_index}].{field} is required"
                                )
                    if batch_errors:
                        raise OutputValidationError("people_list", batch_errors)
                    partial_people.extend(batch_people[: 100 - len(partial_people)])
                    world_data["_partial_people_list"] = partial_people
                    self.checkpoint_manager.save_checkpoint("phase3_world", world_data)
                    batch_index += 1

                response = {"people": partial_people}
                self._validate_json_output(element_name, response)
                world_data[element_name] = dict_to_yaml(response)
                world_data.pop("_partial_people_list", None)
                save_yaml(response, str(self.intermediate_dir / f"{i:02d}_{element_name}.yaml"))
                self.checkpoint_manager.save_checkpoint("phase3_world", world_data)
                continue

            response = self._generate_json(
                prompt,
                phase_config,
                system_prompt=element_prompt.get("system", None),
                request_key=f"phase3_{element_name}",
            )

            if response:
                self._validate_json_output(element_name, response)
                world_data[element_name] = dict_to_yaml(response)
                save_yaml(response, str(self.intermediate_dir / f"{i:02d}_{element_name}.yaml"))
                self.checkpoint_manager.save_checkpoint("phase3_world", world_data)

        # Save checkpoint
        self.checkpoint_manager.save_checkpoint("phase3_world", world_data)
        logger.info("✓ Phase 3 completed")
        return world_data

    @run_lifecycle
    def run_full_pipeline(
        self,
        user_context: Optional[str] = None,
        context_images: Optional[Sequence[Union[str, Path, bytes]]] = None,
        extract_context: bool = False,
    ) -> Dict[str, Any]:
        """
        Run the complete pipeline

        Args:
            user_context: Optional pre-extracted user context

        Returns:
            Dictionary of all generated content
        """
        logger.info("=" * 60)
        logger.info("Starting Full Pipeline Execution")
        logger.info("=" * 60)

        # Check prerequisites
        if not self.check_prerequisites(include_vision=bool(context_images)):
            logger.error("Prerequisites not met. Aborting.")
            return {}

        results = {}

        # Phase 0: Context extraction
        if user_context is None or context_images or extract_context:
            user_context = self.run_phase0_context_extraction(
                user_input=user_context,
                image_paths=context_images,
                extract=extract_context,
            )
        else:
            # Persist explicitly supplied context too, so every run is
            # self-contained and can be resumed without the original input.
            user_context = self.run_phase0_context_extraction(
                user_input=user_context,
            )
        results["user_context"] = user_context

        # Phase 1: 100x expansion
        phase1_results = self.run_phase1_expansion(user_context)
        results.update(phase1_results)

        # Phase 2: Character generation
        characters_list = self.run_phase2_characters(user_context, phase1_results)
        results["characters_list"] = characters_list

        # Phase 3: World building
        world_data = self.run_phase3_world_building(phase1_results)
        results.update(world_data)

        # Phase 4: Plot generation
        plot_data = self.run_phase4_plot_generation(user_context, phase1_results, characters_list, world_data)
        results.update(plot_data)

        # Phase 5: Novel generation
        novels = self.run_phase5_novel_generation(characters_list, plot_data)
        results["novels"] = novels

        # Phase 6: Reference material generation
        references = self.run_phase6_reference_generation(user_context, phase1_results, characters_list, world_data, plot_data)
        results["references"] = references

        self._validate_phase_state("phase1_expansion", phase1_results)
        self._validate_phase_state(
            "phase2_characters", {"characters_list": characters_list}
        )
        self._validate_phase_state("phase3_world", world_data)
        self._validate_phase_state("phase4_plot", plot_data)
        self._validate_phase_state("phase5_novels", novels)
        self._validate_phase_state("phase6_references", references)
        self.manifest.update(
            user_context_sha256=hashlib.sha256(user_context.encode("utf-8")).hexdigest()
        )
        self._generate_quality_report()

        logger.info("=" * 60)
        logger.info("Pipeline Execution Complete")
        logger.info("=" * 60)

        return results

    @run_lifecycle
    def resume_full_pipeline(self) -> Dict[str, Any]:
        """Continue this run from its latest available phase checkpoints.

        The instance must be created with the original ``run_id``.  Each
        phase loads its partial checkpoint and skips already completed items,
        allowing an interrupted run to continue without contacting a cloud
        service or repeating completed requests.
        """
        logger.info(f"Resuming full pipeline (run_id={self.run_id})")
        if not self.check_prerequisites():
            logger.error("Prerequisites not met. Cannot resume.")
            return {}
        context_checkpoint = self.checkpoint_manager.load_checkpoint("phase0_context")
        if not context_checkpoint or not context_checkpoint.get("user_context"):
            logger.error("Cannot resume: phase0_context checkpoint is missing")
            return {}

        self._resume_mode = True
        try:
            user_context = context_checkpoint["user_context"]
            results: Dict[str, Any] = {"user_context": user_context}

            phase1_results = self.run_phase1_expansion(user_context)
            results.update(phase1_results)

            characters_list = self.run_phase2_characters(user_context, phase1_results)
            results["characters_list"] = characters_list

            world_data = self.run_phase3_world_building(phase1_results)
            results.update(world_data)

            plot_data = self.run_phase4_plot_generation(
                user_context, phase1_results, characters_list, world_data
            )
            results.update(plot_data)

            novels = self.run_phase5_novel_generation(characters_list, plot_data)
            results["novels"] = novels

            references = self.run_phase6_reference_generation(
                user_context, phase1_results, characters_list, world_data, plot_data
            )
            results["references"] = references
            self._validate_phase_state("phase1_expansion", phase1_results)
            self._validate_phase_state(
                "phase2_characters", {"characters_list": characters_list}
            )
            self._validate_phase_state("phase3_world", world_data)
            self._validate_phase_state("phase4_plot", plot_data)
            self._validate_phase_state("phase5_novels", novels)
            self._validate_phase_state("phase6_references", references)
            self.manifest.update(
                user_context_sha256=hashlib.sha256(user_context.encode("utf-8")).hexdigest()
            )
            self._generate_quality_report()
            return results
        finally:
            self._resume_mode = False

    @phase_lifecycle("phase4_plot")
    def run_phase4_plot_generation(
        self,
        user_context: str,
        phase1_results: Dict[str, str],
        characters_list: str,
        world_data: Dict[str, str]
    ) -> Dict[str, str]:
        """
        Phase 4: Plot generation
        Generate 10-chapter plot and extract keywords/references

        Args:
            user_context: User context
            phase1_results: Phase 1 results
            characters_list: Characters list
            world_data: World building data

        Returns:
            Dictionary of plot data
        """
        logger.info("=== Phase 4: Plot Generation ===")

        phase_config = self.config.get("phases", {}).get("phase4_plot", {})
        plot_data = self._resume_data("phase4_plot")

        # Generate main plot
        logger.info("Generating main plot...")
        plot_prompt = self.prompts.get("plot", {})
        if "plot" in plot_data and not self._resume_json_is_valid(
            "plot", plot_data["plot"]
        ):
            plot_data.pop("plot", None)
        if plot_prompt and "plot" not in plot_data:
            prompt = format_prompt(
                plot_prompt.get("user", ""),
                user_context=user_context,
                plottype=phase1_results.get("plottype", ""),
                characters_list=characters_list,
                world_data=dict_to_yaml(world_data),
            )
            response = self._generate_json(
                prompt,
                phase_config,
                system_prompt=plot_prompt.get("system", None),
                request_key="phase4_plot",
            )
            if response:
                self._validate_json_output("plot", response)
                plot_data["plot"] = dict_to_yaml(response)
                save_yaml(response, str(self.intermediate_dir / "20_plot.yaml"))
                self.checkpoint_manager.save_checkpoint("phase4_plot", plot_data)

        # Extract and process each chapter
        logger.info("Processing chapters...")
        for chapter_num in tqdm(range(1, 11), desc="Chapters"):
            # Extract chapter
            extract_prompt = self.prompts.get("extract_chapter", {})
            if (
                extract_prompt
                and "plot" in plot_data
                and (
                    f"plot_{chapter_num}" not in plot_data
                    or not self._resume_json_is_valid(
                        "plot_chapter",
                        plot_data.get(f"plot_{chapter_num}"),
                        chapter_number=chapter_num,
                    )
                )
            ):
                plot_data.pop(f"plot_{chapter_num}", None)
                prompt = format_prompt(
                    extract_prompt.get("user", ""),
                    plot=plot_data["plot"],
                    chapter_number=chapter_num
                )
                chapter_response = self._generate_json(
                    prompt,
                    phase_config,
                    system_prompt=extract_prompt.get("system", None),
                    request_key=f"phase4_plot_{chapter_num}",
                )
                if chapter_response:
                    self._validate_json_output(
                        "plot_chapter", chapter_response, chapter_number=chapter_num
                    )
                    plot_data[f"plot_{chapter_num}"] = dict_to_yaml(chapter_response)
                    save_yaml(chapter_response, str(self.intermediate_dir / f"{20 + chapter_num}_plot_{chapter_num}.yaml"))
                    self.checkpoint_manager.save_checkpoint("phase4_plot", plot_data)

            # Extract keywords
            keywords_prompt = self.prompts.get("extract_keywords", {})
            if (
                keywords_prompt
                and f"plot_{chapter_num}" in plot_data
                and (
                    f"plot_keywords_{chapter_num}" not in plot_data
                    or not self._resume_json_is_valid(
                        "keywords", plot_data.get(f"plot_keywords_{chapter_num}")
                    )
                )
            ):
                plot_data.pop(f"plot_keywords_{chapter_num}", None)
                prompt = format_prompt(
                    keywords_prompt.get("user", ""),
                    chapter_plot=plot_data[f"plot_{chapter_num}"]
                )
                keywords_response = self._generate_json(
                    prompt,
                    phase_config,
                    system_prompt=keywords_prompt.get("system", None),
                    request_key=f"phase4_keywords_{chapter_num}",
                )
                if keywords_response:
                    self._validate_json_output("keywords", keywords_response)
                    plot_data[f"plot_keywords_{chapter_num}"] = dict_to_yaml(keywords_response)
                    save_yaml(keywords_response, str(self.intermediate_dir / f"{30 + chapter_num}_plot_keywords_{chapter_num}.yaml"))
                    self.checkpoint_manager.save_checkpoint("phase4_plot", plot_data)

            # Search references
            references_prompt = self.prompts.get("search_references", {})
            if (
                references_prompt
                and f"plot_keywords_{chapter_num}" in plot_data
                and (
                    f"plot_reference_{chapter_num}" not in plot_data
                    or not self._resume_json_is_valid(
                        "references", plot_data.get(f"plot_reference_{chapter_num}")
                    )
                )
            ):
                plot_data.pop(f"plot_reference_{chapter_num}", None)
                prompt = format_prompt(
                    references_prompt.get("user", ""),
                    keywords=plot_data[f"plot_keywords_{chapter_num}"],
                    world_data=dict_to_yaml(
                        {
                            "characters": characters_list,
                            # The 100-person persona list is not needed to
                            # locate chapter references and would dominate
                            # every repeated prompt. Keep chapter reference
                            # requests bounded so local generation remains
                            # practical.
                            "world": {
                                key: value
                                for key, value in world_data.items()
                                if key != "people_list"
                            },
                        }
                    )
                )
                references_response = self._generate_json(
                    prompt,
                    phase_config,
                    system_prompt=references_prompt.get("system", None),
                    request_key=f"phase4_references_{chapter_num}",
                )
                if references_response:
                    # Some local models ignore the "related references"
                    # bound and return a much larger list. Keep the artifact
                    # within its documented contract before validation and
                    # checkpointing so one verbose response cannot abort a run.
                    if isinstance(references_response.get("references"), list):
                        references_response["references"] = references_response[
                            "references"
                        ][:20]
                    self._validate_json_output("references", references_response)
                    plot_data[f"plot_reference_{chapter_num}"] = dict_to_yaml(references_response)
                    save_yaml(references_response, str(self.intermediate_dir / f"{40 + chapter_num}_plot_reference_{chapter_num}.yaml"))
                    self.checkpoint_manager.save_checkpoint("phase4_plot", plot_data)

        self.checkpoint_manager.save_checkpoint("phase4_plot", plot_data)
        logger.info("✓ Phase 4 completed")
        return plot_data

    @phase_lifecycle("phase5_novels")
    def run_phase5_novel_generation(
        self,
        characters_list: str,
        plot_data: Dict[str, str]
    ) -> Dict[str, str]:
        """
        Phase 5: Novel generation
        Generate novel text for all 10 chapters

        Args:
            characters_list: Characters list
            plot_data: Plot data from Phase 4

        Returns:
            Dictionary of generated novels
        """
        logger.info("=== Phase 5: Novel Generation ===")

        phase_config = self.config.get("phases", {}).get("phase5_novel", {})
        novels = self._resume_data("phase5_novels")

        story_prompt = self.prompts.get("story_chapter", {})
        if not story_prompt:
            logger.error("No story prompt found")
            return novels

        for chapter_num in tqdm(range(1, 11), desc="Generating novels"):
            logger.info(f"Generating Chapter {chapter_num}...")

            if f"story_{chapter_num}" in novels:
                continue

            prompt = format_prompt(
                story_prompt.get("user", ""),
                chapter_number=chapter_num,
                characters_list=characters_list,
                chapter_plot=plot_data.get(f"plot_{chapter_num}", ""),
                chapter_references=plot_data.get(f"plot_reference_{chapter_num}", "")
            )

            response = self._generate_text(
                prompt,
                phase_config,
                system_prompt=story_prompt.get("system", ""),
                role="story",
                long_form=True,
                request_key=f"phase5_story_{chapter_num}",
            )

            if response:
                novels[f"story_{chapter_num}"] = response
                save_text(response, str(self.novels_dir / f"chapter_{chapter_num:02d}.txt"))
                self.checkpoint_manager.save_checkpoint("phase5_novels", novels)

        self.checkpoint_manager.save_checkpoint("phase5_novels", novels)
        logger.info("✓ Phase 5 completed")
        return novels

    @phase_lifecycle("phase6_references")
    def run_phase6_reference_generation(
        self,
        user_context: str,
        phase1_results: Dict[str, str],
        characters_list: str,
        world_data: Dict[str, str],
        plot_data: Dict[str, str]
    ) -> Dict[str, str]:
        """
        Phase 6: Reference material generation
        Generate detailed reference materials

        Args:
            user_context: User context
            phase1_results: Phase 1 results
            characters_list: Characters list
            world_data: World building data
            plot_data: Plot data

        Returns:
            Dictionary of generated references
        """
        logger.info("=== Phase 6: Reference Generation ===")

        phase_config = self.config.get("phases", {}).get("phase6_references", {})
        references = self._resume_data("phase6_references")

        # List of references to generate
        reference_types = [
            ("reference_characters", "characters.md", {"characters_list": characters_list}),
            ("reference_plot", "plot.md", {"plot": plot_data.get("plot", "")}),
            ("reference_user_context", "user_context.md", {"user_context": user_context}),
            ("reference_desire_list", "desire_list.md", {"desire_list": phase1_results.get("desire_list", "")}),
            ("reference_ability_list", "ability_list.md", {"ability_list": phase1_results.get("ability_list", "")}),
            ("reference_role_list", "role_list.md", {"role_list": phase1_results.get("role_list", "")}),
            ("reference_plottype_list", "plottype_list.md", {"plottype_list": phase1_results.get("plottype_list", ""), "plottype": phase1_results.get("plottype", "")}),
        ]

        # Add world elements
        for element_name in world_data.keys():
            reference_types.append(
                ("reference_world_element", f"{element_name}.md", {"element_name": element_name, "element_data": world_data[element_name]})
            )

        for prompt_name, filename, prompt_vars in tqdm(reference_types, desc="Generating references"):
            logger.info(f"Generating {filename}...")

            if filename in references:
                continue

            ref_prompt = self.prompts.get(prompt_name, {})
            if not ref_prompt:
                logger.warning(f"No prompt found for {prompt_name}")
                continue

            prompt = format_prompt(ref_prompt.get("user", ""), **prompt_vars)

            response = self._generate_text(
                prompt,
                phase_config,
                system_prompt=ref_prompt.get("system", ""),
                role="reference",
                long_form=True,
                request_key=f"phase6_reference_{filename}",
            )

            if response:
                references[filename] = response
                save_text(response, str(self.references_dir / filename))
                self.checkpoint_manager.save_checkpoint("phase6_references", references)

        self.checkpoint_manager.save_checkpoint("phase6_references", references)
        logger.info("✓ Phase 6 completed")
        return references

    def resume_from_checkpoint(self, phase_name: str) -> bool:
        """
        Resume pipeline from a checkpoint

        Args:
            phase_name: Name of the phase to resume from

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Resuming from checkpoint: {phase_name}")

        checkpoint_data = self.checkpoint_manager.load_checkpoint(phase_name)
        if checkpoint_data is None:
            logger.error(f"Failed to load checkpoint: {phase_name}")
            return False

        # Load state
        for key, value in checkpoint_data.items():
            self.checkpoint_manager.update_state(key, value)

        logger.info("✓ Checkpoint loaded successfully")
        return True
