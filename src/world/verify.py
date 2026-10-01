"""Verifiers that score one candidate entity (each score is in [0, 1]).

Every verifier is deterministic by default and returns a
:class:`VerifierResult` holding a score (1 is best) and structured
:class:`Deduction` records saying which field was penalized and why, so a
critique-and-rewrite step can act on them.  LLM judges and embedding
similarity are optional plug-ins and are never used unless supplied.

Verifiers know no genre, era or setting.  Language-dependent word lists come
from ``config/world/language_rules.yaml`` keyed by language code.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple,
)

import yaml

from ..quality import character_ngrams, jaccard, normalize_item
from .graph import SCALES, SCALE_RANK, get_entity, local_context, new_graph, make_entity
from .operators import OperatorError, validate_candidate

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
DEFAULT_RULES_PATH = CONFIG_DIR / "world" / "language_rules.yaml"
DEFAULT_VERIFIER_PROMPTS = CONFIG_DIR / "prompts" / "world" / "verifiers.yaml"

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


def load_language_rules(path: Any = None) -> Dict[str, Any]:
    return yaml.safe_load(
        Path(path or DEFAULT_RULES_PATH).read_text(encoding="utf-8")) or {}


def rules_for(rules: Mapping[str, Any], language: str) -> Dict[str, Any]:
    """Merge the ``default`` rules with those of ``language`` (if any)."""
    merged = dict(rules.get("default") or {})
    merged.update(rules.get(language) or {})
    return merged


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


# ----------------------------------------------------------------- contrasts

def _contrast_view(entity: Mapping[str, Any]) -> Dict[str, Any]:
    return {"name": entity.get("name", ""), "summary": entity.get("summary", ""),
            "facts": [f.get("text", "") for f in entity.get("facts") or []]}


class ContrastProvider:
    """Produce and cache *contrast candidates*: the model's prior for a slot.

    A contrast is made by running the same operator on a placeholder target
    of the same scale and type, with no brief, no axes and no world-specific
    context, so the output reflects what the model writes for any world.
    Results are cached per (operator, target scale, target type, language),
    in memory and, if ``package_dir`` is given, in ``world/contrasts.json``.
    """

    RELATIVE_PATH = Path("world") / "contrasts.json"

    def __init__(self, runner: Any, package_dir: Any = None, n: int = 3) -> None:
        self.runner = runner
        self.n = n
        self.path = Path(package_dir) / self.RELATIVE_PATH if package_dir else None
        self._cache: Dict[str, List[Dict[str, Any]]] = {}
        if self.path and self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._cache = {k: v for k, v in data.items()
                                   if isinstance(v, list)}
            except (OSError, ValueError):
                self._cache = {}

    @staticmethod
    def key(operator: str, scale: str, etype: str, language: str) -> str:
        return "|".join((operator, scale, etype, language))

    def _save(self) -> None:
        if not self.path:
            return
        from ..checkpoint_manager import CheckpointManager
        payload = json.dumps(self._cache, ensure_ascii=False, indent=2,
                             sort_keys=True).encode("utf-8")
        CheckpointManager._atomic_write(self.path, payload)

    @staticmethod
    def _stub_graph(language: str, scale: str, etype: str):
        """Placeholder ancestry down to ``scale``; no world content."""
        graph = new_graph(language or "und")
        prov = {"statement_ids": ["none"], "derived_from": [], "reason": ""}
        parent = None
        for i in range(SCALE_RANK[scale] + 1):
            eid = f"e{i + 1}"
            graph["entities"].append(make_entity(
                eid, etype if SCALES[i] == scale else "concept",
                f"unspecified {SCALES[i]}", SCALES[i], parent=parent,
                provenance=prov))
            parent = eid
        return graph, parent

    def get(
        self, operator: str, graph: Mapping[str, Any],
        target_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        language = (graph.get("meta") or {}).get("language") or "und"
        target = get_entity(graph, target_id) if target_id else None
        scale = target["scale"] if target else "world"
        etype = target["type"] if target else "-"
        k = self.key(operator, scale, etype, language)
        if k in self._cache:
            return self._cache[k]
        try:
            if target is None:
                stub, tid = new_graph(language), None
            else:
                stub, tid = self._stub_graph(language, scale, etype)
            cands = self.runner.run(operator, stub, tid, self.n)
        except OperatorError:
            return []
        views = [_contrast_view(c["entity"]) for c in cands]
        if views:
            self._cache[k] = views
            self._save()
        return views


# ---------------------------------------------------------------- verifiers

def verify_genericity(
    candidate: Mapping[str, Any], contrasts: Sequence[Mapping[str, Any]],
    similarity: Optional[Similarity] = None,
    params: Optional[Mapping[str, Any]] = None,
) -> VerifierResult:
    p = params or {}
    sim = similarity or (lambda a, b: ngram_similarity(a, b, int(p.get("ngram_size", 3))))
    floor = float(p.get("similarity_floor", 0.15))
    flag = float(p.get("field_flag_similarity", 0.4))
    if not contrasts:
        return VerifierResult("genericity", 1.0, [], skipped=True)
    entity = candidate["entity"]

    def as_text(c: Mapping[str, Any]) -> str:
        return "\n".join([c.get("name", ""), c.get("summary", "")] + list(c.get("facts", [])))

    whole = [(sim(entity_text(entity), as_text(c)), c) for c in contrasts]
    best, best_c = max(whole, key=lambda t: t[0])
    penalty = _penalty_from_similarity(best, floor)
    deductions: List[Deduction] = []
    if penalty > 0:
        pool = [c.get("summary", "") for c in contrasts] + \
               [t for c in contrasts for t in c.get("facts", [])]
        fields = [("name", entity.get("name", "")),
                  ("summary", entity.get("summary", ""))]
        fields += [(f"facts[{i}]", f.get("text", ""))
                   for i, f in enumerate(entity.get("facts") or [])]
        for fname, text in fields:
            if not text:
                continue
            ref = [c.get("name", "") for c in contrasts] if fname == "name" else pool
            s = max((sim(text, r) for r in ref if r), default=0.0)
            if s >= flag:
                deductions.append(Deduction(
                    "genericity", fname, "resembles_prior",
                    "close to what the model writes for this slot without "
                    "any input; make it specific to this world",
                    _penalty_from_similarity(s, floor), {"similarity": round(s, 4)}))
        if not deductions:
            deductions.append(Deduction(
                "genericity", "entity", "resembles_prior",
                "overall close to the no-input contrast candidate",
                penalty, {"similarity": round(best, 4),
                          "contrast_name": best_c.get("name", "")}))
    return VerifierResult("genericity", 1.0 - penalty, deductions)


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


def verify_specificity(
    candidate: Mapping[str, Any], language: str,
    rules: Mapping[str, Any], params: Optional[Mapping[str, Any]] = None,
) -> VerifierResult:
    p = params or {}
    pen = p.get("penalties", {})
    entity = candidate["entity"]
    facts = [f for f in entity.get("facts") or [] if isinstance(f, Mapping)]
    d: List[Deduction] = []
    if not facts:
        d.append(Deduction("specificity", "facts", "no_facts",
                           "no concrete facts at all",
                           float(pen.get("no_facts", 0.6))))
    else:
        kinds = {f.get("kind") for f in facts} - {"other", None}
        need = max(1, int(p.get("min_fact_kinds", 3)))
        if len(kinds) < need:
            d.append(Deduction(
                "specificity", "facts", "kind_coverage",
                f"facts cover {len(kinds)} kind(s); add more of: proper_noun, "
                "number, period, procedure, object, expression",
                float(pen.get("kind_coverage", 0.4)) * (1 - len(kinds) / need),
                {"kinds": sorted(kinds)}))
        nouns = sum(1 for f in facts if f.get("kind") == "proper_noun")
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
    words = rules_for(rules, language).get("abstract_words") or []
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
    return VerifierResult("specificity", _score(d), d)


_NUM = re.compile(r"\d+")


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
        d.append(Deduction("consistency", fld, code, msg,
                           float(pen.get(code, 0.4)), detail))

    for err in validate_candidate(graph, candidate, axes, brief):
        add("entity", "graph_invalid", err)

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
    d = []
    if penalty > 0:
        d.append(Deduction(
            "novelty", "summary", "duplicate",
            f"substantially duplicates existing entity {best_id}",
            penalty, {"similarity": round(best, 4), "entity": best_id}))
    return VerifierResult("novelty", 1.0 - penalty, d)


# --------------------------------------------------------------- LLM judge

class LLMJudge:
    """Optional LLM judge.  Sees one candidate and, for consistency, only
    its bounded local context.  Returns ``None`` when the model fails."""

    def __init__(self, backend: Any, prompts: Optional[Mapping[str, Any]] = None,
                 context_limits: Optional[Mapping[str, int]] = None) -> None:
        self.backend = backend
        self.prompts = dict(prompts) if prompts else yaml.safe_load(
            DEFAULT_VERIFIER_PROMPTS.read_text(encoding="utf-8"))
        self.context_limits = context_limits

    def judge(self, criterion: str, candidate: Mapping[str, Any],
              graph: Mapping[str, Any]) -> Optional[List[Deduction]]:
        entity = candidate["entity"]
        context: Any = "(none)"
        if criterion == "consistency" and candidate.get("target") \
                and get_entity(graph, candidate["target"]):
            context = local_context(graph, candidate["target"], self.context_limits)
        view = {"name": entity.get("name"), "summary": entity.get("summary"),
                "facts": [{"kind": f.get("kind"), "text": f.get("text")}
                          for f in entity.get("facts") or []]}
        prompt = self.prompts["common"]["user"].format(
            language=language_of(graph), criterion=self.prompts["criteria"][criterion].strip(),
            candidate=json.dumps(view, ensure_ascii=False),
            context=json.dumps(context, ensure_ascii=False, separators=(",", ":")))
        resp = self.backend.generate_json(
            prompt, system_prompt=self.prompts["common"]["system"])
        if not isinstance(resp, Mapping):
            return None
        try:
            score = _clamp(float(resp["score"]))
        except (KeyError, TypeError, ValueError):
            return None
        issues = [i for i in resp.get("issues") or [] if isinstance(i, Mapping)]
        if score >= 1.0:
            return []
        share = (1.0 - score) / max(1, len(issues))
        out = [Deduction(criterion, str(i.get("field") or "entity"), "llm_judge",
                         str(i.get("why") or "judged below standard"), share)
               for i in issues]
        return out or [Deduction(criterion, "entity", "llm_judge",
                                 "judged below standard", 1.0 - score)]


__all__ = [
    "ContrastProvider", "Deduction", "LLMJudge", "Similarity", "VerifierResult",
    "embedding_similarity", "entity_text", "language_of", "load_language_rules",
    "ngram_similarity", "rules_for", "verify_consistency", "verify_genericity",
    "verify_novelty", "verify_objectivity", "verify_provenance",
    "verify_specificity",
]
