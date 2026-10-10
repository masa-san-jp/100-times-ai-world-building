"""Issue 70's exact term and information checks."""

import json
import re
import unicodedata
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


def duplicate_jaccard():
    path = Path(__file__).resolve().parents[2] / "config/world/criteria.yaml"
    return float(yaml.safe_load(path.read_text(encoding="utf-8"))["new_information"]["duplicate_jaccard"])


def _trigrams(text):
    return {text[i:i + 3] for i in range(max(len(text) - 2, 1))}


def nearly_same(text, other, threshold):
    """Equal after normalization, or character 3-gram Jaccard at or above threshold."""
    key, other_key = normalize_term(text), normalize_term(other)
    if key == other_key:
        return True
    grams, other_grams = _trigrams(key), _trigrams(other_key)
    return len(grams & other_grams) / len(grams | other_grams) >= threshold


def duplicate_fact(text, existing_texts, threshold=None):
    """Return the first existing fact text equal to or nearly equal to text, else None."""
    threshold = duplicate_jaccard() if threshold is None else threshold
    return next((other for other in existing_texts if nearly_same(text, other, threshold)), None)


def restatement_candidates_limit():
    path = Path(__file__).resolve().parents[2] / "config/world/criteria.yaml"
    return int(yaml.safe_load(path.read_text(encoding="utf-8"))["new_information"]["restatement_candidates"])


def restatement_candidates(text, existing_texts, limit=None):
    """Up to limit existing texts by descending 3-gram Jaccard with text; zero overlap excluded."""
    limit = restatement_candidates_limit() if limit is None else limit
    grams = _trigrams(normalize_term(text))
    scored = []
    for index, other in enumerate(existing_texts):
        other_grams = _trigrams(normalize_term(other))
        score = len(grams & other_grams) / len(grams | other_grams)
        if score > 0:
            scored.append((-score, index, other))
    return [other for _, _, other in sorted(scored)[:limit]]


def restatement_check(backend, text, candidates, *, language, max_attempts, max_conversions):
    """Judge whether text restates one of candidates; ids f1..fN are assigned in order."""
    ids = [f"f{i}" for i in range(1, len(candidates) + 1)]
    prompts = yaml.safe_load((Path(__file__).resolve().parents[2] /
        "config/prompts/world/restatement_check.yaml").read_text(encoding="utf-8"))
    return generate_structured(backend, prompts["user"].format(
        language=language, fact=json.dumps(text, ensure_ascii=False),
        candidates="\n".join(f"{i}: {json.dumps(c, ensure_ascii=False)}" for i, c in zip(ids, candidates))),
        step_schema("restatement_check", candidate_ids=ids), task="restatement_check",
        system_prompt=prompts["system"], max_attempts=max_attempts,
        max_conversions=max_conversions, allow_conversion=False)


def measurement_present(value, unit, subject, views, entities):
    """Return True when an existing number fact has the same (value, unit) and a near subject."""
    threshold = duplicate_jaccard()
    return any(f.get("kind") == "number" and all(key in f for key in ("subject", "value", "unit"))
               and f["value"] == value and f["unit"] == unit and nearly_same(subject, f["subject"], threshold)
               for source in [*views, *entities] for f in source.get("facts", []))
