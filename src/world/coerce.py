"""Defensive coercion of model output.

A model may return an id list as strings, objects (``{"id": ...}``),
nested lists, numbers or one comma-separated string.  These helpers recover
what can be recovered and drop the rest; they never raise on model data.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

ID_KEYS = ("id", "target", "entity_id", "entity", "statement_id", "axis",
           "axis_id", "ref", "name")
TEXT_KEYS = ("text", "value", "fact", "description", "content", "name",
             "statement", "summary")
_SPLIT = re.compile(r"[,;、，\s]+")


def text_of(value: Any, keys: Sequence[str] = TEXT_KEYS) -> str:
    """A stripped string from a string, number or object; else ``""``."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, Mapping):
        for k in keys:
            t = text_of(value.get(k), keys) if k in value else ""
            if t:
                return t
    return ""


def as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return [value]


def id_list(value: Any, keys: Sequence[str] = ID_KEYS) -> List[str]:
    """Flatten ``value`` to unique id strings, in order."""
    out: List[str] = []

    def walk(v: Any, depth: int = 0) -> None:
        if depth > 4 or v is None or isinstance(v, bool):
            return
        if isinstance(v, str):
            out.extend(p for p in _SPLIT.split(v.strip().strip("[]")) if p)
        elif isinstance(v, (int, float)):
            out.append(str(v))
        elif isinstance(v, Mapping):
            for k in keys:
                if k in v:
                    walk(v[k], depth + 1)
                    return
        elif isinstance(v, (list, tuple, set, frozenset)):
            for x in v:
                walk(x, depth + 1)

    walk(value)
    return list(dict.fromkeys(s.strip("'\"") for s in out if s.strip("'\"")))


def fact_items(value: Any, kinds: Sequence[str]) -> List[Dict[str, str]]:
    """``[{"kind", "text"}]`` from strings or objects with varied keys."""
    out: List[Dict[str, str]] = []
    for f in as_list(value):
        if isinstance(f, Mapping):
            text = text_of(f)
            kind = text_of(f.get("kind") or f.get("type") or f.get("category"))
        else:
            text, kind = text_of(f), ""
        if not text:
            continue
        kind = kind.lower().replace(" ", "_").replace("-", "_")
        out.append({"kind": kind if kind in kinds else "other", "text": text})
    return out


def relation_items(value: Any, types: Sequence[str]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for r in as_list(value):
        if not isinstance(r, Mapping):
            continue
        rtype = text_of(r.get("type") or r.get("relation") or r.get("kind"))
        rtype = rtype.lower().replace(" ", "_").replace("-", "_")
        ids = id_list(r.get("target") if "target" in r else
                      r.get("entity_id") if "entity_id" in r else
                      r.get("id") if "id" in r else r.get("to"))
        if rtype in types and ids:
            out.append({"type": rtype, "target": ids[0]})
    return out


def mapping_or_none(value: Any) -> Optional[Mapping[str, Any]]:
    return value if isinstance(value, Mapping) else None


__all__ = ["as_list", "fact_items", "id_list", "mapping_or_none",
           "relation_items", "text_of"]
