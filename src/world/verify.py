"""Retained deterministic checks for neutral reference material and consistency."""

from __future__ import annotations

import copy
import json
import logging
import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple,
)

import yaml

from .textsim import (
    character_ngrams, echo_coverage, is_cjk_text, jaccard, ngrams_of,
    normalize_item,
)
from .graph import SCALES, SCALE_RANK, get_entity, local_context, new_graph, make_entity
from .operators import OperatorError, validate_candidate
from .premises import contract_checks_enabled, premise_source, unit_symbols, world_premises
from .quantities import count_only, observed_units, registered_unit, unit_notation, temporal_conflicts, units_in_text
from .language import load_language_rules, rules_for

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"

Similarity = Callable[[str, str], float]


@dataclass
class Deduction:
    """Why one field of a candidate lost points."""

    verifier: str
    field: str      # "name", "summary", "facts[2]", "provenance.reason", ...
    code: str       # stable machine-readable reason
    message: str    # human-readable explanation
    penalty: float = 0.0
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"verifier": self.verifier, "field": self.field,
                "code": self.code, "message": self.message,
                "penalty": round(self.penalty, 4), "detail": dict(self.detail)}


@dataclass
class VerifierResult:
    name: str
    score: float
    deductions: List[Deduction] = field(default_factory=list)
    skipped: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "score": round(self.score, 4),
                "skipped": self.skipped,
                "deductions": [d.to_dict() for d in self.deductions]}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _score(deductions: Sequence[Deduction]) -> float:
    return _clamp(1.0 - sum(d.penalty for d in deductions))


# ------------------------------------------------------------- text helpers

def entity_text(entity: Mapping[str, Any]) -> str:
    parts = [str(entity.get("name") or ""), str(entity.get("summary") or "")]
    parts += [str(f.get("text") or "") for f in entity.get("facts") or []
              if isinstance(f, Mapping)]
    return "\n".join(p for p in parts if p)


def language_of(graph: Mapping[str, Any]) -> str:
    lang = (graph.get("meta") or {}).get("language") or ""
    return str(lang).split("-")[0].split("_")[0].lower()


def _pattern_hits(text: str, patterns: Iterable[str]) -> List[Tuple[str, int]]:
    hits = []
    for pat in patterns:
        found = re.findall("(?:" + pat + ")", text, flags=re.IGNORECASE)
        if found:
            hits.append((re.search(pat, text, flags=re.IGNORECASE).group(0),
                         len(found)))
    return hits


def _speech_spans(text: str, r: Mapping[str, Any]) -> List[str]:
    """Quoted spans that look like an utterance rather than a quoted term."""
    punct = str(r.get("speech_punct") or "")
    limit = int(r.get("max_quote_chars") or 0)
    after = [re.compile(p, re.IGNORECASE) for p in r.get("speech_after") or []]
    before = [re.compile(p, re.IGNORECASE) for p in r.get("speech_before") or []]
    out: List[str] = []
    for pair in r.get("quote_pairs") or []:
        if len(pair) != 2:
            continue
        o, c = re.escape(pair[0]), re.escape(pair[1])
        for m in re.finditer(o + "([^" + c + "]+)" + c, text):
            inner = m.group(1)
            tail = text[m.end(): m.end() + 40]
            head = text[max(0, m.start() - 40): m.start()]
            tail = re.sub(r"^[\s,、，.]+", "", tail)
            if (any(ch in inner for ch in punct)
                    or (limit and len(inner) > limit)
                    or any(a.match(tail) for a in after)
                    or any(b.search(head) for b in before)):
                out.append(m.group(0))
    return out


def _word_hits(text: str, words: Iterable[str]) -> List[Tuple[str, int]]:
    """Count each word; ASCII words match whole words, others as substrings."""
    hits = []
    for w in words:
        if not w:
            continue
        if w.isascii():
            n = len(re.findall(
                r"(?<![A-Za-z0-9])" + re.escape(w) + r"(?![A-Za-z0-9])",
                text, flags=re.IGNORECASE))
        else:
            n = text.count(w)
        if n:
            hits.append((w, n))
    return hits


# --------------------------------------------------------------- similarity

def ngram_similarity(a: str, b: str, n: int = 3) -> float:
    """Deterministic character n-gram Jaccard (works without word splitting)."""
    na, nb = normalize_item(a), normalize_item(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return jaccard(character_ngrams(na, n), character_ngrams(nb, n))


def embedding_similarity(embed: Callable[[str], Sequence[float]]) -> Similarity:
    """Build a cosine :data:`Similarity` from an ``embed(text) -> vector``."""
    def sim(a: str, b: str) -> float:
        va, vb = list(embed(a)), list(embed(b))
        dot = sum(x * y for x, y in zip(va, vb))
        na = sum(x * x for x in va) ** 0.5
        nb = sum(y * y for y in vb) ** 0.5
        return _clamp(dot / (na * nb)) if na and nb else 0.0
    return sim


def _penalty_from_similarity(sim: float, floor: float) -> float:
    return _clamp((sim - floor) / (1.0 - floor)) if floor < 1 else 0.0


# ---------------------------------------------------------------- reference

def reference_text(
    graph: Mapping[str, Any], target_id: Optional[str],
    brief: Optional[Mapping[str, Any]] = None,
    limits: Optional[Mapping[str, int]] = None,
) -> str:
    """Wording a candidate may merely repeat: the brief and its local context.

    Used to measure how much of a candidate is *new* information.  It holds
    the brief's statements (text and quote), open questions and constraints,
    plus the target, its parent, siblings and related entities (or the
    world-scale entities when there is no target).
    """
    parts: List[str] = []
    for key in ("statements", "open_questions", "constraints"):
        for item in (brief or {}).get(key, []) or []:
            if isinstance(item, Mapping):
                parts += [str(item.get("text") or ""), str(item.get("quote") or "")]
    views: List[Mapping[str, Any]] = []
    if target_id and get_entity(graph, target_id):
        ctx = local_context(graph, target_id, limits)
        views = [ctx["entity"], ctx.get("parent") or {}] \
            + list(ctx["siblings"]) + list(ctx["related"])
    else:
        views = [e for e in graph.get("entities", [])
                 if e.get("scale") == "world"][:6]
    for v in views:
        parts.append(str(v.get("name") or ""))
        parts.append(str(v.get("summary") or ""))
        parts += [str(f.get("text") or "") for f in v.get("facts") or []
                  if isinstance(f, Mapping)]
    return "\n".join(x for x in parts if x)


def verify_provenance(
    candidate: Mapping[str, Any], graph: Mapping[str, Any],
    brief: Optional[Mapping[str, Any]] = None,
    params: Optional[Mapping[str, Any]] = None,
) -> VerifierResult:
    pen = (params or {}).get("penalties", {})
    prov = candidate["entity"].get("provenance") or {}
    sids = [s for s in prov.get("statement_ids") or [] if isinstance(s, str)]
    srcs = [s for s in prov.get("derived_from") or [] if isinstance(s, str)]
    reason = prov.get("reason") if isinstance(prov.get("reason"), str) else ""
    d: List[Deduction] = []
    if not sids and not srcs:
        d.append(Deduction(
            "provenance", "provenance", "no_anchor",
            "cites neither a brief statement nor an existing entity",
            float(pen.get("no_anchor", 1.0))))
    if brief is not None:
        known = {s.get("id") for s in brief.get("statements", []) or []
                 if isinstance(s, Mapping)}
        for s in sids:
            if s not in known:
                d.append(Deduction(
                    "provenance", "provenance.statement_ids", "unknown_reference",
                    f"statement {s} does not exist",
                    float(pen.get("unknown_reference", 0.4)), {"id": s}))
    for s in srcs:
        if get_entity(graph, s) is None:
            d.append(Deduction(
                "provenance", "provenance.derived_from", "unknown_reference",
                f"entity {s} does not exist",
                float(pen.get("unknown_reference", 0.4)), {"id": s}))
    if srcs and not reason.strip():
        d.append(Deduction(
            "provenance", "provenance.reason", "missing_reason",
            "derived from existing entities without saying why",
            float(pen.get("missing_reason", 0.4))))
    return VerifierResult("provenance", _score(d), d)


_MEASURE_PATTERNS = (r"\d\s*[:/]\s*\d", r"\d\.\d", r"\d\s*(?:%|‰|°)")


def _is_measure(text: str, rl: Mapping[str, Any]) -> bool:
    """A number tied to a unit, ratio, percentage or enough descriptive text."""
    t = unicodedata.normalize("NFKC", text)
    if any(re.search(pat, t) for pat in _MEASURE_PATTERNS):
        return True
    units = rl.get("measure_units") or []
    if units and _word_hits(t, units):
        return True
    # A named measurable subject can make a bare value meaningful even when
    # the language omits a unit (for example "population 4200").
    if _word_hits(t, rl.get("measurement_subject_words") or []):
        return True
    rest = re.sub(r"[\d\s.,:;/()\-+~約およそ頃ほど]+", " ", t).strip()
    if is_cjk_text(rest):
        return len(rest.replace(" ", "")) >= int(rl.get("measure_min_chars", 5))
    return len(re.findall(r"[^\W\d_]{2,}", rest)) >= int(
        rl.get("measure_min_words", 2))


def _measure_is_grounded(text: str, rl: Mapping[str, Any]) -> bool:
    """Whether a numeric expression names what it measures.

    Units make a quantity concrete, but a percentage or ratio still needs a
    measured subject. This catches statements such as an unexplained
    ``5% contribution`` without rejecting a value such as ``rainfall 41 mm``.
    The vocabulary is language data, not a setting-specific rule.
    """
    t = unicodedata.normalize("NFKC", text)
    subjects = rl.get("measurement_subject_words") or []
    number_spans = list(re.finditer(r"\d[\d,]*(?:\.\d+)?", t))
    windows = [t[max(0, m.start() - 48): min(len(t), m.end() + 48)]
               for m in number_spans]
    # A nearby evaluation word is evidence that the number is being used as
    # rhetoric (for example "5% contribution"), not as a measurement.
    if any(_word_hits(window, rl.get("evaluation_words") or [])
           for window in windows):
        return False
    if any(_word_hits(window, subjects) for window in windows):
        return True
    # Absolute units identify their dimension without an extra noun (for
    # example "500 square kilometres" or "41 mm"). Ratios and percentages do
    # not: their subject is essential to their meaning.
    if re.search(r"\d\s*(?:%|‰|°)|\d\s*[:/]\s*\d", t):
        return False
    free_units = rl.get("self_describing_measure_units") or rl.get(
        "measure_units") or []
    return bool(_word_hits(t, free_units))


def _fact_hollowness(
    fact: Mapping[str, Any], rl: Mapping[str, Any], reference: str,
    p: Mapping[str, Any], context: str = "",
) -> Optional[Tuple[str, str]]:
    """Return ``(code, message)`` when a fact only fills in its kind label."""
    kind, text = fact.get("kind"), str(fact.get("text") or "").strip()
    if count_only(text, rl):
        code = "bare_count" if kind == "number" and not _is_measure(text, rl) else "thin_fact"
        return (code, "a number and counter alone adds no property, procedure or result")
    if _pattern_hits(unicodedata.normalize("NFKC", text),
                     rl.get("thin_fact_patterns") or []):
        code = "bare_count" if kind == "number" and not _is_measure(text, rl) else "thin_fact"
        return (code, "an identifier or count alone adds no mechanism, "
                "condition or consequence about this entity")
    if kind == "object" and _pattern_hits(text, rl.get("non_object_patterns") or []):
        return ("non_object_fact", "an object fact must describe a physical tool, "
                "facility or item; this describes a person's attribute, relation or role")
    if kind in ("proper_noun", "object") and reference.strip():
        cov = echo_coverage(text, reference, int(p.get("echo_min_chars", 2)))
        if cov >= float(p.get("fact_echo_threshold", 0.6)):
            return ("echoes_input",
                    f"this {kind} fact is made of words from the input or "
                    "the surrounding entities; give a new, specific one")
    if kind == "proper_noun":
        compact = normalize_item(text)
        if is_cjk_text(compact):
            if len(compact) < int(rl.get("proper_noun_min_chars", 3)):
                return ("generic_name",
                        "a short common noun, not a proper name; give the "
                        "particular name this thing carries")
        elif rl.get("proper_noun_requires_capital") and not any(
                c.isupper() for c in text):
            return ("generic_name",
                    "a common noun, not a proper name; give the particular "
                    "name this thing carries")
    if kind == "number" and any(
            unicodedata.category(c) == "Nd"
            for c in unicodedata.normalize("NFKC", text)):
        if not _is_measure(text, rl):
            return ("bare_count",
                    "a bare count; give a measured quantity with a unit, "
                    "a ratio, or a period, tied to what it measures")
        if not _measure_is_grounded(text + " " + context, rl):
            return ("ungrounded_measure",
                    "the numeric value has no named measured subject; tie it "
                    "to a quantity, rate, ratio or other observable measure")
    return None


def _unsupported_claims(text, rules, key):
    """Check each claim's sentence, so unrelated facts cannot rescue rhetoric.

    Language syntax offers conservative positive evidence; the semantic
    judge handles paraphrases and whether the procedure actually causes the
    claimed effect. No unit, device, institution or world is assumed here.
    """
    for sentence in re.split(r"[。;；.!?\n]+", str(text)):
        hits = _word_hits(sentence, rules.get(key) or [])
        if hits and not all(_pattern_hits(sentence, rules.get("mechanism_" + part + "_patterns") or [])
                            for part in ("actor", "procedure", "condition", "result")):
            yield from hits


def verify_specificity(
    candidate: Mapping[str, Any], language: str,
    rules: Mapping[str, Any], params: Optional[Mapping[str, Any]] = None, *,
    reference: str = "",
) -> VerifierResult:
    p = params or {}
    pen = p.get("penalties", {})
    entity = candidate["entity"]
    rl = rules_for(rules, language)
    facts = [f for f in entity.get("facts") or [] if isinstance(f, Mapping)]
    d: List[Deduction] = []
    hollow_total = 0.0
    solid: List[Mapping[str, Any]] = []
    for i, f in enumerate(facts):
        h = _fact_hollowness(
            f, rl, reference, p, str(entity.get("summary") or ""))
        if h is None:
            solid.append(f)
            continue
        each = float(pen.get("hollow_fact", 0.2))
        room = max(0.0, float(pen.get("hollow_cap", 0.5)) - hollow_total)
        hollow_total += min(each, room)
        d.append(Deduction("specificity", f"facts[{i}]", h[0], h[1],
                           min(each, room), {"kind": f.get("kind")}))
    if not facts:
        d.append(Deduction("specificity", "facts", "no_facts",
                           "no concrete facts at all",
                           float(pen.get("no_facts", 0.6))))
    else:
        kinds = {f.get("kind") for f in solid} - {"other", None}
        need = max(1, int(p.get("min_fact_kinds", 3)))
        if len(kinds) < need:
            d.append(Deduction(
                "specificity", "facts", "kind_coverage",
                f"facts cover {len(kinds)} kind(s); add more of: proper_noun, "
                "number, period, procedure, object, expression",
                float(pen.get("kind_coverage", 0.4)) * (1 - len(kinds) / need),
                {"kinds": sorted(kinds)}))
        nouns = sum(1 for f in solid if f.get("kind") == "proper_noun")
        need_n = int(p.get("min_proper_noun_facts", 1))
        if nouns < need_n:
            d.append(Deduction(
                "specificity", "facts", "proper_noun",
                f"{nouns} proper-noun fact(s); expected {need_n}",
                float(pen.get("proper_noun", 0.25)), {"count": nouns}))
    body = "\n".join([str(entity.get("summary") or "")] + [
        str(f.get("text") or "") for f in facts])
    if p.get("require_numeral", True):
        has_num = any(f.get("kind") in ("number", "period") for f in facts) or any(
            unicodedata.category(c) == "Nd"
            for c in unicodedata.normalize("NFKC", body))
        if not has_num:
            d.append(Deduction("specificity", "facts", "numeral",
                               "no numeral, quantity or date anywhere",
                               float(pen.get("numeral", 0.15))))
    words = rl.get("abstract_words") or []
    if words and body.strip():  # unknown language: structural checks only
        hits = _word_hits(body, words)
        density = sum(len(w) * n for w, n in hits) / max(1, len(body))
        limit = float(p.get("max_abstract_density", 0.04))
        if density > limit:
            cap = float(pen.get("abstract_density", 0.4))
            d.append(Deduction(
                "specificity", "summary", "abstract_density",
                "abstract words stand in for concrete description: "
                + ", ".join(w for w, _ in hits),
                min(cap, cap * (density - limit) / max(limit, 1e-9)),
                {"density": round(density, 4), "words": [w for w, _ in hits]}))
    for field_name, text in [("summary", entity.get("summary", ""))] + [
            (f"facts[{i}]", f.get("text", "")) for i, f in enumerate(facts)]:
        for key, code in (("evaluation_words", "unsupported_evaluation"),
                          ("purpose_words", "purpose_without_mechanism")):
            hits = list(_unsupported_claims(text, rl, key))
            if hits:
                amount = float(pen.get(code, 0.25))
                d.append(Deduction(
                    "specificity", field_name, code,
                    "a purpose or effect claim needs an actor, procedure, condition and observable result: "
                    + ", ".join(w for w, _ in hits),
                    min(float(pen.get(code + "_cap", amount)), amount * len(hits)),
                    {"words": [w for w, _ in hits]}))
    return VerifierResult("specificity", _score(d), d)


_NUM = re.compile(r"\d+")
_MEASURE_TOKEN = re.compile(
    r"(?<![0-9A-Za-z])([0-9][0-9,]*(?:\.[0-9]+)?)[ \t]*"
    r"(%|‰|°|[A-Za-z]+|[\u3040-\u30ff\u3400-\u9fff]{1,8})?"
)


def _measure_tokens(text: Any) -> set:
    """Return normalized number+unit tokens suitable for repeat detection."""
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    out = set()
    for match in _MEASURE_TOKEN.finditer(normalized):
        suffix = normalize_item(match.group(2) or "")
        # A bare number is commonly a reference index or a count. Requiring a
        # unit keeps this check focused on repeated measured values.
        if suffix:
            value = match.group(1).replace(",", "")
            out.add(f"{value}:{suffix}")
    return out


def _entity_measure_occurrences(entity: Mapping[str, Any]) -> Dict[str, set]:
    """Map a measured token to the normalized fields in which it occurs."""
    texts = [entity.get("name", ""), entity.get("summary", "")]
    texts += [f.get("text", "") for f in entity.get("facts") or []
              if isinstance(f, Mapping)]
    out: Dict[str, set] = {}
    for text in texts:
        normalized = normalize_item(text)
        for token in _measure_tokens(text):
            out.setdefault(token, set()).add(normalized)
    return out


def _ancestors(graph: Mapping[str, Any], eid: Optional[str]) -> List[str]:
    out, seen = [], set()
    while eid and eid not in seen:
        seen.add(eid)
        out.append(eid)
        e = get_entity(graph, eid)
        eid = e.get("parent") if e else None
    return out


def _period_start(entity: Mapping[str, Any]) -> Optional[int]:
    """Earliest year-like integer in ``period`` facts (3+ digits preferred)."""
    nums: List[int] = []
    for f in entity.get("facts") or []:
        if isinstance(f, Mapping) and f.get("kind") == "period":
            text = unicodedata.normalize("NFKC", str(f.get("text") or ""))
            found = [int(x) for x in _NUM.findall(text)]
            big = [x for x in found if x >= 100]
            nums += big or found
    return min(nums) if nums else None


def _labelled_numbers(entity: Mapping[str, Any]) -> Dict[str, set]:
    """Map a fact's leading label to the first number that follows it."""
    out: Dict[str, set] = {}
    for f in entity.get("facts") or []:
        if not isinstance(f, Mapping):
            continue
        text = unicodedata.normalize("NFKC", str(f.get("text") or ""))
        m = _NUM.search(text.replace(",", ""))
        if not m:
            continue
        label = normalize_item(text[: text.replace(",", "").find(m.group(0))])
        if len(label) >= 2:
            out.setdefault(label, set()).add(int(m.group(0)))
    return out


def verify_consistency(
    candidate: Mapping[str, Any], graph: Mapping[str, Any],
    axes: Optional[Sequence[Mapping[str, Any]]] = None,
    brief: Optional[Mapping[str, Any]] = None,
    params: Optional[Mapping[str, Any]] = None,
) -> VerifierResult:
    pen = (params or {}).get("penalties", {})
    entity = candidate["entity"]
    d: List[Deduction] = []

    def add(fld, code, msg, **detail):
        # Unknown units and derived capability proposals are observations,
        # not evidence that the world lacks the means to measure/use them.
        penalty = 0.0 if code in {"undefined_unit", "technology_extension"} else float(pen.get(code, 0.4))
        d.append(Deduction("consistency", fld, code, msg, penalty, detail))

    # A hierarchy edge is not only a scale edge. A place nested under an
    # institution at a broad scale usually means that an organization was
    # mistaken for a container. A small site/detail can be an institution's
    # physical location, while places may contain places at any lower scale.
    parent_id = entity.get("parent")
    parent_entity = get_entity(graph, parent_id) if parent_id else None
    if parent_entity and entity.get("type") == "place":
        parent_type = parent_entity.get("type")
        child_scale = entity.get("scale")
        allowed = parent_type == "place" or (
            parent_type == "institution" and child_scale in {"site", "detail"}
        )
        if not allowed:
            add(
                "parent",
                "parent_type",
                "a place cannot be a broad-scale child of this parent type; "
                "use a containing place or a site/detail location",
                parent=parent_id, parent_type=parent_type,
                child_type=entity.get("type"), child_scale=child_scale,
            )

    for err in validate_candidate(graph, candidate, axes, brief):
        add("entity", "graph_invalid", err)

    contract = world_premises(graph)
    proposed = entity.get("world_premises") if contract_checks_enabled(graph) else None
    if contract and proposed is not None:
        source = premise_source(graph, contract["source_entity"])
        if proposed != source["world_premises"]:
            add("world_premises", "premise_conflict",
                "the candidate changes the established calendar, technology or society contract")
    if not contract and candidate.get("operator") == "premise" and proposed:
        contract = proposed
    if contract:
        _verify_premise_usage(entity, contract, language_of(graph), add)
    rules = rules_for(load_language_rules(), language_of(graph))
    for field_name, text in [("name", entity.get("name", "")),
                             ("summary", entity.get("summary", ""))] + [
            (f"facts[{i}]", f.get("text", "")) for i, f in enumerate(entity.get("facts", []))]:
        for detail in temporal_conflicts(text, rules):
            add(field_name, "dimension_conflict",
                "quantity basis conflicts with its rate denominator; distinguish a total from a rate",
                **detail)

    rels = [r for r in entity.get("relations") or [] if isinstance(r, Mapping)]
    by_target: Dict[str, set] = {}
    for i, r in enumerate(rels):
        t = r.get("target")
        if t == entity.get("id"):
            add(f"relations[{i}]", "self_relation", "relates to itself")
        by_target.setdefault(t, set()).add(r.get("type"))
    for t, types in by_target.items():
        if "opposes" in types and types & {
                "part_of", "member_of", "located_in", "derived_from"}:
            add("relations", "relation_conflict",
                f"both opposes and belongs to/derives from {t}", target=t)

    # Location: a located_in target must lie on the same ancestry line as parent.
    parent = entity.get("parent")
    if parent:
        line = set(_ancestors(graph, parent))
        for i, r in enumerate(rels):
            if r.get("type") != "located_in" or get_entity(graph, r.get("target")) is None:
                continue
            t = r["target"]
            if t not in line and parent not in _ancestors(graph, t):
                add(f"relations[{i}]", "location_conflict",
                    f"located_in {t}, which is unrelated to its parent {parent}",
                    target=t, parent=parent)

    # Time: a cause or earlier event must not start after what it affects.
    start = _period_start(entity)
    if start is not None:
        for i, r in enumerate(rels):
            if r.get("type") in ("causes", "affects"):
                other = get_entity(graph, r.get("target"))
                o_start = _period_start(other) if other else None
                if o_start is not None and start > o_start:
                    add(f"relations[{i}]", "temporal_order",
                        f"{r['type']} {r['target']} but starts at {start}, "
                        f"after its {o_start}", target=r["target"])

    # Numbers: one label with two different values; same-name entities too.
    mine = _labelled_numbers(entity)
    for label, vals in mine.items():
        if len(vals) > 1:
            add("facts", "number_conflict",
                f"label {label!r} has conflicting values {sorted(vals)}")
    name = normalize_item(entity.get("name", ""))
    for other in graph.get("entities", []):
        if name and normalize_item(other.get("name", "")) == name:
            for label, vals in _labelled_numbers(other).items():
                if label in mine and mine[label] != vals:
                    add("facts", "number_conflict",
                        f"{label!r} differs from existing {other['id']}",
                        entity=other["id"])
    return VerifierResult("consistency", _score(d), d)


def _verify_premise_usage(entity, contract, language, add):
    """Lexical checks against the contract, plus declared semantic references.

    Prose alone cannot reliably identify all apparatus or implied capabilities;
    the optional consistency judge checks those and missing declarations.
    """
    calendar, technology = contract["calendar"], contract["technology"]
    symbols = unit_symbols(contract)
    markers = [unicodedata.normalize("NFKC", value).strip()
               for value in [calendar["name"], *calendar["markers"]]]
    usage = entity.get("premise_usage") or {}
    rules = rules_for(load_language_rules(), language)
    for key, allowed, code in (
            ("calendars", markers, "undefined_calendar"),
            ("technologies", technology["capabilities"], "undefined_technology"),
            ("units", symbols, "undefined_unit")):
        for term in usage.get(key, []):
            if (not registered_unit(term, contract, rules) if key == "units"
                    else normalize_item(term) not in {normalize_item(v) for v in allowed}):
                add(f"premise_usage.{key}", code,
                    f"{term!r} is not defined; review measurability and capability limits", term=term)

    fields = [("name", entity.get("name", "")),
              ("summary", entity.get("summary", ""))]
    fields += [(f"facts[{i}]", f.get("text", ""))
               for i, f in enumerate(entity.get("facts", []))]
    for field_name, text in fields:
        text = unicodedata.normalize("NFKC", str(text))
        date_text = text
        for pattern in rules.get("duration_patterns", []):
            date_text = re.sub(pattern, lambda m: " " * len(m.group(0)),
                               date_text, flags=re.IGNORECASE)
        # The syntax recognizes dates, not any particular calendar. Require
        # a declared marker next to each absolute date; ranges share a marker.
        patterns = list(rules.get("absolute_date_patterns", []))
        period_pattern = r"(?<![\d.])\d{3,}(?:\s*[-–~〜]\s*\d+)?(?![\d.A-Za-z])"
        if field_name.startswith("facts["):
            index = int(field_name[6:-1])
            if entity["facts"][index].get("kind") == "period":
                patterns.append(period_pattern)
        seen_dates = set()
        for pattern in patterns:
            for match in re.finditer(pattern, date_text, re.IGNORECASE):
                if any(a <= match.start() < b for a, b in seen_dates):
                    continue
                if pattern == period_pattern:
                    suffix = date_text[match.end():].lstrip()
                    if any(suffix.startswith(u) and (
                            not u.isascii() or len(suffix) == len(u)
                            or not suffix[len(u)].isalpha())
                           for u in symbols):
                        continue  # a duration/measurement, not a bare year
                seen_dates.add(match.span())
                prefix = date_text[max(0, match.start() - 48):match.start()]
                if not any(re.search(re.escape(marker) + r"\s*$", prefix,
                                     re.IGNORECASE) for marker in markers):
                    add(field_name, "undefined_calendar",
                        "absolute date lacks a calendar marker defined in the premises",
                        date=match.group(0))
        # Unknown symbolic units can be detected without enumerating devices
        # or technical units. Natural-language units use language syntax data.
        units = units_in_text(text, contract, rules, usage.get("units", []))
        # Counter nouns are quantity syntax, not technical measurement units.
        counters = {normalize_item(v) for v in rules.get("count_units", [])}
        unknown = sorted(u for u in units if not registered_unit(u, contract, rules)
                         and normalize_item(u) not in counters)
        if unknown:
            add(field_name, "undefined_unit",
                "unregistered units; consistency judge must review measurability: "
                + ", ".join(unknown), units=unknown)


def verify_objectivity(
    candidate: Mapping[str, Any], language: str,
    rules: Mapping[str, Any], params: Optional[Mapping[str, Any]] = None,
) -> VerifierResult:
    pen = (params or {}).get("penalties", {})
    summary = str(candidate["entity"].get("summary") or "")
    r = rules_for(rules, language)
    d: List[Deduction] = []

    def add(code, msg, **detail):
        d.append(Deduction("objectivity", "summary", code, msg,
                           float(pen.get(code, 0.3)), detail))

    quoted = _speech_spans(summary, r)
    if quoted:
        add("quotation", "quoted speech in the summary; move quotations "
            "into facts", spans=quoted[:3])
    for code, key, msg in (
        ("first_person", "first_person", "first-person voice"),
        ("second_person", "second_person", "addresses the reader"),
        ("flourish", "flourish", "rhetorical or promotional wording"),
    ):
        hits = _word_hits(summary, r.get(key) or []) + \
            _pattern_hits(summary, r.get(key + "_patterns") or [])
        if hits:
            add(code, msg + ": " + ", ".join(w for w, _ in hits),
                words=[w for w, _ in hits])
    if any(m in summary for m in r.get("exclamation") or []):
        add("exclamation", "exclamation mark in an explanatory text")
    if any(m in summary for m in r.get("question") or []):
        add("question", "rhetorical question in an explanatory text")
    return VerifierResult("objectivity", _score(d), d)


def verify_novelty(
    candidate: Mapping[str, Any], graph: Mapping[str, Any],
    similarity: Optional[Similarity] = None,
    params: Optional[Mapping[str, Any]] = None,
) -> VerifierResult:
    p = params or {}
    sim = similarity or (lambda a, b: ngram_similarity(a, b, int(p.get("ngram_size", 3))))
    floor = float(p.get("similarity_floor", 0.4))
    entity = candidate["entity"]
    text = entity_text(entity)
    best, best_id = 0.0, None
    for other in graph.get("entities", []):
        if other.get("id") == entity.get("id"):
            continue
        s = sim(text, entity_text(other))
        a, b = entity.get("summary"), other.get("summary")
        if a and b:  # a renamed copy still repeats the explanation
            s = max(s, sim(str(a), str(b)))
        if normalize_item(other.get("name", "")) == normalize_item(entity.get("name", "")):
            s = 1.0
        if s > best:
            best, best_id = s, other.get("id")
    penalty = _penalty_from_similarity(best, floor)
    d: List[Deduction] = []
    if penalty > 0:
        d.append(Deduction(
            "novelty", "summary", "duplicate",
            f"substantially duplicates existing entity {best_id}",
            penalty, {"similarity": round(best, 4), "entity": best_id}))
    # Detect repeated measurements even when the surrounding explanations are
    # different, e.g. two entities both claiming the same output quantity.
    own_measures = _entity_measure_occurrences(entity)
    measure_penalty = 0.0
    measure_cap = float(p.get("duplicate_measure_cap", 0.45))
    each_measure = float(p.get("duplicate_measure_penalty", 0.3))
    for other in graph.get("entities", []):
        if other.get("id") == entity.get("id"):
            continue
        other_measures = _entity_measure_occurrences(other)
        shared = sorted(
            token for token in own_measures.keys() & other_measures.keys()
            # An identical field is a copied detail, not evidence that two
            # independently described entities reused a value.
            if not own_measures[token] & other_measures[token])
        if not shared:
            continue
        amount = min(each_measure, max(0.0, measure_cap - measure_penalty))
        if amount <= 0:
            break
        measure_penalty += amount
        d.append(Deduction(
            "novelty", "facts", "duplicate_measure",
            "reuses a measured value already assigned to another entity",
            amount, {"entity": other.get("id"), "tokens": shared[:5]}))
    penalty += measure_penalty

    # Long shared character n-grams catch repeated wording that is not close
    # enough for whole-entity Jaccard to flag it. The threshold is configured
    # in characters, so it works for both spaced and CJK input.
    phrase_size = int(p.get("duplicate_phrase_ngram_size", 8))
    phrase_min = int(p.get("duplicate_phrase_min_ngrams", 3))
    phrase_share = float(p.get("duplicate_phrase_share", 0.18))
    own_phrases = ngrams_of(entity.get("summary", ""), phrase_size)
    phrase_each = float(p.get("duplicate_phrase_penalty", 0.3))
    if own_phrases:
        for other in graph.get("entities", []):
            if other.get("id") == entity.get("id"):
                continue
            shared = own_phrases & ngrams_of(other.get("summary", ""), phrase_size)
            if len(shared) < phrase_min or len(shared) / len(own_phrases) < phrase_share:
                continue
            penalty += phrase_each
            d.append(Deduction(
                "novelty", "summary", "duplicate_phrase",
                "reuses a long phrase from another entity",
                phrase_each, {"entity": other.get("id"),
                              "shared_ngrams": len(shared)}))
            break
    penalty = _clamp(penalty)
    return VerifierResult("novelty", 1.0 - penalty, d)
