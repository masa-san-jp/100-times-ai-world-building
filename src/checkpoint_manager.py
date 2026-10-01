"""
Checkpoint Manager Module
Handles saving and loading of checkpoints during pipeline execution
"""

import gzip
import json
import os
from pathlib import Path
from datetime import datetime
import tempfile
from typing import Dict, Any, Optional, List
from loguru import logger


class CheckpointManager:
    """Manages checkpoints for the AI world building pipeline"""

    def __init__(
        self,
        checkpoint_dir: str = "./output/world_manual/checkpoints",
        auto_save: bool = True,
        compression: bool = False,
        max_checkpoints_per_phase: Optional[int] = 100,
    ):
        """
        Initialize checkpoint manager

        Args:
            checkpoint_dir: Directory to store checkpoints
            auto_save: Whether to auto-save after each phase
            compression: Whether to gzip checkpoint files
            max_checkpoints_per_phase: Number of generations to retain per phase
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.auto_save = auto_save
        self.compression = compression
        self.max_checkpoints_per_phase = max_checkpoints_per_phase
        self.phase_status_path = self.checkpoint_dir / "phase_status.json"

        # In-memory state
        self.current_state: Dict[str, Any] = {}
        self.phase_statuses: Dict[str, Dict[str, Any]] = self._load_phase_statuses()

        logger.info(f"CheckpointManager initialized: {self.checkpoint_dir}")

    def save_checkpoint(
        self,
        phase_name: str,
        data: Dict[str, Any],
        timestamp: Optional[str] = None,
    ) -> str:
        """
        Save checkpoint data

        Args:
            phase_name: Name of the phase (e.g., "world_explore")
            data: Data to save
            timestamp: Optional timestamp (auto-generated if None)

        Returns:
            Path to saved checkpoint file
        """
        if timestamp is None:
            # Microseconds prevent several requests in one second from
            # overwriting one another during long phases.
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        suffix = ".json.gz" if self.compression else ".json"
        filename = f"{phase_name}_{timestamp}{suffix}"
        filepath = self.checkpoint_dir / filename

        try:
            serialized = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            if self.compression:
                serialized = gzip.compress(serialized)
            self._atomic_write(filepath, serialized)
            self._enforce_retention(phase_name)

            logger.info(f"✓ Checkpoint saved: {filepath}")
            return str(filepath)

        except Exception as e:
            logger.error(f"Failed to save checkpoint {filepath}: {e}")
            raise

    def load_checkpoint(self, phase_name: str) -> Optional[Dict[str, Any]]:
        """
        Load the latest checkpoint for a phase

        Args:
            phase_name: Name of the phase

        Returns:
            Checkpoint data, or None if not found
        """
        checkpoint_files = self._checkpoint_files(phase_name)

        if not checkpoint_files:
            logger.warning(f"No checkpoint found for phase: {phase_name}")
            return None

        for checkpoint in checkpoint_files:
            try:
                data = self._read_checkpoint(checkpoint)
            except Exception as exc:
                logger.warning(f"Skipping unreadable checkpoint {checkpoint}: {exc}")
                continue
            if isinstance(data, dict):
                logger.info(f"Loaded checkpoint: {checkpoint}")
                return data
            logger.warning(f"Skipping invalid checkpoint: {checkpoint}")

        logger.error(f"No valid checkpoint found for phase: {phase_name}")
        return None

    def load_specific_checkpoint(self, filepath: str) -> Optional[Dict[str, Any]]:
        """
        Load a specific checkpoint file

        Args:
            filepath: Path to checkpoint file

        Returns:
            Checkpoint data, or None on error
        """
        try:
            data = self._read_checkpoint(Path(filepath))
            if not isinstance(data, dict):
                logger.error(f"Checkpoint must contain a JSON object: {filepath}")
                return None
            logger.info(f"Loaded checkpoint: {filepath}")
            return data
        except FileNotFoundError:
            logger.error(f"Checkpoint file not found: {filepath}")
            return None
        except Exception as e:
            logger.error(f"Failed to load checkpoint {filepath}: {e}")
            return None

    def list_checkpoints(self, phase_name: Optional[str] = None) -> List[str]:
        """
        List all checkpoint files

        Args:
            phase_name: Optional phase name filter

        Returns:
            List of checkpoint file paths
        """
        if phase_name:
            checkpoint_files = self._checkpoint_files(phase_name)
        else:
            checkpoint_files = sorted(
                [
                    path
                    for path in self.checkpoint_dir.iterdir()
                    if path.is_file()
                    and path.name != self.phase_status_path.name
                    and (path.name.endswith(".json") or path.name.endswith(".json.gz"))
                ],
                reverse=True,
            )

        filepaths = [str(f) for f in checkpoint_files]
        logger.info(f"Found {len(filepaths)} checkpoint(s)")
        return filepaths

    def delete_checkpoint(self, filepath: str) -> bool:
        """
        Delete a checkpoint file

        Args:
            filepath: Path to checkpoint file

        Returns:
            True if successful, False otherwise
        """
        try:
            Path(filepath).unlink()
            logger.info(f"Deleted checkpoint: {filepath}")
            return True
        except FileNotFoundError:
            logger.error(f"Checkpoint file not found: {filepath}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete checkpoint {filepath}: {e}")
            return False

    def clear_phase_checkpoints(self, phase_name: str) -> int:
        """
        Delete all checkpoints for a specific phase

        Args:
            phase_name: Name of the phase

        Returns:
            Number of deleted checkpoints
        """
        checkpoint_files = self._checkpoint_files(phase_name)

        deleted_count = 0
        for filepath in checkpoint_files:
            try:
                filepath.unlink()
                deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to delete {filepath}: {e}")

        logger.info(f"Deleted {deleted_count} checkpoint(s) for phase: {phase_name}")
        return deleted_count

    def mark_phase(
        self,
        phase_name: str,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """Persist a phase lifecycle status next to checkpoint generations."""
        phase = dict(self.phase_statuses.get(phase_name, {}))
        phase["status"] = status
        phase["updated_at"] = datetime.now().isoformat(timespec="seconds")
        if status == "running" and "started_at" not in phase:
            phase["started_at"] = phase["updated_at"]
        if status in {"completed", "failed", "cancelled"}:
            phase["finished_at"] = phase["updated_at"]
        if error:
            phase["error"] = error
        elif status != "failed":
            phase.pop("error", None)
        self.phase_statuses[phase_name] = phase
        self._atomic_write(
            self.phase_status_path,
            json.dumps(self.phase_statuses, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    def get_phase_status(self, phase_name: str) -> Optional[Dict[str, Any]]:
        """Return a copy of one phase status, if known."""
        status = self.phase_statuses.get(phase_name)
        return dict(status) if status else None

    def get_phase_statuses(self) -> Dict[str, Dict[str, Any]]:
        """Return a copy of all persisted phase statuses."""
        return {name: dict(status) for name, status in self.phase_statuses.items()}

    def _checkpoint_files(self, phase_name: str) -> List[Path]:
        files = list(self.checkpoint_dir.glob(f"{phase_name}_*.json"))
        files.extend(self.checkpoint_dir.glob(f"{phase_name}_*.json.gz"))
        return sorted(set(files), reverse=True)

    def _read_checkpoint(self, filepath: Path) -> Optional[Dict[str, Any]]:
        if filepath.name.endswith(".json.gz"):
            with gzip.open(filepath, "rb") as handle:
                raw = handle.read()
        else:
            raw = filepath.read_bytes()
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else None

    def _load_phase_statuses(self) -> Dict[str, Dict[str, Any]]:
        if not self.phase_status_path.exists():
            return {}
        try:
            data = json.loads(self.phase_status_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("phase status must be an object")
            return {
                str(name): dict(status)
                for name, status in data.items()
                if isinstance(status, dict)
            }
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning(f"Ignoring invalid phase status file: {exc}")
            return {}

    def _enforce_retention(self, phase_name: str) -> None:
        limit = self.max_checkpoints_per_phase
        if limit is None or limit < 1:
            return
        for stale in self._checkpoint_files(phase_name)[limit:]:
            try:
                stale.unlink()
                logger.debug(f"Removed stale checkpoint: {stale}")
            except FileNotFoundError:
                pass

    @staticmethod
    def _atomic_write(filepath: Path, payload: bytes) -> None:
        """Atomically replace a file after flushing it to disk."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{filepath.name}.",
            suffix=".tmp",
            dir=str(filepath.parent),
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, filepath)
            try:
                directory_fd = os.open(filepath.parent, os.O_DIRECTORY)
            except (AttributeError, OSError):
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    def update_state(self, key: str, value: Any) -> None:
        """
        Update in-memory state

        Args:
            key: State key
            value: State value
        """
        self.current_state[key] = value
        logger.debug(f"Updated state: {key}")

    def get_state(self, key: str, default: Any = None) -> Any:
        """
        Get value from in-memory state

        Args:
            key: State key
            default: Default value if key not found

        Returns:
            State value
        """
        return self.current_state.get(key, default)

    def save_state(self, phase_name: str = "current_state") -> str:
        """
        Save current in-memory state to checkpoint

        Args:
            phase_name: Name for the state checkpoint

        Returns:
            Path to saved checkpoint
        """
        return self.save_checkpoint(phase_name, self.current_state)

    def load_state(self, phase_name: str = "current_state") -> bool:
        """
        Load checkpoint into in-memory state

        Args:
            phase_name: Name of the state checkpoint

        Returns:
            True if successful, False otherwise
        """
        data = self.load_checkpoint(phase_name)
        if data is not None:
            self.current_state = data
            logger.info("State loaded successfully")
            return True

        logger.warning("Failed to load state")
        return False

    def get_full_state(self) -> Dict[str, Any]:
        """
        Get the complete in-memory state

        Returns:
            Copy of current state dictionary
        """
        return self.current_state.copy()

    def clear_state(self) -> None:
        """Clear in-memory state"""
        self.current_state = {}
        logger.info("State cleared")

    def export_state_summary(self) -> str:
        """
        Export a summary of current state

        Returns:
            Human-readable summary string
        """
        lines = ["=" * 60]
        lines.append("Current State Summary")
        lines.append("=" * 60)

        if not self.current_state:
            lines.append("(empty)")
        else:
            for key, value in self.current_state.items():
                if isinstance(value, str):
                    preview = (
                        value[:100] + "..." if len(value) > 100 else value
                    )
                elif isinstance(value, (list, dict)):
                    preview = f"<{type(value).__name__} with {len(value)} items>"
                else:
                    preview = str(value)

                lines.append(f"{key}: {preview}")

        lines.append("=" * 60)
        return "\n".join(lines)
