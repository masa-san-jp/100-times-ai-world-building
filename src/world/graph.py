"""Entity graph: the world as a deep, scale-layered, provenance-tracked graph.

The graph is plain data (``dict``) so it round-trips through JSON and the
checkpoint mechanism unchanged.  This module defines the shape, validation
(schema and referential integrity), a deterministic persisted form
(``world/graph.json``), transactional updates, and a size-capped local
context extractor that operators feed to small local models.

Entities describe the world only: persons are inhabitants without a story
role, and no field holds plot or narrative prose.
"""

from __future__ import annotations

import copy
import json
import re
from .premises import CONTRACT_ID, extension_errors, premise_errors, premise_source, usage_errors, world_premises
from contextlib import contextmanager
from pathlib import Path
from typing import (
    Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Union,
)

SCHEMA_VERSION = 1

ENTITY_TYPES = (
    "place", "group", "institution", "person", "object", "practice",
    "event", "concept", "document",
)
SCALES = ("world", "region", "settlement", "district", "site", "detail")
SCALE_RANK = {name: i for i, name in enumerate(SCALES)}
RELATION_TYPES = (
    "located_in", "member_of", "causes", "affects", "opposes",
    "derived_from", "part_of", "uses", "produces", "governs", "related_to",
)
FACT_KINDS = (
    "proper_noun", "number", "period", "procedure", "object", "expression",
    "other",
)

GRAPH_RELATIVE_PATH = Path("world") / "graph.json"
CHECKPOINT_PHASE = "world_graph"

# Hard bounds for local contexts (independent of total graph size).
DEFAULT_LIMITS: Dict[str, int] = {
    "max_siblings": 6,
    "max_related": 10,
    "max_facts": 4,
    "max_summary_chars": 240,
    "max_fact_chars": 120,
    "max_name_chars": 60,
}


class GraphError(ValueError):
    """Raised when a graph (or a transaction's result) is invalid."""

    def __init__(self, errors: Iterable[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors) or "invalid graph")


# ---------------------------------------------------------------- language

def guess_language(text: str) -> str:
    """Deterministically guess a language code from raw input text.

    A coarse script-based heuristic: it only needs to keep generated
    material in the language of the input.  Callers may override it.
    """
    counts = {"ja": 0, "ko": 0, "zh": 0, "ru": 0, "ar": 0, "en": 0}
    for ch in text or "":
        o = ord(ch)
        if 0x3040 <= o <= 0x30FF:
            counts["ja"] += 1
        elif 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF:
            counts["ko"] += 1
        elif 0x4E00 <= o <= 0x9FFF:
            counts["zh"] += 1
        elif 0x0400 <= o <= 0x04FF:
            counts["ru"] += 1
        elif 0x0600 <= o <= 0x06FF:
            counts["ar"] += 1
        elif ch.isascii() and ch.isalpha():
            counts["en"] += 1
    if counts["ja"]:  # kana never appears in Chinese text
        return "ja"
    best = max(counts, key=lambda k: (counts[k], k))
    return best if counts[best] else "und"


# ------------------------------------------------------------- constructors

def new_graph(language: str) -> Dict[str, Any]:
    if not isinstance(language, str) or not language.strip():
        raise ValueError("language is required")
    return {
        "meta": {"schema_version": SCHEMA_VERSION, "language": language},
        "entities": [],
    }


def empty_provenance() -> Dict[str, Any]:
    return {"statement_ids": [], "derived_from": [], "reason": ""}


def make_entity(
    entity_id: str, type: str, name: str, scale: str, *,
    axes: Optional[Sequence[str]] = None,
    parent: Optional[str] = None,
    relations: Optional[Sequence[Mapping[str, str]]] = None,
    summary: str = "",
    facts: Optional[Sequence[Mapping[str, Any]]] = None,
    provenance: Optional[Mapping[str, Any]] = None,
    scores: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build an entity dict in canonical shape."""
    return {
        "id": entity_id,
        "type": type,
        "name": name,
        "axes": list(axes or []),
        "scale": scale,
        "parent": parent,
        "relations": [dict(r) for r in relations or []],
        "summary": summary,
        "facts": [dict(f) for f in facts or []],
        "provenance": dict(provenance or empty_provenance()),
        "scores": dict(scores or {}),
    }


def next_entity_id(graph: Mapping[str, Any]) -> str:
    """Return the next free ``eN`` id."""
    used = {
        int(m.group(1)) for e in graph.get("entities", [])
        if isinstance(e, Mapping)
        for m in [re.fullmatch(r"e(\d+)", str(e.get("id", "")))] if m
    }
    return f"e{max(used, default=0) + 1}"


def get_entity(graph: Mapping[str, Any], entity_id: str) -> Optional[Dict[str, Any]]:
    for e in graph.get("entities", []):
        if e.get("id") == entity_id:
            return e
    return None


# --------------------------------------------------------------- validation

def _str_list(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(v, str) and v for v in value
    )


def _provenance_errors(
    prov: Any, where: str, statement_ids: Optional[set],
    entity_ids: set, required: bool,
) -> List[str]:
    if not isinstance(prov, Mapping):
        return [f"{where}: provenance must be an object"]
    errors: List[str] = []
    sids, srcs = prov.get("statement_ids"), prov.get("derived_from")
    if not _str_list(sids):
        errors.append(f"{where}: provenance.statement_ids must be a list of ids")
        sids = []
    if not _str_list(srcs):
        errors.append(f"{where}: provenance.derived_from must be a list of ids")
        srcs = []
    reason = prov.get("reason")
    if not isinstance(reason, str):
        errors.append(f"{where}: provenance.reason must be a string")
        reason = ""
    if statement_ids is not None:
        for s in sids:
            if s not in statement_ids:
                errors.append(f"{where}: unknown statement id {s}")
    for s in srcs:
        if s not in entity_ids:
            errors.append(f"{where}: unknown source entity id {s}")
    if srcs and not reason.strip():
        errors.append(f"{where}: derived_from requires a reason")
    if required and not sids and not srcs:
        errors.append(f"{where}: provenance needs statement_ids or derived_from")
    return errors


def validate_graph(
    graph: Any,
    axes: Optional[Iterable[Mapping[str, Any]]] = None,
    brief: Optional[Mapping[str, Any]] = None,
) -> List[str]:
    """Return schema and referential-integrity violations (empty if valid).

    ``axes`` (list of axis dicts) and ``brief`` enable checks that axis ids
    and statement ids exist; omit them to check the graph alone.
    """
    if not isinstance(graph, Mapping):
        return ["graph must be an object"]
    errors: List[str] = []
    meta = graph.get("meta")
    if not isinstance(meta, Mapping):
        errors.append("meta must be an object")
    else:
        if meta.get("schema_version") != SCHEMA_VERSION:
            errors.append(f"meta.schema_version must be {SCHEMA_VERSION}")
        lang = meta.get("language")
        if not isinstance(lang, str) or not lang.strip():
            errors.append("meta.language must be a non-empty string")
    entities = graph.get("entities")
    if not isinstance(entities, list):
        return errors + ["entities must be a list"]

    axis_ids = None if axes is None else {a.get("id") for a in axes}
    statement_ids = None
    if brief is not None:
        statement_ids = {
            s.get("id") for s in brief.get("statements", []) or []
            if isinstance(s, Mapping)
        }

    ids: List[str] = []
    for e in entities:
        if isinstance(e, Mapping) and isinstance(e.get("id"), str) and e["id"]:
            ids.append(e["id"])
    seen = set()
    for i in ids:
        if i in seen:
            errors.append(f"duplicate entity id: {i}")
        seen.add(i)
    id_set = set(ids)
    by_id = {e["id"]: e for e in entities
             if isinstance(e, Mapping) and e.get("id") in id_set}
    contracts = [e["world_premises"] for e in entities
                 if isinstance(e, Mapping) and "world_premises" in e]
    record = graph.get("world_contract")
    if record is not None:
        if not isinstance(record, Mapping):
            errors.append("world_contract must be an object")
        else:
            if record.get("id") != CONTRACT_ID or record.get("scale") != "world" or CONTRACT_ID in id_set:
                errors.append("world_contract needs a reserved id and world scale")
            errors.extend(f"world_contract: {err}" for err in premise_errors(record.get("world_premises")))
            errors.extend(_provenance_errors(record.get("provenance"), "world_contract", statement_ids, id_set, True))
            contracts.insert(0, record.get("world_premises"))
    if contracts and any(c != contracts[0] for c in contracts[1:]):
        errors.append("world_premises: conflicting world contracts")

    for n, e in enumerate(entities):
        if not isinstance(e, Mapping):
            errors.append(f"entities[{n}] must be an object")
            continue
        eid = e.get("id")
        if not isinstance(eid, str) or not eid:
            errors.append(f"entities[{n}]: id is required")
            continue
        w = f"entity {eid}"
        if "world_premises" in e:
            if e.get("scale") != "world" or e.get("origin_operator") != "premise":
                errors.append(f"{w}: world_premises requires a world-scale premise")
            errors.extend(f"{w}: {err}" for err in premise_errors(e["world_premises"]))
        if "premise_extension" in e:
            extension = e["premise_extension"]
            source_id = extension.get("source_entity") if isinstance(extension, Mapping) else None
            source = (premise_source(graph, source_id) or {}) if isinstance(source_id, str) else {}
            errors.extend(f"{w}: {err}" for err in extension_errors(extension, e, source))
        if "premise_usage" in e:
            errors.extend(f"{w}: {err}" for err in usage_errors(e["premise_usage"]))
        if e.get("type") not in ENTITY_TYPES:
            errors.append(f"{w}: invalid type {e.get('type')!r}")
        if not isinstance(e.get("name"), str) or not e["name"].strip():
            errors.append(f"{w}: name is required")
        if not isinstance(e.get("summary"), str):
            errors.append(f"{w}: summary must be a string")
        scale = e.get("scale")
        if scale not in SCALE_RANK:
            errors.append(f"{w}: invalid scale {scale!r}")
        if not _str_list(e.get("axes")):
            errors.append(f"{w}: axes must be a list of axis ids")
        elif axis_ids is not None:
            for a in e["axes"]:
                if a not in axis_ids:
                    errors.append(f"{w}: unknown axis id {a}")
        parent = e.get("parent")
        if parent is None:
            if scale not in (None, "world") and scale in SCALE_RANK:
                errors.append(f"{w}: only scale 'world' may omit parent")
        elif not isinstance(parent, str) or parent not in id_set:
            errors.append(f"{w}: parent {parent!r} does not exist")
        elif parent == eid:
            errors.append(f"{w}: parent is itself")
        else:
            ps = by_id[parent].get("scale")
            if scale in SCALE_RANK and ps in SCALE_RANK \
                    and SCALE_RANK[ps] >= SCALE_RANK[scale]:
                errors.append(
                    f"{w}: parent scale {ps} must be above child scale {scale}"
                )
        rels = e.get("relations")
        if not isinstance(rels, list):
            errors.append(f"{w}: relations must be a list")
            rels = []
        for r in rels:
            if not isinstance(r, Mapping):
                errors.append(f"{w}: relation must be an object")
                continue
            if r.get("type") not in RELATION_TYPES:
                errors.append(f"{w}: invalid relation type {r.get('type')!r}")
            if r.get("target") not in id_set:
                errors.append(f"{w}: relation target {r.get('target')!r} does not exist")
        facts = e.get("facts")
        if not isinstance(facts, list):
            errors.append(f"{w}: facts must be a list")
            facts = []
        for k, f in enumerate(facts):
            fw = f"{w} fact[{k}]"
            if not isinstance(f, Mapping):
                errors.append(f"{fw}: must be an object")
                continue
            if not isinstance(f.get("text"), str) or not f["text"].strip():
                errors.append(f"{fw}: text is required")
            if f.get("kind") not in FACT_KINDS:
                errors.append(f"{fw}: invalid kind {f.get('kind')!r}")
            errors.extend(_provenance_errors(
                f.get("provenance"), fw, statement_ids, id_set, False))
        errors.extend(_provenance_errors(
            e.get("provenance"), w, statement_ids, id_set, True))
        if not isinstance(e.get("scores"), Mapping):
            errors.append(f"{w}: scores must be an object")
    return errors


def assert_valid_graph(graph: Any, axes=None, brief=None) -> None:
    errors = validate_graph(graph, axes, brief)
    if errors:
        raise GraphError(errors)


# ----------------------------------------------------------- serialization

def canonical(graph: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a copy with stable ordering (entities by id, sets sorted)."""
    g = copy.deepcopy(dict(graph))
    ents = [e for e in g.get("entities", []) if isinstance(e, dict)]
    for e in ents:
        if isinstance(e.get("axes"), list):
            e["axes"] = sorted(set(e["axes"]))
        if isinstance(e.get("relations"), list):
            e["relations"] = sorted(
                e["relations"],
                key=lambda r: (str(r.get("type")), str(r.get("target"))),
            )
    g["entities"] = sorted(ents, key=lambda e: str(e.get("id")))
    return g


def dumps(graph: Mapping[str, Any]) -> str:
    return json.dumps(
        canonical(graph), ensure_ascii=False, indent=2, sort_keys=True,
    ) + "\n"


# ------------------------------------------------------------------- store

class GraphStore:
    """Persist a graph as ``<package>/world/graph.json``.

    Writes are atomic (temp file + rename).  When a ``CheckpointManager`` is
    given, every commit is also recorded as a ``world_graph`` checkpoint so a
    run can resume even if ``graph.json`` is lost or unreadable.
    """

    def __init__(
        self, package_dir: Union[str, Path], checkpoints: Any = None,
        axes: Optional[Iterable[Mapping[str, Any]]] = None,
        brief: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.path = Path(package_dir) / GRAPH_RELATIVE_PATH
        self.checkpoints = checkpoints
        self.axes = list(axes) if axes is not None else None
        self.brief = brief

    def exists(self) -> bool:
        return self.path.exists()

    def save(self, graph: Mapping[str, Any]) -> Path:
        assert_valid_graph(graph, self.axes, self.brief)
        from ..checkpoint_manager import CheckpointManager

        payload = dumps(graph).encode("utf-8")
        CheckpointManager._atomic_write(self.path, payload)
        if self.checkpoints is not None:
            self.checkpoints.save_checkpoint(CHECKPOINT_PHASE, canonical(graph))
        return self.path

    def load(self) -> Dict[str, Any]:
        """Load and validate ``graph.json``; fall back to the checkpoint."""
        try:
            graph = json.loads(self.path.read_text(encoding="utf-8"))
            assert_valid_graph(graph, self.axes, self.brief)
            return graph
        except (OSError, ValueError, GraphError) as exc:
            if self.checkpoints is None:
                raise
            graph = self.checkpoints.load_checkpoint(CHECKPOINT_PHASE)
            if graph is None:
                raise
            assert_valid_graph(graph, self.axes, self.brief)
            return graph

    def load_or_create(self, language: str) -> Dict[str, Any]:
        """Resume an existing graph, or start an empty one."""
        try:
            return self.load()
        except (OSError, ValueError, GraphError):
            return new_graph(language)

    @contextmanager
    def transaction(self, language: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        """Edit a working copy; commit only if it validates, else roll back."""
        working = copy.deepcopy(
            self.load_or_create(language) if language else self.load()
        )
        yield working
        self.save(working)  # raises GraphError before touching disk


# ----------------------------------------------------------- local context

def _clip(text: Any, limit: int) -> str:
    text = text if isinstance(text, str) else ""
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _brief_view(e: Mapping[str, Any], lim: Mapping[str, int]) -> Dict[str, Any]:
    facts = [
        {"kind": f.get("kind"), "text": _clip(f.get("text"), lim["max_fact_chars"])}
        for f in (e.get("facts") or [])[: lim["max_facts"]]
    ]
    return {
        "id": e.get("id"),
        "type": e.get("type"),
        "name": _clip(e.get("name"), lim["max_name_chars"]),
        "scale": e.get("scale"),
        "summary": _clip(e.get("summary"), lim["max_summary_chars"]),
        "facts": facts,
    }


def local_context(
    graph: Mapping[str, Any], entity_id: str,
    limits: Optional[Mapping[str, int]] = None,
) -> Dict[str, Any]:
    """Return the entity, its parent, siblings and related entities.

    Item counts and text lengths are capped by ``limits`` so the result's
    size is bounded regardless of how large the graph is.  Truncation is
    reported via ``omitted`` counts.  Ordering is deterministic.
    """
    lim = {**DEFAULT_LIMITS, **(limits or {})}
    entities = {e["id"]: e for e in graph.get("entities", [])}
    focus = entities.get(entity_id)
    if focus is None:
        raise KeyError(f"unknown entity id: {entity_id}")

    parent_id = focus.get("parent")
    parent = entities.get(parent_id) if parent_id else None
    siblings = sorted(
        e["id"] for e in entities.values()
        if parent_id and e.get("parent") == parent_id and e["id"] != entity_id
    )
    related_ids = {r["target"] for r in focus.get("relations", [])}
    related_ids.update(
        e["id"] for e in entities.values()
        if any(r.get("target") == entity_id for r in e.get("relations", []))
    )
    skip = {entity_id, parent_id, *siblings}
    related = sorted(i for i in related_ids if i in entities and i not in skip)

    chosen_sib = siblings[: lim["max_siblings"]]
    chosen_rel = related[: lim["max_related"]]
    return {
        "language": (graph.get("meta") or {}).get("language"),
        "world_premises": world_premises(graph),
        "entity": {
            **_brief_view(focus, lim),
            "axes": list(focus.get("axes", [])),
            "relations": [
                {"type": r.get("type"), "target": r.get("target")}
                for r in focus.get("relations", [])[: lim["max_related"]]
            ],
        },
        "parent": _brief_view(parent, lim) if parent else None,
        "siblings": [_brief_view(entities[i], lim) for i in chosen_sib],
        "related": [_brief_view(entities[i], lim) for i in chosen_rel],
        "omitted": {
            "siblings": len(siblings) - len(chosen_sib),
            "related": len(related) - len(chosen_rel),
        },
    }


__all__ = [
    "CHECKPOINT_PHASE", "DEFAULT_LIMITS", "ENTITY_TYPES", "FACT_KINDS",
    "GRAPH_RELATIVE_PATH", "GraphError", "GraphStore", "RELATION_TYPES",
    "SCALES", "SCALE_RANK", "SCHEMA_VERSION", "assert_valid_graph",
    "canonical", "dumps", "empty_provenance", "get_entity", "guess_language",
    "local_context", "make_entity", "new_graph", "next_entity_id",
    "validate_graph",
]
