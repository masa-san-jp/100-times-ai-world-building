"""Quantity syntax, independent of any privileged measurement system.

The lexicon supplies linguistic time expressions and counter syntax. Unit
notations come from the contract, declarations or symbols next to numbers.
This is a conservative syntax check, not a general dimensional algebra.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping

NUMBER = r"[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?"
LETTERS = r"[A-Za-z\u00b5\u0370-\u03ff]"
SYMBOL = LETTERS + r"+(?:\^?[-+]?\d+)?|[%‰°]"
DENOMINATOR = r"(?:" + LETTERS + r"+|[\u3400-\u9fff]+)(?:\^?[-+]?\d+)?"
TOKEN = re.compile(
    r"(?<![A-Za-z\d])" + NUMBER + r"[ \t]*("
    + SYMBOL + r")((?:[ \t]*/[ \t]*" + DENOMINATOR + r")*)")


def text_fields(entity: Mapping[str, Any]):
    yield "name", str(entity.get("name") or "")
    yield "summary", str(entity.get("summary") or "")
    for index, fact in enumerate(entity.get("facts") or []):
        if isinstance(fact, Mapping):
            yield f"facts[{index}]", str(fact.get("text") or "")


def normalized(value):
    return unicodedata.normalize("NFKC", str(value)).strip()


def units_in_text(text, contract, rules, declared=()):
    text = normalized(text)
    # An absolute calendar date is not a measured quantity.
    calendar = contract.get("calendar") or {}
    markers = [calendar.get("name", ""), *calendar.get("markers", [])]
    for marker in filter(None, markers):
        text = re.sub(re.escape(normalized(marker)) + r"\s*\d+(?:\s*[-–~〜]\s*\d+)?(?:\s*年|\s+years?)?",
                      " ", text, flags=re.IGNORECASE)
    counters = {normalized(u) for u in rules.get("count_units", [])}
    units = set()
    for match in TOKEN.finditer(text):
        unit = match[1] + re.sub(r"\s+", "", match[2])
        if unit not in counters:
            units.add(unit)
    known = {normalized(u) for u in [
        *(contract.get("technology") or {}).get("units", []),
        *rules.get("measure_units", []), *declared]}
    # Longest notation wins, including compound natural-language units.
    if known:
        pattern = r"(?<![\d.])" + NUMBER + r"\s*(" + "|".join(
            re.escape(u) for u in sorted(known, key=len, reverse=True) if u) + r")"
        for match in re.finditer(pattern, text):
            unit = match[1]
            if unit.isascii() and re.match(r"[A-Za-z0-9/^]", text[match.end():]):
                continue  # a prefix of a longer symbol is not another unit
            if unit not in counters:
                units.add(unit)
    return sorted(units)


def observed_units(entity, contract, rules):
    usage = entity.get("premise_usage") or {}
    return sorted({u for _, text in text_fields(entity)
                   for u in units_in_text(text, contract, rules, usage.get("units", []))})


def temporal_conflicts(text, rules):
    """Find an aggregate/rate label incompatible with its own denominator.

    Patterns have named groups: period is the asserted basis and denominator
    the basis after '/' or 'per'. Equivalence is language data (time words),
    never a list of technical units. Only one quantity in a short clause is
    matched; explicit observation windows use separate syntax.
    """
    text = normalized(text)
    aliases = rules.get("time_basis_aliases") or {}
    for pattern in rules.get("quantity_basis_patterns", []):
        for match in re.finditer(pattern, text, re.IGNORECASE):
            period, denominator = match["period"].lower(), match["denominator"].lower()
            if period in aliases and denominator in aliases and aliases[period] != aliases[denominator]:
                yield {"expression": match[0], "period": period, "denominator": denominator}
