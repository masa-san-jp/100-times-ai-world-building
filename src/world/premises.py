"""Small, explicit world contracts and traceable extensions.

No real calendar, device or unit is privileged. The first accepted contract
is authoritative; reviewed additions are recorded on accepted entities.
Older graphs without a contract remain readable.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from jsonschema import Draft202012Validator


MAX_ITEMS = 16
MAX_TEXT = 160
CONTRACT_ID = "world_contract"
_CONTRACT_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "config/schemas/world_contract.json")
    .read_text(encoding="utf-8"))
_UNIT_VALIDATOR = Draft202012Validator(
    _CONTRACT_SCHEMA["properties"]["technology"]["properties"]["units"]["items"])
_INSTITUTION_VALIDATOR = Draft202012Validator(
    _CONTRACT_SCHEMA["properties"]["society"]["properties"]["institutions"]["items"])


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


def _units(value: Any) -> bool:
    # Existing graphs and extension histories can still contain bare terms.
    # Newly generated contracts are checked against world_contract.json.
    return (_terms(value, required=True) or (
        isinstance(value, list) and 0 < len(value) <= MAX_ITEMS
        and all(_UNIT_VALIDATOR.is_valid(unit) for unit in value)))


def unit_symbols(contract: Mapping[str, Any]) -> list[str]:
    """Return notation only; measurement descriptions never register units."""
    return [unit["symbol"] if isinstance(unit, Mapping) else unit
            for unit in (contract.get("technology") or {}).get("units", [])]


def _institutions(value: Any) -> bool:
    # Preserve bare terms in existing graphs, as with legacy unit notation.
    return (_terms(value) or (
        isinstance(value, list) and len(value) <= MAX_ITEMS
        and all(_INSTITUTION_VALIDATOR.is_valid(institution) for institution in value)))


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
            and _units(technology.get("units"))):
        errors.append("technology needs description, capabilities and nonempty units")
    if "society" in value:
        society = value["society"]
        if not isinstance(society, Mapping) or not (
                _text(society.get("description"))
                and _institutions(society.get("institutions"))):
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
                        known = unit_symbols(contract) if key == "units" else contract["technology"][key]
                        if term not in known:
                            contract["technology"][key].append(term)
            return contract
    return {}


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
