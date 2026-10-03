"""Small, explicit world contracts, stored on their originating premise.

No real calendar, device or unit is privileged. The first accepted contract
is authoritative; later candidates cannot expand their own allow lists.
Older graphs without a contract remain readable.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Mapping, Optional

MAX_ITEMS = 16
MAX_TEXT = 160


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= MAX_TEXT


def _terms(value: Any, required: bool = False) -> bool:
    return (isinstance(value, list) and len(value) <= MAX_ITEMS
            and (bool(value) or not required) and all(_text(v) for v in value))


def premise_errors(value: Any) -> list:
    if not isinstance(value, Mapping):
        return ["world_premises must be an object"]
    calendar, technology = value.get("calendar"), value.get("technology")
    errors = []
    if not isinstance(calendar, Mapping) or not (
            _text(calendar.get("name")) and _text(calendar.get("origin"))
            and _terms(calendar.get("markers"), required=True)):
        errors.append("calendar needs name, origin and nonempty markers")
    if not isinstance(technology, Mapping) or not (
            _text(technology.get("description"))
            and _terms(technology.get("capabilities"))
            and _terms(technology.get("units"), required=True)):
        errors.append("technology needs description, capabilities and nonempty units")
    return errors


def normalize_premises(value: Any) -> Optional[Dict[str, Any]]:
    if premise_errors(value):
        return None
    return {section: {key: copy.deepcopy(value[section][key]) for key in keys}
            for section, keys in (
                ("calendar", ("name", "origin", "markers")),
                ("technology", ("description", "capabilities", "units")))}


def world_premises(graph: Mapping[str, Any]) -> Dict[str, Any]:
    for entity in graph.get("entities", []):
        value = entity.get("world_premises")
        if entity.get("scale") == "world" and not premise_errors(value):
            return {"source_entity": entity["id"], **normalize_premises(value)}
    return {}


def usage_errors(value: Any) -> list:
    if not isinstance(value, Mapping):
        return ["premise_usage must be an object"]
    return [f"premise_usage.{key} must be a bounded list of terms"
            for key in ("calendars", "technologies", "units")
            if not _terms(value.get(key, []))]
