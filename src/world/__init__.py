"""Input acceptance and world-axis primitives for the world-building engine."""

from .axes import WorldAxesBuilder, WorldAxesResult, load_axes, load_catalog
from .graph import (
    GraphError, GraphStore, guess_language, local_context, make_entity,
    new_graph, validate_graph,
)
from .explore import (
    Bandit, ExplorationLoop, ExplorationResult, extract_preference_pairs,
    run_world_engine,
)
from .render import RenderError, render_world_package
from .input import InputBriefBuilder, InputBriefResult, InputSourceError

__all__ = [
    "RenderError", "render_world_package",
    "Bandit", "ExplorationLoop", "ExplorationResult",
    "extract_preference_pairs", "run_world_engine",
    "GraphError", "GraphStore", "guess_language", "local_context",
    "make_entity", "new_graph", "validate_graph",
    "InputBriefBuilder", "InputBriefResult", "InputSourceError",
    "WorldAxesBuilder", "WorldAxesResult", "load_axes", "load_catalog",
]
