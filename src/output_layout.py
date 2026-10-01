"""Filesystem layout for generated world outputs."""

from pathlib import Path


def world_package_name(run_id: str) -> str:
    """Return the directory name for one generated world package."""
    return f"world_{run_id}"


def world_package_path(root: Path, run_id: str) -> Path:
    """Return the package directory for ``run_id`` under ``root``."""
    return Path(root) / world_package_name(run_id)
