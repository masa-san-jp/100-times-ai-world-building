"""Render a world package as reference material (Markdown and ``world.json``).

Everything here is deterministic template code: no model is called and no
prose is composed beyond what the world model already contains.  Output goes
to ``<package>/final/``::

    world.json                 machine-readable model + axes + run summary
    world_report.md            exploration results
    world_bible/README.md      overview, axes, contents
    world_bible/scales/<s>.md  one index per scale, top-down navigation
    world_bible/entities/<id>.md  one page per entity
    world_bible/glossary.md    proper-noun index
    world_bible/timeline.md    events / dated facts and their traces
    world_bible/documents.md   in-world documents

Headings come from ``config/world/render_labels.yaml`` keyed by
``meta.language`` (fallback ``en``).  Inputs are read from the package files
written by the exploration engine.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import yaml
from .premises import premise_extensions, world_premises
from .world_criteria import axis_counts, load_world_criteria_config, world_status

from .graph import (
    SCALES, SCALE_RANK, canonical, validate_graph,
)

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
DEFAULT_LABELS_PATH = CONFIG_DIR / "world" / "render_labels.yaml"
FALLBACK_LANGUAGE = "en"

FINAL_DIR = "final"
BIBLE_DIR = "world_bible"
WORLD_JSON_SCHEMA = 1

HISTOGRAM_BINS = 5
MAX_DISCARDED_EXAMPLES = 5
SUMMARY_EXCERPT_CHARS = 160


class RenderError(ValueError):
    """Raised when a package cannot be rendered."""


# ------------------------------------------------------------------ labels

def load_labels(
    language: Optional[str], path: Union[str, Path, None] = None,
) -> Dict[str, Any]:
    """Labels for ``language``; missing keys fall back to ``en``."""
    data = yaml.safe_load(
        Path(path or DEFAULT_LABELS_PATH).read_text(encoding="utf-8")) or {}
    base = data.get(FALLBACK_LANGUAGE)
    if not isinstance(base, Mapping):
        raise RenderError("render labels must define the fallback language")
    lang = (language or "").strip().lower().replace("_", "-")
    chosen = data.get(lang) or data.get(lang.split("-")[0]) or {}
    return _merge(base, chosen)


def _merge(base: Mapping[str, Any], over: Mapping[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), Mapping):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


# ----------------------------------------------------------------- helpers

def _one_line(text: Any) -> str:
    if text is None:
        text = ""
    return re.sub(r"\s+", " ", str(text)).strip()


def _unit_descriptions(units: Sequence[Any]) -> str:
    return ", ".join(
        f"{_one_line(unit['symbol'])} ({_one_line(unit['quantity'])})"
        if isinstance(unit, Mapping) else _one_line(unit)
        for unit in units)


def _institution_descriptions(institutions: Sequence[Any]) -> str:
    return ", ".join(
        f"{_one_line(institution['name'])} ({_one_line(institution['description'])})"
        if isinstance(institution, Mapping) else _one_line(institution)
        for institution in institutions)


def _esc(text: Any) -> str:
    """Escape text for use inside link text and table cells."""
    t = _one_line(text)
    for ch in ("\\", "[", "]", "|"):
        t = t.replace(ch, "\\" + ch)
    return t


def _excerpt(text: str, limit: int = SUMMARY_EXCERPT_CHARS) -> str:
    t = _one_line(text)
    return t if len(t) <= limit else t[: limit - 1] + "…"


def _id_key(entity_id: str) -> Tuple[int, int, str]:
    m = re.fullmatch(r"e(\d+)", entity_id)
    return (0, int(m.group(1)), "") if m else (1, 0, entity_id)


def _file_name(entity_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", entity_id) + ".md"


def _blockquote(text: str) -> str:
    return "> " + _one_line(text)


class _Ctx:
    """Everything the page builders share."""

    def __init__(self, graph, axes, brief, labels, run, coverage, prefs):
        self.graph = graph
        self.labels = labels
        self.axes = list(axes)
        self.run = run
        self.coverage = coverage
        self.prefs = prefs
        self.entities = sorted(
            graph["entities"], key=lambda e: _id_key(e["id"]))
        self.by_id = {e["id"]: e for e in self.entities}
        self.statements = {
            s["id"]: s for s in (brief or {}).get("statements", []) or []
            if isinstance(s, Mapping) and s.get("id")}
        self.axis_by_id = {a["id"]: a for a in self.axes}
        self.children: Dict[str, List[str]] = {}
        self.incoming: Dict[str, List[Tuple[str, str]]] = {}
        for e in self.entities:
            if e.get("parent"):
                self.children.setdefault(e["parent"], []).append(e["id"])
            for r in e.get("relations", []):
                self.incoming.setdefault(r["target"], []).append(
                    (e["id"], r["type"]))

    def label(self, key: str, **kw: Any) -> str:
        value = self.labels.get(key, key)
        return value.format(**kw) if kw and isinstance(value, str) else value

    def sub(self, group: str, key: str) -> str:
        return str((self.labels.get(group) or {}).get(key, key))

    def link(self, entity_id: str, from_dir: str = "entities") -> str:
        """Markdown link to an entity page, relative to ``from_dir``."""
        e = self.by_id[entity_id]
        prefix = {"entities": "", "scales": "../entities/"}.get(
            from_dir, "entities/")
        return f"[{_esc(e['name'])}]({prefix}{_file_name(entity_id)})"

    def axis_name(self, axis_id: str) -> str:
        a = self.axis_by_id.get(axis_id)
        return a["name"] if a and a.get("name") else axis_id


# --------------------------------------------------------------- the pages

def _entity_page(ctx: _Ctx, e: Mapping[str, Any]) -> str:
    L = ctx.label
    eid = e["id"]
    out: List[str] = [f"# {_one_line(e['name'])}", ""]
    nav = [f"[{L('readme_title')}](../README.md)",
           f"[{ctx.sub('scales', e['scale'])}](../scales/{e['scale']}.md)"]
    if e.get("parent"):
        nav.insert(1, f"{L('up')}: {ctx.link(e['parent'])}")
    out += [" / ".join(nav), ""]
    out += [f"## {L('attributes')}", "",
            f"- {L('type')}: {ctx.sub('types', e['type'])}",
            f"- {L('scale')}: {ctx.sub('scales', e['scale'])}"]
    if e.get("axes"):
        out.append(f"- {L('axes_of_entity')}: "
                   + ", ".join(_esc(ctx.axis_name(a)) for a in e["axes"]))
    out.append("")
    out += [f"## {L('summary')}", "", _one_line(e.get("summary")) or "-", ""]
    out += [f"## {L('facts')}", ""]
    facts = e.get("facts") or []
    if facts:
        out += [f"- [{ctx.sub('fact_kinds', f['kind'])}] "
                f"{_one_line(f['text'])}" for f in facts]
    else:
        out.append(L("no_facts"))
    out.append("")

    contract = e.get("world_premises")
    if contract:
        calendar, technology = contract["calendar"], contract["technology"]
        out += [f"## {L('world_premises')}", "",
                f"- {L('calendar')}: {_one_line(calendar['name'])}",
                f"- {L('calendar_origin')}: {_one_line(calendar['origin'])}",
                f"- {L('calendar_markers')}: " + ", ".join(calendar['markers']),
                f"- {L('technology')}: {_one_line(technology['description'])}",
                f"- {L('capabilities')}: " + ", ".join(technology['capabilities']),
                f"- {L('units')}: " + _unit_descriptions(technology['units']), ""]
        if contract.get("society"):
            society = contract["society"]
            out += [f"- {L('society')}: {_one_line(society['description'])}",
                    f"- {L('institutions')}: " + _institution_descriptions(society['institutions']), ""]

    out += [f"## {L('relations')}", ""]
    rels = [f"- {ctx.sub('relation_types', r['type'])}: {ctx.link(r['target'])}"
            for r in e.get("relations", [])]
    out += rels or [f"- {L('none')}"]
    inc = sorted({(s, t) for s, t in ctx.incoming.get(eid, [])},
                 key=lambda p: (_id_key(p[0]), p[1]))
    if inc:
        out += ["", f"### {L('referenced_by')}", ""]
        out += [f"- {ctx.link(s)} ({ctx.sub('relation_types', t)})"
                for s, t in inc]
    out.append("")

    out += [f"## {L('hierarchy')}", "",
            f"- {L('parent')}: "
            + (ctx.link(e["parent"]) if e.get("parent") else L("none")),
            f"- {L('children')}: "
            + (", ".join(ctx.link(c) for c in ctx.children.get(eid, []))
               or L("none")), ""]

    prov = e.get("provenance") or {}
    out += [f"## {L('provenance')}", ""]
    sids = prov.get("statement_ids") or []
    if sids:
        out += [f"### {L('source_statements')}", ""]
        for s in sids:
            st = ctx.statements.get(s)
            quote = (st or {}).get("quote") or (st or {}).get("text") or ""
            out.append(f"- `{s}`")
            if quote:
                out.append(f"  {_blockquote(quote)}")
        out.append("")
    srcs = prov.get("derived_from") or []
    if srcs:
        out += [f"### {L('derived_from')}", ""]
        out += [f"- {ctx.link(s)}" for s in srcs]
        out.append("")
    reason = _one_line(prov.get("reason"))
    if reason:
        out += [f"### {L('reason')}", "", reason, ""]
    return "\n".join(out).rstrip() + "\n"


def _scale_page(ctx: _Ctx, scale: str) -> str:
    L = ctx.label
    items = [e for e in ctx.entities if e["scale"] == scale]
    rank = SCALE_RANK[scale]
    out = [f"# {L('scale_page_title', scale=ctx.sub('scales', scale))}", ""]
    nav = [f"[{L('readme_title')}](../README.md)"]
    if rank > 0:
        p = SCALES[rank - 1]
        nav.append(f"{L('prev_scale')}: "
                   f"[{ctx.sub('scales', p)}]({p}.md)")
    if rank < len(SCALES) - 1:
        n = SCALES[rank + 1]
        nav.append(f"{L('next_scale')}: "
                   f"[{ctx.sub('scales', n)}]({n}.md)")
    out += [" / ".join(nav), "", L("entity_count", n=len(items)), ""]
    groups: Dict[Optional[str], List[Mapping[str, Any]]] = {}
    for e in items:
        groups.setdefault(e.get("parent"), []).append(e)
    order = sorted(groups, key=lambda p: (p is not None, _id_key(p or "")))
    for parent in order:
        if parent is None:
            out += [f"## {L('entities_top')}", ""]
        else:
            out += [f"## {L('entities_under', parent=ctx.link(parent, 'scales'))}",
                    ""]
        for e in groups[parent]:
            line = f"- {ctx.link(e['id'], 'scales')} "
            line += f"({ctx.sub('types', e['type'])})"
            if e.get("summary"):
                line += f": {_excerpt(e['summary'])}"
            out.append(line)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _glossary_page(ctx: _Ctx) -> str:
    L = ctx.label
    terms: Dict[str, Dict[str, Any]] = {}

    def add(term: str, eid: str, kind: str) -> None:
        term = _one_line(term)
        if not term:
            return
        slot = terms.setdefault(term, {"refs": {}})
        slot["refs"].setdefault(eid, kind)
        if kind == "glossary_name":
            slot["refs"][eid] = kind

    for e in ctx.entities:
        add(e["name"], e["id"], "glossary_name")
        for f in e.get("facts", []):
            if f.get("kind") == "proper_noun":
                add(f["text"], e["id"], "glossary_fact")
    out = [f"# {L('glossary')}", "",
           f"[{L('readme_title')}](README.md)", "", L("glossary_intro"), ""]
    for term in sorted(terms, key=lambda t: (t.casefold(), t)):
        refs = terms[term]["refs"]
        links = ", ".join(
            f"{ctx.link(i, 'bible')} ({L(refs[i])})"
            for i in sorted(refs, key=_id_key))
        out.append(f"- **{_esc(term)}**: {links}")
    return "\n".join(out).rstrip() + "\n"


def _timeline_page(ctx: _Ctx) -> str:
    L = ctx.label
    out = [f"# {L('timeline')}", "",
           f"[{L('readme_title')}](README.md)", "", L("timeline_intro"), ""]
    events = [e for e in ctx.entities if e["type"] == "event"]
    dated = [e for e in ctx.entities if e["type"] != "event"
             and any(f.get("kind") == "period" for f in e.get("facts", []))]
    if not events and not dated:
        out.append(L("timeline_empty"))
    if events:
        out += [f"## {L('timeline_events')}", ""]
        for e in events:
            periods = [_one_line(f["text"]) for f in e.get("facts", [])
                       if f.get("kind") == "period"]
            head = f"- {ctx.link(e['id'], 'bible')}"
            if periods:
                head += ": " + "; ".join(periods)
            out.append(head)
            traces = [r["target"] for r in e.get("relations", [])
                      if r["type"] in ("affects", "causes")]
            traces += [s for s, t in ctx.incoming.get(e["id"], [])
                       if t == "derived_from"]
            traces = [t for t in dict.fromkeys(traces) if t != e["id"]]
            if traces:
                out.append(f"  - {L('timeline_traces')}: "
                           + ", ".join(ctx.link(t, "bible") for t in traces))
        out.append("")
    if dated:
        out += [f"## {L('timeline_periods')}", ""]
        for e in dated:
            periods = "; ".join(_one_line(f["text"]) for f in e["facts"]
                                if f.get("kind") == "period")
            out.append(f"- {ctx.link(e['id'], 'bible')}: {periods}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _documents_page(ctx: _Ctx) -> str:
    L = ctx.label
    out = [f"# {L('documents')}", "",
           f"[{L('readme_title')}](README.md)", "", L("documents_intro"), ""]
    docs = [e for e in ctx.entities if e["type"] == "document"]
    if not docs:
        out.append(L("documents_empty"))
    for e in docs:
        out += [f"## {_one_line(e['name'])}", "",
                f"[{L('readme_title')}](README.md) / "
                f"{ctx.link(e['id'], 'bible')}", "",
                _one_line(e.get("summary")), ""]
        issuers = [s for s, t in ctx.incoming.get(e["id"], [])
                   if t in ("produces", "governs")]
        issuers += [r["target"] for r in e.get("relations", [])
                    if r["type"] == "derived_from"]
        if e.get("parent"):
            issuers.append(e["parent"])
        issuers = list(dict.fromkeys(issuers))
        if issuers:
            out.append(f"- {L('document_issuer')}: "
                       + ", ".join(ctx.link(i, "bible") for i in issuers))
        targets = [r["target"] for r in e.get("relations", [])
                   if r["type"] == "related_to"]
        if targets:
            out.append(f"- {L('document_target')}: "
                       + ", ".join(ctx.link(i, "bible") for i in targets))
        out += ["", f"### {L('document_facts')}", ""]
        out += [f"- [{ctx.sub('fact_kinds', f['kind'])}] "
                f"{_one_line(f['text'])}" for f in e.get("facts", [])] \
            or [L("no_facts")]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> List[str]:
    lines = ["| " + " | ".join(_esc(h) for h in header) + " |",
             "|" + "|".join(" --- " for _ in header) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(_esc(c) for c in r) + " |")
    return lines


def _readme(ctx: _Ctx) -> str:
    L = ctx.label
    out = [f"# {L('readme_title')}", "", f"## {L('overview')}", ""]
    roots = [e for e in ctx.entities if e["scale"] == "world"]
    if roots:
        for e in roots:
            out += [f"### {ctx.link(e['id'], 'bible')}", "",
                    _one_line(e.get("summary")), ""]
    else:
        out += [L("overview_empty"), ""]
    out += [L("overview_counts", entities=len(ctx.entities),
              axes=len(ctx.axes)), ""]

    out += [f"## {L('axes')}", "", L("axes_intro"), ""]
    rows = []
    for a in sorted(ctx.axes, key=lambda a: (-float(a.get("weight") or 0),
                                              str(a["id"]))):
        g = a.get("grounds") or {}
        sids = g.get("statement_ids") or []
        parts = []
        for s in sids:
            st = ctx.statements.get(s)
            q = (st or {}).get("quote") or (st or {}).get("text")
            parts.append(f"{s}: {_excerpt(q, 80)}" if q else s)
        if g.get("reason"):
            parts.append(_one_line(g["reason"]))
        grounds = " / ".join(parts) or L("no_grounds")
        name = a.get("name") or a["id"]
        if a.get("origin") == "added":
            name = f"{name} ({L('axis_origin_added')})"
        rows.append([name, f"{float(a.get('weight') or 0):.2f}",
                     a.get("meaning") or "", grounds])
    out += _table(L("axis_columns"), rows)
    out.append("")

    out += [f"## {L('contents')}", "", f"### {L('scales_by_scale')}", ""]
    for s in SCALES:
        n = sum(1 for e in ctx.entities if e["scale"] == s)
        out.append(f"- [{ctx.sub('scales', s)}](scales/{s}.md) "
                   f"({L('entity_count', n=n)})")
    out += ["", f"- [{L('glossary')}](glossary.md)",
            f"- [{L('timeline')}](timeline.md)",
            f"- [{L('documents')}](documents.md)",
            f"- [{L('report')}](../world_report.md)", ""]
    return "\n".join(out).rstrip() + "\n"


# ------------------------------------------------------------------ report

def _stats(values: Sequence[float]) -> Tuple[int, float, float, float]:
    return (len(values), sum(values) / len(values), min(values), max(values))


def _discarded_examples(ctx: _Ctx, limit: int) -> List[Dict[str, Any]]:
    rows = []
    for r in ctx.prefs:
        if r.get("type") != "candidate" or r.get("decision") != "rejected":
            continue
        res = r.get("result") or {}
        ded = [d for d in res.get("deductions", [])
               if d.get("verifier") == "genericity"]
        score = (res.get("scores") or {}).get("genericity")
        if "genericity" not in (res.get("failed") or []) and not (
                ded and isinstance(score, (int, float))):
            continue
        rows.append((float(score) if isinstance(score, (int, float)) else 1.0,
                     str(r.get("id")), r, ded))
    rows.sort(key=lambda t: (t[0], t[1]))
    return [{"score": s, "id": i, "record": r, "deductions": d}
            for s, i, r, d in rows[:limit]]


def _report(ctx: _Ctx, limit: int) -> str:
    L = ctx.label
    run = ctx.run
    counters = run.get("counters") or {}
    out = [f"# {L('report_title')}", "",
           f"[{L('readme_title')}]({BIBLE_DIR}/README.md)", "",
           f"## {L('run_summary')}", ""]
    models = run.get("models") or {}
    if models.get("generation"):
        out.append(f"- {L('generation_model')}: {models['generation']}")
    if models.get("judge"):
        out.append(f"- {L('judge_model')}: {models['judge']}")
    stop = run.get("stop_reason")
    out.append(f"- {L('stop_reason')}: "
               + (ctx.sub("stop_reasons", stop) if stop else L("none")))
    out.append(f"- {L('iterations')}: {run.get('iterations', 0)}")
    out.append(f"- {L('generation_calls')}: "
               f"{counters.get('generation_calls', 0)}")
    out.append(f"- {L('accepted')}: {counters.get('accepted', 0)}")
    out.append(f"- {L('rejected')}: {counters.get('rejected', 0)}")
    out.append("")

    from .structured import metrics_markdown
    if run.get("structured"):
        out.append(metrics_markdown(run["structured"]))

    if run.get("build"):
        from .builder import build_metrics_markdown
        out.append(build_metrics_markdown(run["build"]))

    stage = ctx.graph.get("contract_stage")
    if stage:
        out += [f"## {L('contract_stage')}", "",
                f"- {L('contract_status')}: {stage['status']}",
                f"- {L('contract_attempts')}: {stage['attempts']}"]
        if not stage.get("checks_enabled", True):
            out.append(L("contract_disabled"))
        for attempt in stage.get("errors", []):
            if attempt.get("errors"):
                out.append(f"- {attempt['attempt']}: " + " / ".join(_one_line(e) for e in attempt["errors"]))
        out.append("")
        from .contract import contract_metrics_markdown
        if stage.get("steps"):
            out.append(contract_metrics_markdown(stage))
        contract = world_premises(ctx.graph)
        if contract:
            calendar, technology = contract["calendar"], contract["technology"]
            out += [f"- {L('calendar')}: {_one_line(calendar['name'])}",
                    f"- {L('calendar_origin')}: {_one_line(calendar['origin'])}",
                    f"- {L('calendar_markers')}: " + ", ".join(calendar['markers']),
                    f"- {L('technology')}: {_one_line(technology['description'])}",
                    f"- {L('capabilities')}: " + ", ".join(technology['capabilities']),
                    f"- {L('units')}: " + _unit_descriptions(technology['units'])]
            if contract.get("society"):
                out += [f"- {L('society')}: {_one_line(contract['society']['description'])}",
                        f"- {L('institutions')}: " + _institution_descriptions(contract['society']['institutions'])]
            out.append("")

    cov = ctx.coverage
    out += [f"## {L('purpose_achievement')}", "",
            f"- {L('coverage_state')}: "
            + (L("met") if cov.get("met") else L("not_met")), ""]
    out += _table(L("criteria_columns"), [
        [ctx.sub("world_criteria", metric),
         row["value"] if row["value"] is not None else L("none"),
         row["threshold"], L("met") if row["met"] else L("not_met")]
        for metric, row in cov["criteria"].items()]) + [""]
    out += [f"### {L('coverage_axes')}", ""]
    weights = {a["id"]: float(a.get("weight") or 0) for a in ctx.axes}
    total_w = sum(weights.values())
    used = axis_counts(ctx.graph, ctx.axes)
    total_used = sum(used.values())
    rows = []
    for a in sorted(ctx.axes, key=lambda a: str(a["id"])):
        w = weights[a["id"]]
        share = (w / total_w) if total_w > 0 else 1.0 / max(1, len(weights))
        n = used.get(a["id"], 0)
        rows.append([a.get("name") or a["id"], f"{w:.2f}", f"{share:.1%}", n,
                     f"{(n / total_used if total_used else 0.0):.1%}"])
    out += _table(L("coverage_columns"), rows) + [""]

    out += [f"## {L('scale_counts')}", ""]
    counts = {s: 0 for s in SCALES}
    for e in ctx.entities:
        counts[e["scale"]] += 1
    out += _table(L("scale_columns"),
                  [[ctx.sub("scales", s), counts[s]] for s in SCALES]
                  + [[L("total"), len(ctx.entities)]]) + [""]

    out += [f"## {L('reward_distribution')}", ""]
    by_name: Dict[str, List[float]] = {}
    for e in ctx.entities:
        for k, v in (e.get("scores") or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                by_name.setdefault(k, []).append(float(v))
    rows = []
    for k in sorted(k for k in by_name if k != "reward"):
        n, mean, lo, hi = _stats(by_name[k])
        rows.append([k, n, f"{mean:.3f}", f"{lo:.3f}", f"{hi:.3f}"])
    if "reward" in by_name:
        n, mean, lo, hi = _stats(by_name["reward"])
        rows.append([L("reward_total"), n, f"{mean:.3f}", f"{lo:.3f}",
                     f"{hi:.3f}"])
    if rows:
        out += _table(L("reward_columns"), rows) + [""]
    if by_name.get("reward"):
        bins = [0] * HISTOGRAM_BINS
        for v in by_name["reward"]:
            bins[min(HISTOGRAM_BINS - 1,
                     max(0, int(v * HISTOGRAM_BINS)))] += 1
        out += [f"### {L('reward_histogram')}", ""]
        for i, c in enumerate(bins):
            lo, hi = i / HISTOGRAM_BINS, (i + 1) / HISTOGRAM_BINS
            out.append(f"- {lo:.1f} - {hi:.1f}: {c}")
        out.append("")

    out += [f"## {L('discarded')}", ""]
    examples = _discarded_examples(ctx, limit)
    if not examples:
        out += [L("discarded_empty"), ""]
    for ex in examples:
        cand = ex["record"].get("candidate") or {}
        out += [f"### {_one_line(cand.get('name')) or ex['id']}", "",
                _excerpt(cand.get("summary") or ""), "",
                f"- {L('discarded_score')}: {ex['score']:.3f}"]
        reasons = [_one_line(d.get("message")) for d in ex["deductions"][:3]
                   if d.get("message")]
        if reasons:
            out.append(f"- {L('discarded_reasons')}: " + " / ".join(reasons))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------- the entry

def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def render_world_package(
    package_dir: Union[str, Path], *,
    run_summary: Optional[Mapping[str, Any]] = None,
    labels_path: Union[str, Path, None] = None,
    explore_config: Optional[Mapping[str, Any]] = None,
    max_discarded_examples: int = MAX_DISCARDED_EXAMPLES,
) -> Dict[str, Path]:
    """Write ``final/`` for the package and return the main file paths.

    Reads ``world/graph.json``, ``world/world_axes.json``,
    ``input/input_brief.json``, ``world/preferences.jsonl`` and (for the run
    summary, unless ``run_summary`` is given) ``run_manifest.json``.  The same
    inputs always produce byte-identical files.
    """
    root = Path(package_dir)
    graph = _read_json(root / "world" / "graph.json", None)
    if graph is None:
        raise RenderError(f"missing or unreadable {root / 'world/graph.json'}")
    errors = validate_graph(graph)
    if errors:
        raise RenderError("invalid graph: " + "; ".join(errors[:5]))
    axes = (_read_json(root / "world" / "world_axes.json", {}) or {}) \
        .get("axes", [])
    brief = _read_json(root / "input" / "input_brief.json", {})
    prefs = _read_jsonl(root / "world" / "preferences.jsonl")

    if run_summary is None:
        manifest = _read_json(root / "run_manifest.json", {}) or {}
        stored = manifest.get("world_explore") or {}
        run_summary = {
            "stop_reason": stored.get("stop_reason"),
            "iterations": stored.get("iteration", 0),
            "counters": stored.get("counters") or {},
            "structured": manifest.get("structured", {}),
            "build": manifest.get("build", {}),
            "models": {"generation": manifest.get("model"),
                       "judge": manifest.get("judge_model")}}
    run = {"models": dict(run_summary.get("models") or {}), "build": run_summary.get("build", {}), "structured": run_summary.get("structured", {}), "stop_reason": run_summary.get("stop_reason"),
           "iterations": int(run_summary.get("iterations") or 0),
           "counters": {k: int(v) for k, v in sorted(
               (run_summary.get("counters") or {}).items())}}

    coverage = world_status(graph, axes, brief, world_premises(graph),
                            load_world_criteria_config())
    labels = load_labels(graph["meta"]["language"], labels_path)
    ctx = _Ctx(graph, axes, brief, labels, run, coverage, prefs)

    final = root / FINAL_DIR
    bible = final / BIBLE_DIR
    if bible.exists():
        shutil.rmtree(bible)  # generated tree: drop stale pages
    model = canonical(graph)
    model["axes"] = axes
    model["run"] = {**run, "coverage": coverage}
    model["premise_extensions"] = premise_extensions(graph)
    _write(final / "world.json", json.dumps(
        model, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _write(bible / "README.md", _readme(ctx))
    for s in SCALES:
        _write(bible / "scales" / f"{s}.md", _scale_page(ctx, s))
    for e in ctx.entities:
        _write(bible / "entities" / _file_name(e["id"]), _entity_page(ctx, e))
    _write(bible / "glossary.md", _glossary_page(ctx))
    _write(bible / "timeline.md", _timeline_page(ctx))
    _write(bible / "documents.md", _documents_page(ctx))
    _write(final / "world_report.md", _report(ctx, max_discarded_examples))
    return {"world_json": final / "world.json", "bible": bible,
            "report": final / "world_report.md"}


__all__ = [
    "DEFAULT_LABELS_PATH", "RenderError", "load_labels",
    "render_world_package",
]
