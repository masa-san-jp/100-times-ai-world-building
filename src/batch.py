"""Batch execution for repeated local world-building experiments."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Union

from loguru import logger

from .pipeline import Pipeline
from .utils import load_config


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _derive_run_seed(batch_seed: int, index: int) -> int:
    material = f"{batch_seed}:{index}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % (
        2**31 - 1
    )


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


class BatchRunner:
    """Run independent pipelines sequentially and keep a durable summary."""

    def __init__(self, pipeline_kwargs: Optional[Dict[str, Any]] = None):
        self.pipeline_kwargs = dict(pipeline_kwargs or {})

    def run(
        self,
        user_context: Optional[str],
        runs: int,
        seed: Optional[int] = None,
        context_images: Optional[Sequence[Union[str, Path, bytes]]] = None,
        extract_context: bool = False,
        continue_on_error: bool = True,
    ) -> Dict[str, Any]:
        """Run ``runs`` independent executions and return the batch summary."""
        if runs < 1:
            raise ValueError("runs must be at least 1")

        kwargs = dict(self.pipeline_kwargs)
        config_path = kwargs.get("config_path", "config/ollama_config.yaml")
        config = load_config(config_path)
        output_root = Path(
            kwargs.get("output_dir")
            or config.get("output", {}).get("base_dir", "./output")
        )
        batch_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        batch_dir = output_root / f"batch_{batch_id}"
        summary_path = batch_dir / "batch_manifest.json"
        while batch_dir.exists():
            batch_id = f"{batch_id}_{secrets.token_hex(2)}"
            batch_dir = output_root / f"batch_{batch_id}"
            summary_path = batch_dir / "batch_manifest.json"

        worlds_dir = batch_dir / "worlds"
        # A batch is itself one package containing its manifest and the
        # independent world packages produced by each iteration.
        batch_pipeline_kwargs = dict(kwargs)
        batch_pipeline_kwargs["output_dir"] = str(worlds_dir)

        batch_seed = int(seed) if seed is not None else secrets.randbits(32)
        summary: Dict[str, Any] = {
            "schema_version": 1,
            "layout_version": 2,
            "artifact_type": "world_batch",
            "batch_id": batch_id,
            "batch_seed": batch_seed,
            "requested_runs": runs,
            "created_at": _utc_now(),
            "status": "running",
            "runs": [],
            "summary_path": str(summary_path),
            "output_dir": str(batch_dir),
            "worlds_dir": str(worlds_dir),
        }
        _atomic_write_json(summary_path, summary)

        for index in range(1, runs + 1):
            run_seed = _derive_run_seed(batch_seed, index)
            run_kwargs = dict(batch_pipeline_kwargs)
            run_kwargs.pop("run_id", None)
            run_kwargs["seed"] = run_seed
            started = time.monotonic()
            record: Dict[str, Any] = {
                "index": index,
                "run_seed": run_seed,
                "status": "running",
                "started_at": _utc_now(),
            }
            pipeline: Optional[Pipeline] = None
            try:
                pipeline = Pipeline(**run_kwargs)
                record["run_id"] = pipeline.run_id
                record["output_dir"] = pipeline.base_dir
                result = pipeline.run_full_pipeline(
                    user_context,
                    context_images=context_images,
                    extract_context=extract_context,
                )
                if (
                    not result
                    or pipeline.manifest.data.get("status") != "completed"
                ):
                    raise RuntimeError(
                        "pipeline did not complete successfully"
                    )
                record["status"] = "completed"
            except KeyboardInterrupt:
                record["status"] = "cancelled"
                summary["runs"].append(record)
                summary["status"] = "cancelled"
                summary["finished_at"] = _utc_now()
                _atomic_write_json(summary_path, summary)
                raise
            except Exception as exc:
                record["status"] = "failed"
                record["error"] = str(exc)
                logger.error(f"Batch run {index}/{runs} failed: {exc}")
                if pipeline is not None:
                    record["manifest"] = str(pipeline.manifest.path)
                if not continue_on_error:
                    summary["runs"].append(record)
                    summary["status"] = "failed"
                    summary["finished_at"] = _utc_now()
                    _atomic_write_json(summary_path, summary)
                    raise
            finally:
                record["duration_seconds"] = round(
                    time.monotonic() - started, 3
                )
                if record not in summary["runs"]:
                    summary["runs"].append(record)
                summary["completed_runs"] = sum(
                    item["status"] == "completed" for item in summary["runs"]
                )
                summary["failed_runs"] = sum(
                    item["status"] == "failed" for item in summary["runs"]
                )
                summary["cancelled_runs"] = sum(
                    item["status"] == "cancelled" for item in summary["runs"]
                )
                _atomic_write_json(summary_path, summary)

        summary["status"] = (
            "completed"
            if summary.get("failed_runs", 0) == 0
            else "completed_with_errors"
        )
        summary["finished_at"] = _utc_now()
        _atomic_write_json(summary_path, summary)

        if runs >= 2:
            try:
                from .compare import create_comparison_report

                world_dirs = [
                    Path(record["output_dir"])
                    for record in summary["runs"]
                    if record.get("status") == "completed"
                    and record.get("output_dir")
                ]
                if world_dirs:
                    _, comparison_path = create_comparison_report(
                        world_dirs, batch_dir / "comparison.md"
                    )
                    summary["comparison_path"] = str(comparison_path)
                    _atomic_write_json(summary_path, summary)
            except Exception as exc:
                logger.warning(f"Batch comparison generation failed: {exc}")

        return summary


def run_batch(
    user_context: Optional[str],
    runs: int,
    seed: Optional[int] = None,
    pipeline_kwargs: Optional[Dict[str, Any]] = None,
    context_images: Optional[Sequence[Union[str, Path, bytes]]] = None,
    extract_context: bool = False,
    continue_on_error: bool = True,
) -> Dict[str, Any]:
    """Convenience wrapper around :class:`BatchRunner`."""
    return BatchRunner(pipeline_kwargs).run(
        user_context=user_context,
        runs=runs,
        seed=seed,
        context_images=context_images,
        extract_context=extract_context,
        continue_on_error=continue_on_error,
    )
