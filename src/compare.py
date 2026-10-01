"""Compare generated world packages without calling external services.

Worlds generated from the same input should differ.  The report puts each
world's coverage, depth and scores side by side and measures how much the
worlds repeat each other (near-identical entities, shared names and shared
proper nouns).
"""

from __future__ import annotations

import argparse
from itertools import combinations
from pathlib import Path
from typing import (
    Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple,
)

import yaml

from .quality import (
    character_ngrams, entities_of, generate_quality_report,
    get_quality_config, jaccard, load_world_package, normalize_item, _num,
    _read_json,
)
from .world.graph import SCALES
from .world.verify import entity_text

UNKNOWN = "-"


def _proper_nouns(entities) -> Set[str]:
    return {normalize_item(f.get("text")) for e in entities
            for f in e.get("facts") or []
            if isinstance(f, Mapping) and f.get("kind") == "proper_noun"
            and normalize_item(f.get("text"))}


def _mean(values: Sequence[float]) -> Optional[float]:
    return round(sum(values) / len(values), 4) if values else None


def _world_summary(label: str, pkg: Mapping[str, Any],
                   cfg: Mapping[str, Any]) -> Dict[str, Any]:
    ents = entities_of(pkg["graph"])
    manifest = pkg["manifest"]
    explore = manifest.get("world_explore") or {}
    rewards = [v for v in (_num((e.get("scores") or {}).get("reward"))
                           for e in ents) if v is not None]
    generic = [v for v in (_num((e.get("scores") or {}).get("genericity"))
                           for e in ents) if v is not None]
    counts = {s: sum(1 for e in ents if e.get("scale") == s) for s in SCALES}
    reached = [s for s in SCALES if counts[s]]
    covered = {a for e in ents for a in e.get("axes") or []}
    axes = pkg["axes"]
    quality = generate_quality_report(pkg["root"], config=cfg)
    return {
        "label": label, "path": str(pkg["root"]),
        "run_id": manifest.get("run_id"), "run_seed": manifest.get("run_seed"),
        "backend": manifest.get("backend"), "model": manifest.get("model"),
        "stop_reason": manifest.get("stop_reason")
        or explore.get("stop_reason"),
        "iterations": manifest.get("iterations", explore.get("iteration", 0)),
        "entity_count": len(ents), "scale_counts": counts,
        "deepest_scale": reached[-1] if reached else None,
        "axis_count": len(axes),
        "axes_covered": sum(1 for a in axes if a["id"] in covered),
        "axis_names": sorted(str(a.get("name") or a["id"]) for a in axes),
        "mean_reward": _mean(rewards), "mean_genericity": _mean(generic),
        "quality_status": quality["status"],
        "quality_checks": {k: v["status"]
                           for k, v in quality["checks"].items()},
    }


def _entity_signatures(entities) -> List[Tuple[str, Set[str]]]:
    out = []
    for e in entities:
        norm = normalize_item(entity_text(e))
        out.append((normalize_item(e.get("name")), character_ngrams(norm)))
    return out


def _pair_overlap(left, right, threshold: float) -> Dict[str, Any]:
    """Overlap of two entity lists, as fractions of the smaller world."""
    ls, rs = _entity_signatures(left), _entity_signatures(right)
    smaller = min(len(ls), len(rs)) or 1
    right_names = {n for n, _ in rs if n}
    same_name = sum(1 for n, _ in ls if n and n in right_names)
    near = 0
    for _, lg in ls:
        if lg and any(rg and jaccard(lg, rg) >= threshold for _, rg in rs):
            near += 1
    lp, rp = _proper_nouns(left), _proper_nouns(right)
    nouns = len(lp & rp) / (len(lp | rp) or 1)
    return {
        "same_name_rate": round(same_name / smaller, 4),
        "near_duplicate_rate": round(min(near, smaller) / smaller, 4),
        "shared_proper_noun_rate": round(nouns, 4),
        "shared_proper_nouns": len(lp & rp)}


def _divergence(labels, packages, cfg) -> Dict[str, Any]:
    threshold = float(cfg["near_duplicate_threshold"])
    warn_at = float(cfg["cross_world_overlap_warn"])
    pairs = []
    for i, j in combinations(range(len(packages)), 2):
        o = _pair_overlap(entities_of(packages[i]["graph"]),
                          entities_of(packages[j]["graph"]), threshold)
        o.update({"left": labels[i], "right": labels[j]})
        o["overlap"] = max(o["same_name_rate"], o["near_duplicate_rate"],
                           o["shared_proper_noun_rate"])
        o["warning"] = o["overlap"] >= warn_at
        pairs.append(o)
    names = [set(sorted(str(a.get("name") or a["id"]) for a in p["axes"]))
             for p in packages]
    axis_pairs = [{"left": labels[i], "right": labels[j],
                   "similarity": round(jaccard(names[i], names[j]), 4)}
                  for i, j in combinations(range(len(packages)), 2)]
    return {"pairs": pairs, "axis_similarity": axis_pairs,
            "max_overlap": max((p["overlap"] for p in pairs), default=None),
            "overlap_warn_threshold": warn_at}


def generate_comparison_report(
    world_dirs: Sequence[Any], config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a comparison report in memory (nothing is written)."""
    paths = [Path(p) for p in world_dirs]
    if not paths:
        raise ValueError("at least one world directory is required")
    cfg = get_quality_config(config)
    packages = [load_world_package(p) for p in paths]
    seen: Dict[str, int] = {}
    labels = []
    for p in paths:
        base = p.name or str(p)
        seen[base] = seen.get(base, 0) + 1
        labels.append(base if seen[base] == 1 else f"{base} ({seen[base]})")
    return {
        "schema_version": 2,
        "worlds": [_world_summary(lb, pk, cfg)
                   for lb, pk in zip(labels, packages)],
        "divergence": _divergence(labels, packages, cfg),
    }


def _cell(value: Any) -> str:
    if value is None or value == "":
        return UNKNOWN
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _row(values: Sequence[Any]) -> str:
    return "| " + " | ".join(_cell(v) for v in values) + " |"


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render a comparison report as Markdown."""
    worlds = report["worlds"]
    lines = ["# World Comparison", "", f"- Worlds: {len(worlds)}", "",
             "## Runs", "", _row(["world", "seed", "backend", "model",
                                  "stop reason", "iterations"]),
             "|" + "---|" * 6]
    for w in worlds:
        lines.append(_row([w["label"], w["run_seed"], w["backend"],
                           w["model"], w["stop_reason"], w["iterations"]]))

    lines += ["", "## Coverage and depth", "",
              _row(["world", "entities", "axes covered", "deepest scale",
                    *SCALES]), "|" + "---|" * (4 + len(SCALES))]
    for w in worlds:
        lines.append(_row([
            w["label"], w["entity_count"],
            f"{w['axes_covered']}/{w['axis_count']}", w["deepest_scale"],
            *(w["scale_counts"][s] for s in SCALES)]))

    lines += ["", "## Scores and quality", "",
              _row(["world", "mean reward", "mean genericity", "quality"]),
              "|" + "---|" * 4]
    for w in worlds:
        lines.append(_row([w["label"], w["mean_reward"],
                           w["mean_genericity"],
                           str(w["quality_status"]).upper()]))

    div = report["divergence"]
    lines += ["", "## Cross-world overlap", ""]
    if not div["pairs"]:
        lines.append("A single world: nothing to compare.")
    else:
        lines += [
            f"Overlap is the largest of the three rates; a pair at or above "
            f"{div['overlap_warn_threshold']:.2f} is flagged.", "",
            _row(["pair", "same name", "near-duplicate", "shared proper nouns",
                  "flag"]), "|" + "---|" * 5]
        for p in div["pairs"]:
            lines.append(_row([
                f"{p['left']} / {p['right']}", f"{p['same_name_rate']:.1%}",
                f"{p['near_duplicate_rate']:.1%}",
                f"{p['shared_proper_noun_rate']:.1%}",
                "REPEATS" if p["warning"] else ""]))
        lines += ["", "### Axis similarity", ""]
        lines += [f"- {a['left']} / {a['right']}: {a['similarity']:.1%}"
                  for a in div["axis_similarity"]]
    return "\n".join(lines) + "\n"


def create_comparison_report(
    world_dirs: Sequence[Any], output_path: Any,
    config: Optional[Mapping[str, Any]] = None,
) -> Tuple[Dict[str, Any], Path]:
    """Generate and write a comparison Markdown report."""
    report = generate_comparison_report(world_dirs, config=config)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report), encoding="utf-8")
    return report, path


def resolve_batch_worlds(batch_dir: Any) -> List[Path]:
    """Resolve the completed world packages listed by a batch manifest."""
    batch_path = Path(batch_dir)
    manifest_path = batch_path / "batch_manifest.json"
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError(f"Invalid or missing batch manifest: {manifest_path}")

    def resolve(value: Any) -> Path:
        path = Path(str(value))
        return path if path.is_absolute() or path.is_dir() \
            else batch_path / path

    worlds_dir = resolve(manifest.get("worlds_dir", "worlds"))
    resolved: List[Path] = []
    seen: Set[Path] = set()
    for record in manifest.get("runs") or []:
        if not isinstance(record, Mapping) \
                or record.get("status") not in (None, "completed"):
            continue
        candidate = resolve(record["output_dir"]) \
            if record.get("output_dir") else None
        if (candidate is None or not candidate.is_dir()) \
                and record.get("run_id"):
            candidate = worlds_dir / f"world_{record['run_id']}"
        if candidate is not None and candidate.is_dir():
            candidate = candidate.resolve()
            if candidate not in seen:
                resolved.append(candidate)
                seen.add(candidate)
    if not resolved and worlds_dir.is_dir():
        resolved = sorted(
            (p.resolve() for p in worlds_dir.iterdir()
             if p.is_dir() and (p / "world" / "graph.json").is_file()),
            key=str)
    return resolved


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a side-by-side comparison of world packages")
    parser.add_argument("world_dirs", nargs="*", type=Path)
    parser.add_argument("--batch", type=Path, help="batch directory")
    parser.add_argument("--out", type=Path, help="output Markdown path")
    args = parser.parse_args(argv)
    if args.batch and args.world_dirs:
        parser.error("world directories and --batch cannot be used together")
    try:
        if args.batch:
            world_dirs = resolve_batch_worlds(args.batch)
            if not world_dirs:
                raise ValueError(
                    f"No completed worlds found in batch: {args.batch}")
            output_path = args.out or (args.batch / "comparison.md")
        else:
            world_dirs = args.world_dirs
            if not world_dirs:
                parser.error("at least one world directory is required")
            output_path = args.out
        if output_path:
            create_comparison_report(world_dirs, output_path)
        else:
            print(render_markdown(generate_comparison_report(world_dirs)),
                  end="")
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
