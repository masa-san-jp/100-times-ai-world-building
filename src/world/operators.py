"""Generation operators that widen and deepen the entity graph.

Each operator receives a target (an entity id, or the whole world for
``premise``) and a candidate count ``n``.  It builds a prompt from only the
bounded ``local_context`` of the target plus a few brief statements and axes,
asks the backend once for ``n`` distinct candidates, and returns validated
candidate entities.  Candidates are *not* committed: the exploration loop
decides which to apply.

Code, never the model, assigns ids, scale and parent, adds the structural
relation to the target, drops candidates without provenance, and enforces a
minimum number of concrete facts that grows toward lower scales.

A candidate is ``{"operator": str, "target": Optional[str], "entity": dict}``
where ``entity`` has the canonical shape of :func:`make_entity` (including its
relations).
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import yaml

from ..llm import LLMBackend
from .coerce import fact_items, id_list, relation_items, text_of
from .graph import (
    ENTITY_TYPES, FACT_KINDS, RELATION_TYPES, SCALES, SCALE_RANK,
    get_entity, local_context, make_entity, validate_graph,
)

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
DEFAULT_PROMPT_PATH = CONFIG_DIR / "prompts" / "world" / "operators.yaml"
DEFAULT_REVISION_PATH = CONFIG_DIR / "prompts" / "world" / "revision.yaml"

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
    max_candidates: int = 8
    max_statements: int = 12
    max_axes: int = 12
    max_text_chars: int = 160
    context_limits: Optional[Dict[str, int]] = None
    temperature: Optional[float] = None  # None: use the backend default


def load_prompts(path: Any = None) -> Dict[str, Any]:
    return yaml.safe_load(
        Path(path or DEFAULT_PROMPT_PATH).read_text(encoding="utf-8"))


def load_revision_prompts(path: Any = None) -> Dict[str, Any]:
    return yaml.safe_load(
        Path(path or DEFAULT_REVISION_PATH).read_text(encoding="utf-8"))


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
    baseline = set(validate_graph(graph, axes, brief))
    trial = copy.deepcopy(dict(graph))
    trial.setdefault("entities", []).append(
        copy.deepcopy(dict(candidate["entity"])))
    return [e for e in validate_graph(trial, axes, brief) if e not in baseline]


# --------------------------------------------------------------- the engine

class OperatorRunner:
    """Run generation operators against a backend."""

    def __init__(
        self, backend: LLMBackend,
        config: Optional[OperatorConfig] = None,
        prompts: Optional[Mapping[str, Any]] = None,
        revision_prompts: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.backend = backend
        self.config = config or OperatorConfig()
        self.prompts = dict(prompts) if prompts else load_prompts()
        self._revision_prompts = (
            dict(revision_prompts) if revision_prompts else None)

    def run(
        self, operator: str, graph: Mapping[str, Any],
        target: Optional[str] = None, n: int = 3, *,
        brief: Optional[Mapping[str, Any]] = None,
        axes: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        if operator not in OPERATORS:
            raise OperatorError(f"unknown operator: {operator}")
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            raise OperatorError("n must be a positive integer")
        n = min(n, self.config.max_candidates)
        target_entity = None
        if operator != "premise":
            if not target:
                raise OperatorError(f"{operator} needs a target entity id")
            target_entity = get_entity(graph, target)
            if target_entity is None:
                raise OperatorError(f"unknown entity id: {target}")
        place = placement(operator, graph, target_entity)

        prompt = self._render(operator, graph, target_entity, place, n, brief, axes)
        kwargs: Dict[str, Any] = {"system_prompt": self.prompts["common"]["system"]}
        if self.config.temperature is not None:
            kwargs["temperature"] = self.config.temperature
        response = self.backend.generate_json(prompt, **kwargs)
        return self._build(
            operator, graph, target_entity, place, n, response, brief, axes)

    def revise(
        self, candidate: Mapping[str, Any], findings: Sequence[Mapping[str, Any]],
        graph: Mapping[str, Any], *,
        brief: Optional[Mapping[str, Any]] = None,
        axes: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Rewrite ``candidate`` to resolve structured review ``findings``.

        Each finding is ``{"field", "code", "message"}``.  The result is a
        validated candidate of the same operator and target, or ``None``
        when the model returns nothing usable.  Placement, ids and
        structural relations are assigned by code exactly as in ``run``.
        """
        if self._revision_prompts is None:
            self._revision_prompts = load_revision_prompts()
        cfg = self.config
        operator = candidate["operator"]
        target_id = candidate.get("target")
        target = get_entity(graph, target_id) if target_id else None
        if operator != "premise" and target is None:
            raise OperatorError(f"unknown entity id: {target_id}")
        place = placement(operator, graph, target)
        entity = candidate["entity"]
        draft = {
            "type": entity.get("type"), "name": entity.get("name"),
            "axes": list(entity.get("axes", [])),
            "summary": entity.get("summary"),
            "facts": [{"kind": f.get("kind"), "text": f.get("text")}
                      for f in entity.get("facts", [])],
            "statement_ids": list(
                (entity.get("provenance") or {}).get("statement_ids", [])),
            "derived_from": list(
                (entity.get("provenance") or {}).get("derived_from", [])),
            "reason": (entity.get("provenance") or {}).get("reason", ""),
        }
        statements = [
            f"{s['id']}: {_clip(s.get('text'), cfg.max_text_chars)}"
            for s in (brief or {}).get("statements", []) or []
            if isinstance(s, Mapping) and s.get("id") and s.get("text")
        ][: cfg.max_statements]
        axis_lines = [
            f"{a['id']}: {_clip(a.get('name'), 40)} - "
            f"{_clip(a.get('meaning'), cfg.max_text_chars)}"
            for a in axes or [] if isinstance(a, Mapping) and a.get("id")
        ][: cfg.max_axes]
        ctx = (_world_context(graph, cfg) if target is None
               else local_context(graph, target["id"], cfg.context_limits))
        need = _min_concrete(place["scale"], cfg)
        concrete_rule = (
            f"At least {need} of them must be of kind "
            f"{'/'.join(CONCRETE_KINDS)}." if need else
            "Prefer facts of kind " + "/".join(CONCRETE_KINDS) + ".")
        lines = [
            f"- {f.get('field', 'entity')} | {f.get('code', '')} | "
            f"{_clip(f.get('message'), 200)}" for f in findings]
        common = self._revision_prompts["common"]
        prompt = common["user"].format(
            language=(graph.get("meta") or {}).get("language", ""),
            operator=operator,
            target_note=(f" on the entity {target['id']}" if target else ""),
            draft=json.dumps(draft, ensure_ascii=False, separators=(",", ":")),
            findings=_lines(lines), statements=_lines(statements),
            axes=_lines(axis_lines),
            context=json.dumps(ctx, ensure_ascii=False, separators=(",", ":")),
            min_facts=cfg.min_facts, concrete_rule=concrete_rule)
        kwargs: Dict[str, Any] = {"system_prompt": common["system"]}
        if cfg.temperature is not None:
            kwargs["temperature"] = cfg.temperature
        response = self.backend.generate_json(prompt, **kwargs)
        out = self._build(
            operator, graph, target, place, 1, response, brief, axes)
        return out[0] if out else None

    # -- prompt
    def _render(self, operator, graph, target, place, n, brief, axes) -> str:
        cfg = self.config
        statements = [
            f"{s['id']}: {_clip(s.get('text'), cfg.max_text_chars)}"
            for s in (brief or {}).get("statements", []) or []
            if isinstance(s, Mapping) and s.get("id") and s.get("text")
        ][: cfg.max_statements]
        axis_lines = [
            f"{a['id']}: {_clip(a.get('name'), 40)} - "
            f"{_clip(a.get('meaning'), cfg.max_text_chars)}"
            for a in axes or [] if isinstance(a, Mapping) and a.get("id")
        ][: cfg.max_axes]
        if target is None:
            ctx = _world_context(graph, cfg)
        else:
            ctx = local_context(graph, target["id"], cfg.context_limits)
        task = self.prompts["operators"][operator].strip()
        if target is not None:
            task += f"\nTARGET entity id: {target['id']} (scale {target['scale']})."
        if operator == "zoom":
            task += f"\nThe new entities are at scale {place['scale']}."
        scale = place["scale"]
        need = _min_concrete(scale, cfg)
        concrete_rule = (
            f"At least {need} of them must be of kind "
            f"{'/'.join(CONCRETE_KINDS)}." if need else
            "Prefer facts of kind " + "/".join(CONCRETE_KINDS) + ".")
        return self.prompts["common"]["user"].format(
            language=(graph.get("meta") or {}).get("language", ""),
            task=task, statements=_lines(statements), axes=_lines(axis_lines),
            context=json.dumps(ctx, ensure_ascii=False, separators=(",", ":")),
            n=n, types=", ".join(ENTITY_TYPES), kinds=", ".join(FACT_KINDS),
            relation_types=", ".join(RELATION_TYPES),
            min_facts=cfg.min_facts, concrete_rule=concrete_rule,
        )

    # -- candidates
    def _build(self, operator, graph, target, place, n, response, brief, axes):
        raw = response.get("candidates") if isinstance(response, Mapping) else None
        if isinstance(raw, Mapping):
            raw = [raw]
        if not isinstance(raw, list):
            return []
        entities = graph.get("entities", [])
        existing_ids = {e["id"] for e in entities}
        existing_names = {str(e.get("name", "")).strip().lower() for e in entities}
        statement_ids = None if brief is None else {
            s.get("id") for s in brief.get("statements", []) or []
            if isinstance(s, Mapping)}
        axis_ids = None if axes is None else {a.get("id") for a in axes}

        from .graph import next_entity_id
        next_n = int(next_entity_id(graph)[1:])
        out: List[Dict[str, Any]] = []
        for item in raw:
            if len(out) >= n:
                break
            if not isinstance(item, Mapping):
                continue
            entity = self._entity(
                operator, graph, target, place, item, f"e{next_n}",
                existing_ids, statement_ids, axis_ids)
            if entity is None:
                continue
            name = entity["name"].strip().lower()
            if name in existing_names:
                continue
            candidate = {
                "operator": operator,
                "target": target["id"] if target else None,
                "entity": entity,
            }
            if validate_candidate(graph, candidate, axes, brief):
                continue
            existing_names.add(name)
            next_n += 1
            out.append(candidate)
        return out

    def _entity(
        self, operator, graph, target, place, item, new_id,
        existing_ids, statement_ids, axis_ids,
    ) -> Optional[Dict[str, Any]]:
        cfg = self.config
        etype = text_of(item.get("type")).lower().replace(" ", "_")
        if operator == "document":
            etype = "document"
        if etype not in ENTITY_TYPES:
            return None
        name = text_of(item.get("name"))
        summary = text_of(item.get("summary"))
        if not name or not summary:
            return None

        sids = [s for s in id_list(item.get("statement_ids"))
                if statement_ids is None or s in statement_ids]
        srcs = [s for s in id_list(item.get("derived_from"))
                if s in existing_ids]
        reason = text_of(item.get("reason"))
        if not sids and not srcs:
            return None  # no provenance: discard
        if srcs and not reason:
            if not sids:
                return None
            srcs = []  # statements still ground it; drop the unexplained link
        provenance = {"statement_ids": sids, "derived_from": srcs,
                      "reason": reason}

        facts = [{"kind": f["kind"], "text": f["text"],
                  "provenance": copy.deepcopy(provenance)}
                 for f in fact_items(item.get("facts"), FACT_KINDS)]
        scale = place["scale"]
        concrete = sum(1 for f in facts if f["kind"] in CONCRETE_KINDS)
        if len(facts) < cfg.min_facts or concrete < _min_concrete(scale, cfg):
            return None

        axes_ = [a for a in id_list(item.get("axes"))
                 if axis_ids is None or a in axis_ids]
        if not axes_ and target is not None:
            axes_ = [a for a in target.get("axes", [])
                     if axis_ids is None or a in axis_ids]

        relations: List[Dict[str, str]] = []
        for rel in relation_items(item.get("relations"), RELATION_TYPES):
            if rel["target"] in existing_ids and rel not in relations:
                relations.append(rel)
        if target is not None and operator in _TARGET_RELATION:
            rel = {"type": _TARGET_RELATION[operator], "target": target["id"]}
            if rel not in relations:
                relations.append(rel)

        entity = make_entity(
            new_id, etype, name, scale, axes=axes_,
            parent=place["parent"], relations=relations,
            summary=summary, facts=facts, provenance=provenance)
        # Keep the operation that created an entity as provenance for the
        # exploration policy. It is outside the canonical entity schema so
        # older graphs without it remain readable.
        entity["origin_operator"] = operator
        return entity


# ---------------------------------------------------------- public wrappers

def _runner(backend, config, prompts) -> OperatorRunner:
    return OperatorRunner(backend, config, prompts)


def premise(backend, graph, n=3, *, brief=None, axes=None,
            config=None, prompts=None):
    return _runner(backend, config, prompts).run(
        "premise", graph, None, n, brief=brief, axes=axes)


def _targeted(name):
    def op(backend, graph, target, n=3, *, brief=None, axes=None,
           config=None, prompts=None):
        return _runner(backend, config, prompts).run(
            name, graph, target, n, brief=brief, axes=axes)
    op.__name__ = name
    op.__doc__ = f"Run the ``{name}`` operator on entity ``target``."
    return op


expand = _targeted("expand")
zoom = _targeted("zoom")
cause = _targeted("cause")
perspective = _targeted("perspective")
history = _targeted("history")
document = _targeted("document")


def run_operator(
    operator: str, backend, graph, target=None, n=3, *,
    brief=None, axes=None, config=None, prompts=None,
):
    """Dispatch by operator name."""
    return _runner(backend, config, prompts).run(
        operator, graph, target, n, brief=brief, axes=axes)


__all__ = [
    "CONCRETE_KINDS", "DEFAULT_MIN_CONCRETE_FACTS", "OPERATORS",
    "OperatorConfig", "OperatorError", "OperatorRunner", "cause", "document",
    "expand", "history", "load_prompts", "load_revision_prompts", "perspective", "placement",
    "premise", "run_operator", "validate_candidate", "zoom",
]
