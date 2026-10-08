"""Issue 70's exact term and information checks."""

import json
import re
import unicodedata
from decimal import Decimal
from pathlib import Path

import yaml

from .premises import unit_symbols
from .schemas import step_schema
from .structured import generate_structured


def normalize_term(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value))).lower()


def contract_terms(contract):
    calendar = contract.get("calendar") or {}
    society = contract.get("society") or {}
    return list(dict.fromkeys(filter(None, [calendar.get("name"),
        *calendar.get("markers", []), *unit_symbols(contract),
        *(i["name"] if isinstance(i, dict) else i for i in society.get("institutions", [])),
        *(contract.get("technology") or {}).get("capabilities", [])])))


def descriptions(value):
    """Walk descriptions, excluding generated bookkeeping ids."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            if key != "id":
                yield from descriptions(child)
    elif isinstance(value, list):
        for child in value:
            yield from descriptions(child)


def new_name(name, raw_input, brief, views, entities, contract):
    key = normalize_term(name)
    sources = [raw_input, *descriptions(brief),
        *(e.get("name", "") for e in views),
        *(f.get("text", "") for e in views for f in e.get("facts", [])),
        *(e.get("name", "") for e in entities), *contract_terms(contract)]
    return bool(key) and not any(key in normalize_term(source) for source in sources)


def real_world_check(backend, terms, *, language, max_attempts, max_conversions):
    terms = list(dict.fromkeys(terms))
    prompts = yaml.safe_load((Path(__file__).resolve().parents[2] /
        "config/prompts/world/real_world_check.yaml").read_text(encoding="utf-8"))
    return generate_structured(backend, prompts["user"].format(
        language=language, terms=json.dumps(terms, ensure_ascii=False)),
        step_schema("real_world_check", terms=terms), task="real_world_check",
        system_prompt=prompts["system"], max_attempts=max_attempts,
        max_conversions=max_conversions, allow_conversion=False)


def outside_terms(data, raw_input):
    raw = normalize_term(raw_input)
    return [item for item in data["items"]
            if item["category"] in {"real_calendar", "real_unit", "real_person_name",
                                    "real_place_name", "real_organization_name"}
            and normalize_term(item["term"]) not in raw]


def measurement_present(value, unit, brief, views, entities):
    """Match structured pairs or complete numeric tokens in existing text."""
    from .quantities import NUMBER, normalized
    for source in [brief, *views, *entities]:
        if isinstance(source, dict):
            for fact in source.get("facts", []):
                if fact.get("value") == value and fact.get("unit") == unit:
                    return True
        texts = descriptions(source) if source is brief else (
            f.get("text", "") for f in source.get("facts", []))
        pattern = r"(?<![A-Za-z\d.])(" + NUMBER + r")\s*" + re.escape(normalized(unit)) + r"(?![A-Za-z0-9_/^*·×])"
        for text in texts:
            if any(Decimal(m[1].replace(",", "")) == Decimal(str(value))
                   for m in re.finditer(pattern, normalized(text))):
                return True
    return False
