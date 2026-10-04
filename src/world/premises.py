"""Small, explicit world contracts and traceable extensions.

No real calendar, device or unit is privileged. The first accepted contract
is authoritative; reviewed additions are recorded on accepted entities.
Older graphs without a contract remain readable.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Mapping, Optional

from .quantities import registered_unit

MAX_ITEMS = 16
MAX_TEXT = 160
CONTRACT_ID = "world_contract"


def contract_checks_enabled(graph: Mapping[str, Any]) -> bool:
    return (graph.get("contract_stage") or {}).get("status") != "failed"


def premise_source(graph: Mapping[str, Any], source_id: str) -> Optional[Mapping[str, Any]]:
    record = graph.get("world_contract")
    if isinstance(record, Mapping) and record.get("id") == source_id:
        return record
    return next((e for e in graph.get("entities", []) if e.get("id") == source_id), None)


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
    if "society" in value:
        society = value["society"]
        if not isinstance(society, Mapping) or not (
                _text(society.get("description"))
                and _terms(society.get("institutions"))):
            errors.append("society needs description and institutions")
    return errors


def normalize_premises(value: Any) -> Optional[Dict[str, Any]]:
    if premise_errors(value):
        return None
    sections = [("calendar", ("name", "origin", "markers")),
                ("technology", ("description", "capabilities", "units"))]
    if "society" in value:
        sections.append(("society", ("description", "institutions")))
    return {section: {key: copy.deepcopy(value[section][key]) for key in keys}
            for section, keys in sections}


def world_premises(graph: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the original contract plus accepted, traceable additions.

    New base contracts live in world_contract; legacy premise entities remain
    readable. Extensions live on contributing entities so transaction rollback
    and checkpoint recovery remove their extensions along with those entities.
    The original calendar and technology limits are never overwritten.
    """
    if not contract_checks_enabled(graph):
        return {}
    entities = graph.get("entities", [])
    record = graph.get("world_contract")
    sources = ([record] if isinstance(record, Mapping) else []) + list(entities)
    for entity in sources:
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


def proposed_extension(entity: Mapping[str, Any], contract: Mapping[str, Any],
                       rules: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Declared additions need a derivation; units alone remain usable."""
    reason = (entity.get("provenance") or {}).get("reason")
    usage = entity.get("premise_usage")
    if not contract.get("source_entity") or not isinstance(reason, str) or not reason.strip():
        return {}
    if usage_errors(usage):
        return {}
    additions = {key: list(dict.fromkeys(
        term for term in usage.get(usage_key, [])
        if (not registered_unit(term, contract, rules or {}) if key == "units"
            else term not in contract["technology"][key])))
        for key, usage_key in (("units", "units"), ("capabilities", "technologies"))}
    if not any(additions.values()):
        return {}
    return {"source_entity": contract["source_entity"], **additions, "reason": reason}


def premise_extensions(graph: Mapping[str, Any]) -> list:
    """Derived export index; entities remain the transactional source of truth."""
    source_id = world_premises(graph).get("source_entity")
    source = premise_source(graph, source_id)
    if source is None:
        return []
    return [{"entity": e["id"], **copy.deepcopy(e["premise_extension"])}
            for e in graph.get("entities", [])
            if "premise_extension" in e and not extension_errors(e["premise_extension"], e, source)]


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
            for key in ("calendars", "technologies", "units", "institutions")
            if not _terms(value.get(key, []))]
