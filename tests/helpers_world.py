"""Builders for synthetic world packages used by report tests (no LLM)."""

import json
from pathlib import Path

from src.world.graph import dumps, make_entity, new_graph

PROV = {"statement_ids": ["s1"], "derived_from": [], "reason": ""}
GOOD = {"genericity": 0.9, "provenance": 1.0, "specificity": 0.8,
        "consistency": 1.0, "objectivity": 0.9, "novelty": 0.9, "reward": 0.85}

AXES = [
    {"id": "a1", "name": "Axis One", "meaning": "first", "weight": 0.7,
     "grounds": {"statement_ids": ["s1"], "reason": "stated"},
     "origin": "catalog"},
    {"id": "a2", "name": "Axis Two", "meaning": "second", "weight": 0.3,
     "grounds": {"statement_ids": [], "reason": "needed"},
     "origin": "added"},
]


def entity(eid, scale, name, parent=None, axes=("a1",), scores=GOOD,
           summary=None, facts=None, provenance=PROV):
    return make_entity(
        eid, "concept", name, scale, axes=list(axes), parent=parent,
        summary=summary or f"{name} holds a distinct place in the order",
        facts=facts if facts is not None else [
            {"kind": "proper_noun", "text": f"{name} Registry",
             "provenance": provenance}],
        provenance=provenance, scores=dict(scores))


def deep_entities(prefix="x"):
    """One entity at every scale, chained parent to child."""
    scales = ["world", "region", "settlement", "district", "site", "detail"]
    out, parent = [], None
    for i, s in enumerate(scales, 1):
        out.append(entity(f"e{i}", s, f"{prefix} {s} name{i}", parent,
                          axes=("a1", "a2") if i < 3 else ("a1",)))
        parent = f"e{i}"
    return out


def write_package(root, entities, axes=AXES, manifest=None, prefs=None,
                  language="en"):
    root = Path(root)
    (root / "world").mkdir(parents=True, exist_ok=True)
    graph = new_graph(language)
    graph["entities"] = list(entities)
    (root / "world" / "graph.json").write_text(dumps(graph), encoding="utf-8")
    (root / "world" / "world_axes.json").write_text(
        json.dumps({"axes": axes}), encoding="utf-8")
    (root / "run_manifest.json").write_text(json.dumps(
        manifest if manifest is not None else {
            "run_id": root.name, "run_seed": 1, "backend": "fake",
            "model": "fake", "status": "completed",
            "stop_reason": "max_iterations", "iterations": 3,
            "counters": {"generation_calls": 5}}), encoding="utf-8")
    if prefs is not None:
        (root / "world" / "preferences.jsonl").write_text(
            "".join(json.dumps(p) + "\n" for p in prefs), encoding="utf-8")
    return root


def candidate_output(item):
    """Complete synthetic candidate fixtures using the declared output fields."""
    return {"axes": [], "derived_from": [], "relations": [], **item,
            "premise_usage": {"calendars": [], "technologies": [], "units": [],
                              "institutions": [], **item.get("premise_usage", {})}}


def review_output(prompt, assessments):
    """Emit the per-term approval fields requested by this synthetic prompt."""
    import copy
    result = copy.deepcopy(assessments)
    context = json.JSONDecoder().raw_decode(prompt.split(
        "CONTEXT (world premises, local entities and explicit input; may be empty):\n", 1)[1].lstrip())[0]
    proposal = context["proposed_premise_extension"]
    for criterion, item in result.items():
        if "_approve" not in item:
            continue
        approve = item.pop("_approve")
        if criterion == "consistency" and proposal:
            item["premise_extension_approvals"] = {
                group: [{"unit" if group == "units" else "capability": term,
                         "approved": "yes" if approve else "no", "why": "synthetic review"}
                        for term in proposal.get(group, [])]
                for group in ("units", "capabilities")}
    return result
