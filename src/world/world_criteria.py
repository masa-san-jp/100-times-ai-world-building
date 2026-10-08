"""Deterministic measurements of the world's purpose-derived criteria."""

from __future__ import annotations

import math
from pathlib import Path

import yaml

from .graph import SCALES, SCALE_RANK
from .premises import premise_source


DEFAULT_WORLD_CRITERIA_PATH = (
    Path(__file__).resolve().parents[2] / "config/world/world_criteria.yaml")


def load_world_criteria_config():
    return yaml.safe_load(DEFAULT_WORLD_CRITERIA_PATH.read_text(encoding="utf-8"))


def axis_requirements(axes, cfg):
    return {a["id"]: max(1, math.ceil(float(a.get("weight") or 0)
                                    * cfg["breadth"]["per_weight"]))
            for a in axes or []}


def axis_counts(graph, axes):
    counts = {a["id"]: 0 for a in axes or []}
    for entity in graph.get("entities", []):
        for axis in set(entity.get("axes", [])):
            if axis in counts:
                counts[axis] += 1
    return counts


def causal_entities(graph):
    """Both endpoints of causes/affects, including incoming-only entities."""
    connected = set()
    for entity in graph.get("entities", []):
        for relation in entity.get("relations", []):
            if relation.get("type") in {"causes", "affects"}:
                connected.update((entity["id"], relation["target"]))
    return connected


def scale_chain(graph):
    """Deepest uninterrupted world-rooted chain, using existing id tie order."""
    entities = graph.get("entities", [])
    paths = {e["id"]: [e["id"]] for e in entities if e["scale"] == "world"}
    for scale in SCALES[1:]:
        for entity in sorted(entities, key=lambda e: e["id"]):
            parent_path = paths.get(entity.get("parent"))
            if entity["scale"] == scale and parent_path \
                    and len(parent_path) == SCALE_RANK[scale]:
                paths[entity["id"]] = parent_path + [entity["id"]]
    return min(paths.values(), key=lambda path: (-len(path), path[-1])) if paths else []


def world_status(graph, axes, brief, contract, cfg):
    """Return value, provisional threshold and met for each specified metric.

    Metric ids qualify the multiple measurements of breadth, depth and scale.
    An empty denominator gives 0.0 and is never treated as achievement.
    Operator counts use recorded origin_operator only.
    """
    entities = graph.get("entities", [])
    criteria = {}

    def add(metric, value, threshold):
        criteria[metric] = {"value": value, "threshold": threshold,
                            "met": value >= threshold}

    def add_ratio(metric, numerator, denominator, threshold):
        add(metric, numerator / denominator if denominator else 0.0, threshold)
        if not denominator:
            criteria[metric]["met"] = False

    statements = {s["id"] for s in (brief or {}).get("statements", [])}
    used = set()
    contract_source = contract or graph.get("world_contract") or {}
    if contract_source.get("source_entity"):
        contract_source = premise_source(graph, contract_source["source_entity"]) or {}
    for source in [*entities, contract_source]:
        used.update((source.get("provenance") or {}).get("statement_ids", []))
    add_ratio("faithful", len(statements & used), len(statements),
              cfg["faithful"]["threshold"])

    counts = axis_counts(graph, axes)
    required = axis_requirements(axes, cfg)
    add_ratio("breadth.axes", sum(counts[a] >= n for a, n in required.items()),
              len(required), cfg["breadth"]["axes"])
    add("breadth.perspective", sum(e.get("origin_operator") == "perspective"
        for e in entities), cfg["breadth"]["perspective"])

    connected = causal_entities(graph)
    non_world = [e for e in entities if e["scale"] != "world"]
    add_ratio("depth.relations", sum(e["id"] in connected for e in non_world),
              len(non_world), cfg["depth"]["relations"])
    add("depth.history", sum(e.get("origin_operator") == "history"
        for e in entities), cfg["depth"]["history"])

    for scale in SCALES:
        add(f"scale.{scale}", sum(e["scale"] == scale for e in entities),
            cfg["scale"]["min_entities"])
    add("scale.chain", len(scale_chain(graph)) == len(SCALES), cfg["scale"]["chain"])
    return {"criteria": criteria, "met": all(c["met"] for c in criteria.values())}
