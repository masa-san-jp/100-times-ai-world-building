"""Quality checks for one generated world package.

The report reads the package the engine wrote (``world/graph.json``,
``world/world_axes.json``, ``world/preferences.jsonl``, ``run_manifest.json``)
and judges the world on the properties the engine is meant to deliver: axis
coverage, scale depth, reward distribution, genericity, provenance and
internal duplication.  It never calls a model and never blocks generation.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import (
    Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple,
)

import yaml

from .world.graph import SCALE_RANK, SCALES, validate_graph
from .world.textsim import (  # noqa: F401  (re-exported for callers)
    _item_text, character_ngrams, jaccard, normalize_item,
)
from .world.verify import entity_text

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
DEFAULT_QUALITY_PATH = CONFIG_DIR / "world" / "quality.yaml"
HISTOGRAM_BINS = 5


# ------------------------------------------------------------- text helpers

def analyze_duplicates(
    items: Sequence[Any], threshold: float = 0.8,
) -> Dict[str, Any]:
    """Exact, normalized and character 3-gram duplicate metrics for texts."""
    values = [_item_text(i) for i in items]
    normalized = [normalize_item(i) for i in values]
    grams = [character_ngrams(n) for n in normalized]
    near = 0
    for i, left in enumerate(normalized):
        if not grams[i]:
            continue
        for j in range(i + 1, len(normalized)):
            if left != normalized[j] and grams[j] \
                    and jaccard(grams[i], grams[j]) >= threshold:
                near += 1
    return {
        "item_count": len(values),
        "exact_duplicate_count": len(values) - len(set(values)),
        "normalized_duplicate_count": len(values) - len(set(normalized)),
        "near_duplicate_pair_count": near,
    }


# ------------------------------------------------------------------ loading

def _read_json(path: Path, default: Any = None) -> Any:
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


def get_quality_config(
    config: Optional[Mapping[str, Any]] = None, path: Any = None,
) -> Dict[str, Any]:
    """Load ``config/world/quality.yaml`` and merge ``config`` over it."""
    cfg = yaml.safe_load(
        Path(path or DEFAULT_QUALITY_PATH).read_text(encoding="utf-8")) or {}
    cfg.update(copy.deepcopy(dict(config or {})))
    if not 0.0 <= float(cfg["near_duplicate_threshold"]) <= 1.0:
        raise ValueError("near_duplicate_threshold must be between 0 and 1")
    if cfg["min_depth_scale"] not in SCALE_RANK:
        raise ValueError(f"min_depth_scale must be one of {list(SCALES)}")
    return cfg


def load_world_package(world_dir: Any) -> Dict[str, Any]:
    """Read the parts of a world package the reports need."""
    root = Path(world_dir)
    if not root.is_dir():
        raise ValueError(f"World directory does not exist: {root}")
    graph = _read_json(root / "world" / "graph.json")
    if not isinstance(graph, dict):
        raise ValueError(f"Not a world package (no world/graph.json): {root}")
    axes = (_read_json(root / "world" / "world_axes.json", {}) or {}) \
        .get("axes", [])
    return {
        "root": root, "graph": graph, "axes": axes,
        "manifest": _read_json(root / "run_manifest.json", {}) or {},
        "prefs": _read_jsonl(root / "world" / "preferences.jsonl"),
    }


def entities_of(graph: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return [e for e in graph.get("entities", []) if isinstance(e, Mapping)]


def _status_rank(status: str) -> int:
    return {"pass": 0, "warn": 1, "fail": 2}[status]


def _worst_status(statuses: Iterable[str]) -> str:
    return max(statuses, key=_status_rank, default="pass")


def _num(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) \
        and not isinstance(value, bool) else None


def _stats(values: Sequence[float]) -> Dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "min": None, "max": None}
    return {"count": len(values), "mean": round(sum(values) / len(values), 4),
            "min": round(min(values), 4), "max": round(max(values), 4)}


# ------------------------------------------------------------------- checks

def _graph_check(entities, graph, axes) -> Dict[str, Any]:
    errors = validate_graph(graph)
    status = "fail" if errors or not entities else "pass"
    out = {"status": status, "entity_count": len(entities),
           "errors": errors[:10], "error_count": len(errors)}
    if not entities:
        out["errors"] = ["the world has no entities"] + out["errors"]
    return out


def _axis_check(entities, axes, cfg) -> Dict[str, Any]:
    minimum = int(cfg["min_axis_entities"])
    counts = {a["id"]: 0 for a in axes}
    for e in entities:
        for a in set(e.get("axes") or []):
            if a in counts:
                counts[a] += 1
    total_w = sum(float(a.get("weight") or 0) for a in axes)
    used = sum(counts.values())
    rows = []
    for a in axes:
        w = float(a.get("weight") or 0)
        rows.append({
            "id": a["id"], "name": a.get("name") or a["id"],
            "weight": round(w, 4),
            "weight_share": round(w / total_w, 4) if total_w else 0.0,
            "entities": counts[a["id"]],
            "entity_share": round(counts[a["id"]] / used, 4) if used else 0.0})
    uncovered = [r["id"] for r in rows if r["entities"] < minimum]
    status = "warn" if uncovered or not axes else "pass"
    return {"status": status, "axis_count": len(axes),
            "min_axis_entities": minimum, "uncovered_axes": uncovered,
            "axes": rows}


def _scale_check(entities, cfg) -> Dict[str, Any]:
    counts = {s: 0 for s in SCALES}
    for e in entities:
        if e.get("scale") in counts:
            counts[e["scale"]] += 1
    reached = [s for s in SCALES if counts[s]]
    target = SCALE_RANK[cfg["min_depth_scale"]]
    need = int(cfg["min_entities_per_scale"])
    missing = [s for s in SCALES[: target + 1] if counts[s] < need]
    deepest = reached[-1] if reached else None
    if not entities:
        status = "fail"
    else:
        status = "warn" if missing else "pass"
    return {"status": status, "counts": counts, "deepest_scale": deepest,
            "target_scale": cfg["min_depth_scale"],
            "min_entities_per_scale": need, "missing_scales": missing}


def _reward_check(entities, cfg) -> Dict[str, Any]:
    rewards = [v for v in (_num((e.get("scores") or {}).get("reward"))
                           for e in entities) if v is not None]
    unscored = [e["id"] for e in entities
                if _num((e.get("scores") or {}).get("reward")) is None]
    by_verifier: Dict[str, List[float]] = {}
    for e in entities:
        for k, v in (e.get("scores") or {}).items():
            n = _num(v)
            if n is not None and k != "reward":
                by_verifier.setdefault(k, []).append(n)
    bins = [0] * HISTOGRAM_BINS
    for v in rewards:
        bins[min(HISTOGRAM_BINS - 1, max(0, int(v * HISTOGRAM_BINS)))] += 1
    low = [e["id"] for e, v in ((e, _num((e.get("scores") or {}).get("reward")))
                                for e in entities)
           if v is not None and v < float(cfg["low_reward_threshold"])]
    n = len(entities) or 1
    warnings = []
    stats = _stats(rewards)
    if stats["mean"] is not None and stats["mean"] < float(cfg["min_reward"]):
        warnings.append(f"mean reward {stats['mean']:.3f} is below "
                        f"{float(cfg['min_reward']):.2f}")
    if len(low) / n > float(cfg["max_low_reward_share"]):
        warnings.append(f"{len(low)} of {len(entities)} entities are "
                        "below the low-reward threshold")
    if len(unscored) / n > float(cfg["max_unscored_share"]):
        warnings.append(f"{len(unscored)} entities carry no reward")
    return {"status": "warn" if warnings else "pass", "reward": stats,
            "histogram": bins, "low_reward_entities": low,
            "unscored_entities": unscored,
            "verifiers": {k: _stats(v) for k, v in sorted(by_verifier.items())},
            "warnings": warnings}


def _genericity_check(entities, prefs, cfg) -> Dict[str, Any]:
    threshold = float(cfg["genericity_threshold"])
    scores = [(e["id"], _num((e.get("scores") or {}).get("genericity")))
              for e in entities]
    scored = [(i, v) for i, v in scores if v is not None]
    generic = [i for i, v in scored if v < threshold]
    rejected = [r for r in prefs if r.get("type") == "candidate"
                and r.get("decision") == "rejected"
                and "genericity" in ((r.get("result") or {}).get("failed")
                                     or [])]
    warnings = []
    if scored and len(generic) / len(scored) > float(cfg["max_generic_share"]):
        warnings.append(f"{len(generic)} of {len(scored)} scored entities "
                        "are close to the no-input contrast")
    return {"status": "warn" if warnings else "pass",
            "genericity": _stats([v for _, v in scored]),
            "threshold": threshold, "generic_entities": generic,
            "candidates_rejected_as_generic": len(rejected),
            "warnings": warnings}


def _provenance_check(entities) -> Dict[str, Any]:
    ungrounded = []
    for e in entities:
        p = e.get("provenance") or {}
        if not (p.get("statement_ids") or p.get("derived_from")
                or str(p.get("reason") or "").strip()):
            ungrounded.append(e["id"])
    return {"status": "warn" if ungrounded else "pass",
            "ungrounded_entities": ungrounded}


def _duplicate_check(entities, cfg) -> Dict[str, Any]:
    threshold = float(cfg["near_duplicate_threshold"])
    metrics = analyze_duplicates(
        [entity_text(e) for e in entities], threshold)
    names = analyze_duplicates([str(e.get("name") or "") for e in entities],
                               threshold)
    dup = (metrics["exact_duplicate_count"]
           + metrics["normalized_duplicate_count"]
           + metrics["near_duplicate_pair_count"]
           + names["normalized_duplicate_count"])
    return {"status": "warn" if dup else "pass", "threshold": threshold,
            "entities": metrics, "names": names}


def _exploration_check(manifest, prefs) -> Dict[str, Any]:
    explore = manifest.get("world_explore") or {}
    stop = manifest.get("stop_reason") or explore.get("stop_reason")
    counters = manifest.get("counters") or explore.get("counters") or {}
    status = "pass"
    notes = []
    if manifest.get("status") == "failed":
        status = "fail"
        notes.append(f"run failed: {manifest.get('error', 'unknown error')}")
    elif not stop:
        status = "warn"
        notes.append("no stop reason recorded (the run may be unfinished)")
    iterations = [r for r in prefs if r.get("type") == "iteration"]
    accepted = sum(1 for r in iterations if r.get("outcome") == "accepted")
    return {"status": status, "run_status": manifest.get("status"),
            "stop_reason": stop,
            "iterations": manifest.get("iterations",
                                       explore.get("iteration", 0)),
            "counters": counters, "logged_iterations": len(iterations),
            "accepted_iterations": accepted, "notes": notes}


def generate_quality_report(
    world_dir: Any, config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate a quality report for one world package (no external calls)."""
    pkg = load_world_package(world_dir)
    cfg = get_quality_config(config)
    ents = entities_of(pkg["graph"])
    checks = {
        "graph": _graph_check(ents, pkg["graph"], pkg["axes"]),
        "axis_coverage": _axis_check(ents, pkg["axes"], cfg),
        "scale_depth": _scale_check(ents, cfg),
        "reward_distribution": _reward_check(ents, cfg),
        "genericity": _genericity_check(ents, pkg["prefs"], cfg),
        "provenance": _provenance_check(ents),
        "duplicates": _duplicate_check(ents, cfg),
        "exploration": _exploration_check(pkg["manifest"], pkg["prefs"]),
    }
    status = _worst_status(c["status"] for c in checks.values())
    return {"world_dir": str(pkg["root"]), "status": status,
            "overall_status": status, "config": cfg, "checks": checks}


# ----------------------------------------------------------------- Markdown

def _fmt(value: Optional[float]) -> str:
    return "-" if value is None else f"{value:.3f}"


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact human-readable Markdown report."""
    c = report["checks"]
    lines = ["# Quality Report", "",
             f"- World: `{report['world_dir']}`",
             f"- Overall: **{str(report['status']).upper()}**", "",
             "## Summary", ""]
    for key, check in c.items():
        lines.append(f"- {key}: **{str(check['status']).upper()}**")

    g = c["graph"]
    lines += ["", "## 1. Graph", "", f"- Entities: {g['entity_count']}",
              f"- Validation errors: {g['error_count']}"]
    lines += [f"  - {e}" for e in g["errors"]]

    a = c["axis_coverage"]
    lines += ["", "## 2. Axis coverage", "",
              f"- Axes: {a['axis_count']} (each should own at least "
              f"{a['min_axis_entities']} entities)",
              f"- Uncovered: {', '.join(a['uncovered_axes']) or 'none'}", "",
              "| axis | weight share | entities | entity share |",
              "| --- | --- | --- | --- |"]
    for r in a["axes"]:
        lines.append(f"| {r['name']} | {r['weight_share']:.1%} | "
                     f"{r['entities']} | {r['entity_share']:.1%} |")

    s = c["scale_depth"]
    lines += ["", "## 3. Scale depth", "",
              f"- Deepest scale reached: {s['deepest_scale'] or 'none'} "
              f"(target: {s['target_scale']})",
              f"- Scales below the minimum: "
              f"{', '.join(s['missing_scales']) or 'none'}", "",
              "| scale | entities |", "| --- | --- |"]
    lines += [f"| {k} | {v} |" for k, v in s["counts"].items()]

    r = c["reward_distribution"]
    lines += ["", "## 4. Reward distribution", "",
              f"- Reward: mean {_fmt(r['reward']['mean'])}, "
              f"min {_fmt(r['reward']['min'])}, max {_fmt(r['reward']['max'])} "
              f"over {r['reward']['count']} entities",
              f"- Low-reward entities: {len(r['low_reward_entities'])}",
              f"- Unscored entities: {len(r['unscored_entities'])}"]
    for i, n in enumerate(r["histogram"]):
        lines.append(f"- {i / HISTOGRAM_BINS:.1f} - "
                     f"{(i + 1) / HISTOGRAM_BINS:.1f}: {n}")
    for name, st in r["verifiers"].items():
        lines.append(f"- {name}: mean {_fmt(st['mean'])} "
                     f"(min {_fmt(st['min'])})")
    lines += [f"- Warning: {w}" for w in r["warnings"]]

    gen = c["genericity"]
    lines += ["", "## 5. Genericity", "",
              f"- Mean genericity score: {_fmt(gen['genericity']['mean'])} "
              f"(threshold {gen['threshold']})",
              f"- Entities below threshold: {len(gen['generic_entities'])}",
              f"- Candidates rejected as generic: "
              f"{gen['candidates_rejected_as_generic']}"]
    lines += [f"- Warning: {w}" for w in gen["warnings"]]

    p = c["provenance"]
    lines += ["", "## 6. Provenance", "",
              f"- Entities without any grounding: "
              f"{', '.join(p['ungrounded_entities']) or 'none'}"]

    d = c["duplicates"]
    lines += ["", "## 7. Duplicates", "",
              f"- Entity texts: exact={d['entities']['exact_duplicate_count']}, "
              f"normalized={d['entities']['normalized_duplicate_count']}, "
              f"near pairs={d['entities']['near_duplicate_pair_count']}",
              f"- Repeated names: {d['names']['normalized_duplicate_count']}"]

    x = c["exploration"]
    lines += ["", "## 8. Exploration", "",
              f"- Run status: {x['run_status']}",
              f"- Stop reason: {x['stop_reason']}",
              f"- Iterations: {x['iterations']} "
              f"(accepted {x['accepted_iterations']} of "
              f"{x['logged_iterations']} logged)"]
    lines += [f"- Note: {n}" for n in x["notes"]]
    return "\n".join(lines) + "\n"


def write_quality_reports(
    world_dir: Any, report: Mapping[str, Any],
) -> Tuple[Path, Path]:
    """Write JSON and Markdown reports and return their paths."""
    root = Path(world_dir)
    json_path = root / "quality_report.json"
    md_path = root / "quality_report.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def create_quality_reports(
    world_dir: Any, config: Optional[Mapping[str, Any]] = None,
) -> Tuple[Dict[str, Any], Path, Path]:
    """Generate and write both quality report formats."""
    report = generate_quality_report(world_dir, config=config)
    json_path, md_path = write_quality_reports(world_dir, report)
    return report, json_path, md_path


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a world package quality report")
    parser.add_argument("world_dir", type=Path)
    parser.add_argument("--json", action="store_true",
                        help="print the full JSON report")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 when the overall status is fail")
    args = parser.parse_args(argv)
    try:
        report, json_path, md_path = create_quality_reports(args.world_dir)
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Quality: {str(report['status']).upper()}")
        for name, check in report["checks"].items():
            print(f"- {name}: {str(check['status']).upper()}")
        print(f"JSON: {json_path}\nMarkdown: {md_path}")
    return 1 if args.strict and report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
