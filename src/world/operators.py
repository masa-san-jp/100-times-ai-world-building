"""Operation tasks, bounded context and harness-owned placement."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import yaml

from .premises import world_premises
from .graph import (
    ENTITY_TYPES, FACT_KINDS, RELATION_TYPES, SCALES, SCALE_RANK,
    get_entity, local_context, make_entity, validate_graph,
)

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
DEFAULT_PROMPT_PATH = CONFIG_DIR / "prompts" / "world" / "operators.yaml"

OPERATORS = (
    "premise", "expand", "zoom", "cause", "perspective", "history", "document",
)

# Fact kinds that count as concrete detail.
CONCRETE_KINDS = ("proper_noun", "number", "object")

# Minimum number of concrete facts by the scale of the candidate.
DEFAULT_MIN_CONCRETE_FACTS: Dict[str, int] = {
    "world": 0, "region": 1, "settlement": 2,
    "district": 2, "site": 3, "detail": 4,
}

# Structural relation the code adds from the candidate to its target.
_TARGET_RELATION = {
    "cause": "causes", "perspective": "related_to",
    "history": "affects", "document": "related_to",
}


class OperatorError(ValueError):
    """Raised for an invalid operator request (not for bad model output)."""


@dataclass
class OperatorConfig:
    min_facts: int = 1
    min_concrete_facts: Dict[str, int] = field(
        default_factory=lambda: dict(DEFAULT_MIN_CONCRETE_FACTS))
    max_statements: int = 12
    max_axes: int = 12
    max_text_chars: int = 160
    context_limits: Optional[Dict[str, int]] = None
    temperature: Optional[float] = None  # None: use the backend default


def load_prompts(path: Any = None) -> Dict[str, Any]:
    return yaml.safe_load(
        Path(path or DEFAULT_PROMPT_PATH).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ helpers

def _clip(text: Any, n: int) -> str:
    text = text if isinstance(text, str) else ""
    return text if len(text) <= n else text[: max(0, n - 1)] + "…"


def _lines(items: Sequence[str]) -> str:
    return "\n".join(items) or "(none)"


def _world_context(graph: Mapping[str, Any], cfg: OperatorConfig) -> Dict[str, Any]:
    """Bounded view of the world as a whole (for ``premise``)."""
    roots = [e for e in graph.get("entities", [])
             if e.get("scale") == "world"][:6]
    return {
        "language": (graph.get("meta") or {}).get("language"),
        "world_premises": world_premises(graph),
        "entities": [
            {"id": e["id"], "type": e.get("type"),
             "name": _clip(e.get("name"), 60),
             "summary": _clip(e.get("summary"), 240),
             "facts": [{"kind": f.get("kind"), "text": _clip(f.get("text"), 120)}
                       for f in (e.get("facts") or [])[:4]]}
            for e in roots
        ],
    }


def _min_concrete(scale: str, cfg: OperatorConfig) -> int:
    return int(cfg.min_concrete_facts.get(scale, 0))


def placement(
    operator: str, graph: Mapping[str, Any], target: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Return the scale and parent code assigns for ``operator``."""
    if operator == "premise":
        return {"scale": "world", "parent": None}
    assert target is not None
    if operator == "zoom":
        rank = SCALE_RANK[target["scale"]]
        if rank + 1 >= len(SCALES):
            raise OperatorError(
                f"cannot zoom below scale {target['scale']!r}")
        return {"scale": SCALES[rank + 1], "parent": target["id"]}
    # expand and the relation-bearing operators sit beside the target.
    return {"scale": target["scale"], "parent": target.get("parent")}


def validate_candidate(
    graph: Mapping[str, Any], candidate: Mapping[str, Any],
    axes: Optional[Sequence[Mapping[str, Any]]] = None,
    brief: Optional[Mapping[str, Any]] = None,
) -> List[str]:
    """Return errors that applying ``candidate`` would add to the graph.

    The graph itself is not modified.  Pre-existing errors are not reported.
    """
    if "premise_extension" in candidate["entity"]:
        return ["premise_extension history is verifier-managed, not candidate content"]
    baseline = set(validate_graph(graph, axes, brief))
    trial = copy.deepcopy(dict(graph))
    trial.setdefault("entities", []).append(
        copy.deepcopy(dict(candidate["entity"])))
    return [e for e in validate_graph(trial, axes, brief) if e not in baseline]
