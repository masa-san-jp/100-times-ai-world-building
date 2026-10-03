"""Small, explicit world contracts, stored on their originating premise.

No real calendar, device or unit is privileged. The first accepted contract
is authoritative; reviewed additions are recorded on accepted entities.
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
    """Return the original contract plus accepted, traceable additions.

    Records live on the contributing entities so transaction rollback and
    checkpoint recovery remove their extensions along with those entities.
    The original calendar and technology limits are never overwritten.
    """
    entities = graph.get("entities", [])
    for entity in entities:
        value = entity.get("world_premises")
        if entity.get("scale") == "world" and not premise_errors(value):
            contract = {"source_entity": entity["id"], **normalize_premises(value)}
            for contributor in entities:
                extension = contributor.get("premise_extension")
                if extension is None or extension_errors(extension, contributor, entity):
                    continue
                for key in ("units", "capabilities"):
                    for term in extension[key]:
                        if term not in contract["technology"][key]:
                            contract["technology"][key].append(term)
            return contract
    return {}


def proposed_extension(entity: Mapping[str, Any], contract: Mapping[str, Any]) -> Dict[str, Any]:
    """Declared additions need a derivation; units alone remain usable."""
    reason = (entity.get("provenance") or {}).get("reason")
    usage = entity.get("premise_usage")
    if not contract.get("source_entity") or not isinstance(reason, str) or not reason.strip():
        return {}
    if usage_errors(usage):
        return {}
    additions = {key: list(dict.fromkeys(
        term for term in usage.get(usage_key, [])
        if term not in contract["technology"][key]))
        for key, usage_key in (("units", "units"), ("capabilities", "technologies"))}
    if not any(additions.values()):
        return {}
    return {"source_entity": contract["source_entity"], **additions, "reason": reason}


def extension_errors(value: Any, entity: Mapping[str, Any], source: Mapping[str, Any]) -> list:
    """Validate the history's origin and its connection to declared usage."""
    if not isinstance(value, Mapping):
        return ["premise_extension must be an object"]
    errors = []
    if (value.get("source_entity") != source.get("id")
            or source.get("scale") != "world"
            or premise_errors(source.get("world_premises"))):
        errors.append("premise_extension needs an existing world premise source")
    reason = value.get("reason")
    if (not isinstance(reason, str) or not reason.strip()
            or reason != (entity.get("provenance") or {}).get("reason")):
        errors.append("premise_extension needs the candidate's derivation reason")
    usage = entity.get("premise_usage") or {}
    if usage_errors(usage):
        return errors + ["premise_extension needs valid declared usage"]
    for key, usage_key in (("units", "units"), ("capabilities", "technologies")):
        terms = value.get(key)
        if not _terms(terms) or not isinstance(usage, Mapping) or any(
                term not in usage.get(usage_key, []) for term in (terms or [])):
            errors.append(f"premise_extension.{key} must contain declared terms")
    if not value.get("units") and not value.get("capabilities"):
        errors.append("premise_extension must add a unit or capability")
    return errors


def usage_errors(value: Any) -> list:
    if not isinstance(value, Mapping):
        return ["premise_usage must be an object"]
    return [f"premise_usage.{key} must be a bounded list of terms"
            for key in ("calendars", "technologies", "units")
            if not _terms(value.get(key, []))]
