"""Quantity syntax, independent of any privileged measurement system.

The lexicon supplies linguistic time expressions and counter syntax. Unit
notations come from the contract, declarations or symbols next to numbers.
The algebra describes registered notation, not physical dimensions or
measurement capabilities; those still require semantic review.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping

NUMBER = r"[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?"
LETTERS = r"[A-Za-z\u00b5\u0370-\u03ff]"
SYMBOL = LETTERS + r"+(?:\^?[-+]?\d+)?|[%‰°]"
DENOMINATOR = r"(?:" + LETTERS + r"+|[\u3400-\u9fff]+)(?:\^?[-+]?\d+)?"
# Bounded nesting for prose extraction; the parser below checks the complete
# expression. The first token must be a symbol or parentheses, so ordinary
# Japanese words following a number are not invented measurement units.
_FACTOR = r"(?:" + DENOMINATOR + r"|[%‰°])"
for _ in range(3):
    _GROUP = r"\(" + _FACTOR + r"(?:\s*[/*·×]\s*" + _FACTOR + r")*\)(?:\^[-+]?\d+)?"
    _FACTOR = r"(?:" + DENOMINATOR + r"|[%‰°]|" + _GROUP + r")"
_EXPRESSION = r"(?:" + SYMBOL + r"|" + _GROUP + r")(?:\s*[/*·×]\s*" + _FACTOR + r")*"
TOKEN = re.compile(r"(?<![A-Za-z\d])" + NUMBER + r"[ \t]*(" + _EXPRESSION + r")")


def unit_notation(value):
    """Normalize typography, never infer a named measurement system."""
    value = normalized(value)
    value = re.sub(r"\s+", "", value).replace("**", "^")
    value = value.replace("·", "*").replace("×", "*").replace("−", "-")
    # NFKC changes superscripts to ordinary digits; trailing powers are a
    # general symbolic convention, including invented symbols.
    return re.sub(r"([^\W\d_]+)([-+]?\d+)", r"\1^\2", value)


def unit_factors(value):
    """Parse products, quotients, parentheses and integer powers safely."""
    value = unit_notation(value)
    tokens = re.findall(r"[^\W\d_]+|[%‰°]|[-+]?\d+|[*/^()]", value)
    if "".join(tokens) != value or not tokens:
        return None
    position = 0

    def expression():
        nonlocal position
        result = factor()
        while position < len(tokens) and tokens[position] in ("*", "/"):
            operator = tokens[position]
            position += 1
            for name, exponent in factor().items():
                result[name] = result.get(name, 0) + exponent * (1 if operator == "*" else -1)
        return {name: exponent for name, exponent in result.items() if exponent}

    def factor():
        nonlocal position
        if position >= len(tokens):
            raise ValueError
        token = tokens[position]
        position += 1
        if token == "(":
            result = expression()
            if position >= len(tokens) or tokens[position] != ")":
                raise ValueError
            position += 1
        elif re.fullmatch(r"[^\W\d_]+|[%‰°]", token):
            result = {token: 1}
        else:
            raise ValueError
        if position < len(tokens) and tokens[position] == "^":
            position += 1
            if position >= len(tokens) or not re.fullmatch(r"[-+]?\d+", tokens[position]):
                raise ValueError
            power = int(tokens[position])
            position += 1
            result = {name: exponent * power for name, exponent in result.items()}
        return result

    try:
        result = expression()
        return result if position == len(tokens) else None
    except (ValueError, RecursionError):
        return None


def is_counter(unit, rules):
    return normalized(unit).casefold() in {normalized(v).casefold() for v in rules.get("count_units", [])}


def registered_unit(unit, contract, rules):
    """Units constructible from registered units and linguistic time words.

    Integer powers of a registered atomic unit are available; a new scale
    or spelling with no typographic derivation still needs semantic review.
    Counters are explicitly outside the measurement contract.
    """
    if is_counter(unit, rules):
        return True
    calendar = contract.get("calendar") or {}
    known = [*(contract.get("technology") or {}).get("units", []),
             *(rules.get("time_basis_aliases") or {}),
             calendar.get("name", ""), *calendar.get("markers", [])]
    key = unit_notation(unit)
    if key in {unit_notation(v) for v in known if v}:
        return True
    factors = unit_factors(unit)
    if factors is None:
        return False
    vectors = [parsed for v in known if (parsed := unit_factors(v))]
    # Even a cancelling expression must be built from known atom names.
    atoms = set(re.findall(r"[^\W\d_]+|[%‰°]", key))
    if not atoms <= {name for vector in vectors for name in vector}:
        return False
    return _integer_combination(factors, vectors)


def _integer_combination(target, vectors):
    """Exact integer lattice membership; no measurement-system assumptions.

    Euclidean column reduction keeps the same integer span. Success means
    the expression uses products/quotients/integer powers of known units,
    including registered compound units. Fractional roots need review.
    """
    names = sorted({*target, *(name for vector in vectors for name in vector)})
    columns = [[vector.get(name, 0) for name in names] for vector in vectors]
    remainder = [target.get(name, 0) for name in names]
    for row in range(len(names)):
        while any(column[row] for column in columns):
            pivot_index = min((i for i, col in enumerate(columns) if col[row]),
                              key=lambda i: abs(columns[i][row]))
            columns[0], columns[pivot_index] = columns[pivot_index], columns[0]
            pivot = columns[0]
            for index in range(1, len(columns)):
                quotient = columns[index][row] // pivot[row]
                columns[index] = [a - quotient * b for a, b in zip(columns[index], pivot)]
            if any(column[row] for column in columns[1:]):
                continue
            if remainder[row] % pivot[row]:
                return False
            quotient = remainder[row] // pivot[row]
            remainder = [a - quotient * b for a, b in zip(remainder, pivot)]
            columns = columns[1:]
            break
        if remainder[row]:
            return False
    return not any(remainder)


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
    units = set()
    for match in TOKEN.finditer(text):
        unit = re.sub(r"\s+", "", match[1])
        if not is_counter(unit, rules):
            units.add(unit)
    known = {normalized(u) for u in [
        *(contract.get("technology") or {}).get("units", []),
        *rules.get("measure_units", []), *(rules.get("time_basis_aliases") or {}), *declared]}
    # Longest notation wins, including compound natural-language units.
    if known:
        pattern = r"(?<![\d.])" + NUMBER + r"\s*(" + "|".join(
            re.escape(u) for u in sorted(known, key=len, reverse=True) if u) + r")((?:\s*[/*·×]\s*" + DENOMINATOR + r")*)"
        for match in re.finditer(pattern, text):
            unit = match[1] + re.sub(r"\s+", "", match[2])
            if unit.isascii() and re.match(r"[A-Za-z0-9/^]", text[match.end():]):
                continue  # a prefix of a longer symbol is not another unit
            if not is_counter(unit, rules):
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


def count_only(text, rules):
    """A nominal label and number+counter, with no substantive predicate."""
    counters = rules.get("count_units") or []
    if not counters:
        return False
    counter = "(?:" + "|".join(re.escape(v) for v in sorted(counters, key=len, reverse=True)) + ")"
    for pattern in rules.get("count_only_patterns", []):
        if re.fullmatch(pattern.replace("{number}", NUMBER).replace("{counter}", counter),
                        normalized(text), re.IGNORECASE):
            return True
    return False
