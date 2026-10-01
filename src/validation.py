"""Validation of generated world artifacts."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import yaml


class OutputValidationError(ValueError):
    """Raised when a generated artifact violates its contract."""

    def __init__(self, artifact: str, errors: Iterable[str]):
        self.artifact = artifact
        self.errors = list(errors)
        message = "; ".join(self.errors) or "invalid output"
        super().__init__(f"{artifact}: {message}")


def _as_dict(data: Any) -> Optional[Dict[str, Any]]:
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        try:
            parsed = yaml.safe_load(data)
        except yaml.YAMLError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def validate_artifact(artifact: str, data: Any) -> List[str]:
    """Return contract violations for one generated artifact.

    Known artifacts: ``entity_graph`` (the world graph, see
    :func:`src.world.graph.validate_graph`).  Prose quality is never judged
    here; that is the verifiers' job.
    """
    value = _as_dict(data)
    if value is None:
        return [f"{artifact} must be an object"]
    if artifact == "entity_graph":
        from .world.graph import validate_graph

        return validate_graph(value)
    return []


def assert_valid_artifact(artifact: str, data: Any) -> None:
    """Raise :class:`OutputValidationError` when an artifact is invalid."""
    errors = validate_artifact(artifact, data)
    if errors:
        raise OutputValidationError(artifact, errors)
