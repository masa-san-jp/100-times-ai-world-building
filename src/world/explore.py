"""Frontier and bandit exploration using checked, incremental entity builds."""

from __future__ import annotations

import copy
import json
import math
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import (
    Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union,
)

import yaml
from loguru import logger

from .graph import (
    SCALE_RANK, SCALES, GraphStore, guess_language, local_context,
)
from .structured import StructuredFailure, client_instance, metrics_markdown
from .operators import OperatorConfig
from .builder import EntityBuilder
from .premises import world_premises
from .world_criteria import (
    axis_counts, axis_requirements, causal_entities, load_world_criteria_config,
    scale_chain, world_status,
)

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
DEFAULT_EXPLORE_PATH = CONFIG_DIR / "world" / "explore.yaml"
PREFERENCES_RELATIVE_PATH = Path("world") / "preferences.jsonl"
CHECKPOINT_PHASE = "world_explore"
STATE_VERSION = 1

STOP_REASONS = (
    "coverage_met", "max_iterations", "max_wall_seconds",
    "max_generation_calls", "frontier_exhausted", "too_many_failures",
)

# Operators that deliberately widen the world or add a second explanation
# of an existing entity. They are policy data, not assumptions about content.
BREADTH_OPERATORS = ("expand", "perspective", "cause", "history", "document")


class BudgetExhausted(RuntimeError):
    """Raised inside an iteration when the generation-call budget is spent."""


# ------------------------------------------------------------------ config

def _merge(base: Dict[str, Any], over: Mapping[str, Any]) -> Dict[str, Any]:
    for k, v in over.items():
        if isinstance(v, Mapping) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = copy.deepcopy(v)
    return base


def load_explore_config(
    path: Any = None, overrides: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    cfg = yaml.safe_load(
        Path(path or DEFAULT_EXPLORE_PATH).read_text(encoding="utf-8")) or {}
    return _merge(cfg, overrides or {})


# ---------------------------------------------------------------- frontier

def _children(graph: Mapping[str, Any]) -> Dict[str, int]:
    count: Dict[str, int] = {}
    for e in graph.get("entities", []):
        if e.get("parent"):
            count[e["parent"]] = count.get(e["parent"], 0) + 1
    return count


def axis_shares(axes: Optional[Sequence[Mapping[str, Any]]]) -> Dict[str, float]:
    """Budget share per axis: weight / sum of weights."""
    items = [(a["id"], float(a.get("weight") or 0.0))
             for a in axes or [] if isinstance(a, Mapping) and a.get("id")]
    total = sum(w for _, w in items)
    if not items:
        return {}
    if total <= 0:
        return {i: 1.0 / len(items) for i, _ in items}
    return {i: w / total for i, w in items}


def axis_consumption(
    graph: Mapping[str, Any], axes: Optional[Sequence[Mapping[str, Any]]],
) -> Dict[str, int]:
    used = {a["id"]: 0 for a in axes or [] if isinstance(a, Mapping)
            and a.get("id")}
    for e in graph.get("entities", []):
        for a in e.get("axes", []):
            if a in used:
                used[a] += 1
    return used


def scale_needs(
    graph: Mapping[str, Any], cfg: Mapping[str, Any],
) -> Dict[str, float]:
    """Shortage per scale in [0, 1] against the world scale criterion.

    All scales from world through detail are measured.
    """
    want = load_world_criteria_config()["scale"]["min_entities"]
    counts = {s: 0 for s in SCALES}
    for e in graph.get("entities", []):
        if e.get("scale") in counts:
            counts[e["scale"]] += 1
    return {s: max(0, want - counts[s]) / want for s in SCALES}


def _axis_target(
    graph: Mapping[str, Any], axis_id: str,
    needs: Optional[Mapping[str, float]] = None,
) -> Optional[str]:
    """Entity to build under for an under-served axis (deterministic).

    The gap is filled below an existing entity (zoom) or beside it
    (perspective / cause), not by adding world-scale siblings: among the
    entities that can still be zoomed into, the one whose child scale is
    the most under-filled is chosen, so axis gaps also push the world
    downward.  Entities already tagged with the axis win ties.
    """
    ents = sorted(graph.get("entities", []), key=lambda e: e["id"])
    detail = SCALE_RANK["detail"]
    zoomable = [e for e in ents if SCALE_RANK[e["scale"]] < detail]
    if zoomable and needs is not None:
        return min(zoomable, key=lambda e: (
            -needs.get(SCALES[SCALE_RANK[e["scale"]] + 1], 0.0),
            0 if axis_id in e.get("axes", []) else 1,
            SCALE_RANK[e["scale"]], e["id"]))["id"]
    tagged = [e for e in ents if axis_id in e.get("axes", [])]
    if tagged:
        return min(tagged, key=lambda e: (SCALE_RANK[e["scale"]], e["id"]))["id"]
    regions = [e for e in ents if e.get("scale") == "region"]
    pool = regions or [e for e in ents if e.get("scale") == "world"] or ents
    return pool[0]["id"] if pool else None


def operator_consumption(
    graph: Mapping[str, Any],
    operators: Optional[Sequence[str]] = None,
) -> Dict[str, int]:
    """Count entities produced by each breadth operator.

    New entities carry ``origin_operator``. The relation/type fallback keeps
    this useful for graphs written by earlier versions of the engine.
    """
    wanted = tuple(operators or BREADTH_OPERATORS)
    used = {op: 0 for op in wanted}
    for entity in graph.get("entities", []):
        op = entity.get("origin_operator")
        if op not in used:
            if entity.get("type") == "document":
                op = "document"
            else:
                rel_types = {r.get("type") for r in entity.get("relations", [])
                             if isinstance(r, Mapping)}
                if "causes" in rel_types:
                    op = "cause"
                elif "affects" in rel_types:
                    op = "history"
                elif "related_to" in rel_types:
                    op = "perspective"
                else:
                    op = None
        if op in used:
            used[op] += 1
    return used


def _breadth_target(
    graph: Mapping[str, Any], operator: str,
    needs: Mapping[str, float],
) -> Optional[str]:
    """Choose a bounded, deterministic target for a missing breadth arm."""
    entities = [e for e in graph.get("entities", [])
                if e.get("type") != "document"] or list(graph.get("entities", []))
    if not entities:
        return None

    def key(e: Mapping[str, Any]) -> Tuple[Any, ...]:
        rank = SCALE_RANK.get(e.get("scale"), 0)
        below = needs.get(SCALES[rank + 1], 0.0) if rank + 1 < len(SCALES) else 0.0
        type_penalty = 0
        if operator == "perspective":
            type_penalty = 0 if e.get("type") in {
                "institution", "place", "event", "group", "practice"
            } else 1
        return (type_penalty, -below, -rank, str(e.get("id")))
    return min(entities, key=key).get("id")


def evaluate_frontier(
    graph: Mapping[str, Any],
    axes: Optional[Sequence[Mapping[str, Any]]],
    cfg: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """List frontier items ``{kind, target, axis, deficit, axis_share, ...}``.

    Each item has a ``deficit`` in [0, 1] (how much the spot lacks) and an
    ``axis_share`` in [0, 1] (the normalized weight of its axis).  It also
    carries ``target_scale`` and ``depth_need`` (``same`` / ``below``: the
    shortage of entities at the target's scale and at the scale one below
    it, see :func:`scale_needs`), which :func:`pair_prior` uses to favour
    ``zoom`` while lower scales are empty.  Output order is deterministic.
    """
    fcfg = cfg.get("frontier", {})
    criteria_cfg = load_world_criteria_config()
    entities = sorted(graph.get("entities", []), key=lambda e: e["id"])
    if not entities:
        return [{"kind": "empty", "target": None, "axis": None,
                 "deficit": 1.0, "axis_share": 0.0, "target_scale": None,
                 "depth_need": None}]

    shares = axis_shares(axes)
    top = max(shares.values(), default=0.0)

    def share_of(ids: Sequence[str]) -> float:
        vals = [shares[a] for a in ids if a in shares]
        return (sum(vals) / len(vals) / top) if vals and top > 0 else 0.0

    kids = _children(graph)
    detail_rank = SCALE_RANK["detail"]
    explainers = {e["id"] for e in entities
                  if any(r.get("type") == "causes" for r in e.get("relations", []))}
    explained = {r["target"] for e in entities for r in e.get("relations", [])
                 if r.get("type") == "causes"}
    min_facts = int(fcfg.get("min_facts", 3))
    low_thr = float(fcfg.get("low_score_threshold", 0.5))
    low_names = list(fcfg.get("low_score_verifiers") or [])
    max_per_kind = int(cfg.get("selection", {}).get("max_items_per_kind", 12))

    by_kind: Dict[str, List[Dict[str, Any]]] = {}
    needs = scale_needs(graph, cfg)
    by_id = {e["id"]: e for e in entities}

    def add(kind, target, deficit, axis=None, share=0.0):
        scale = by_id[target]["scale"]
        rank = SCALE_RANK[scale]
        below = needs[SCALES[rank + 1]] if rank + 1 < len(SCALES) else 0.0
        by_kind.setdefault(kind, []).append({
            "kind": kind, "target": target, "axis": axis,
            "deficit": round(max(0.0, min(1.0, deficit)), 6),
            "axis_share": round(share, 6), "target_scale": scale,
            "depth_need": {"same": round(needs[scale], 6),
                           "below": round(below, 6)}})

    for e in entities:
        rank = SCALE_RANK[e["scale"]]
        sh = share_of(e.get("axes", []))
        if rank < detail_rank and not kids.get(e["id"]):
            add("unexpanded", e["id"], 1.0 - rank / (len(SCALES) - 1), None, sh)
        if (e["id"] not in explained and e["id"] not in explainers
                and e.get("type") != "document"):
            add("uncaused", e["id"], 0.6, None, sh)
        nf = len(e.get("facts", []))
        if nf < min_facts and min_facts > 0:
            add("thin", e["id"], (min_facts - nf) / min_facts, None, sh)
        scores = e.get("scores") or {}
        lows = [low_thr - scores[v] for v in low_names
                if isinstance(scores.get(v), (int, float)) and scores[v] < low_thr]
        if lows and low_thr > 0:
            add("low_score", e["id"], max(lows) / low_thr, None, sh)

    used = axis_counts(graph, axes)
    required = axis_requirements(axes, criteria_cfg)
    for axis_id in sorted(used):
        expected = required[axis_id]
        if used[axis_id] < expected:
            target = _axis_target(graph, axis_id, needs)
            if target is not None:
                add("axis_gap", target, (expected - used[axis_id]) / expected,
                    axis_id, shares.get(axis_id, 0.0) / top if top > 0 else 0.0)

    # Scale coverage alone can be satisfied by repeatedly descending along
    # one path. Make unserved widening/viewpoint operators first-class
    # frontier items so the bandit can allocate budget to them.
    bcfg = cfg.get("breadth", {})
    if bcfg.get("enabled", True):
        breadth_ops = tuple(bcfg.get("operators") or BREADTH_OPERATORS)
        minimum = max(1, int(bcfg.get("min_entities_per_operator", 1)))
        consumed = operator_consumption(graph, breadth_ops)
        for operator in breadth_ops:
            missing = max(0, minimum - consumed.get(operator, 0))
            if not missing:
                continue
            target = _breadth_target(graph, operator, needs)
            if target is None:
                continue
            entity = by_id[target]
            add("breadth_gap", target, min(1.0, missing / minimum),
                None, share_of(entity.get("axes", [])))
            by_kind["breadth_gap"][-1]["operator"] = operator
            by_kind["breadth_gap"][-1]["breadth_need"] = round(
                min(1.0, missing / minimum), 6)

    # The purpose-derived gaps expose exactly the operation in the design.
    # Existing frontier kinds and their allowed operations remain available.
    status = world_status(graph, axes, {}, graph.get("world_contract"), criteria_cfg)

    def add_world_gap(metric, operator, target):
        row = status["criteria"][metric]
        if row["met"] or target is None:
            return
        add("world_gap", target, 1 - row["value"] / row["threshold"],
            share=share_of(by_id[target].get("axes", [])))
        by_kind["world_gap"][-1].update(operator=operator, criterion=metric)

    weights = {a["id"]: float(a.get("weight") or 0) for a in axes or []}
    target = min(entities, key=lambda e: (
        -max((weights[a] for a in e.get("axes", []) if a in weights), default=0.0),
        int(e["id"][1:])))
    add_world_gap("breadth.perspective", "perspective", target["id"])

    connected = causal_entities(graph)
    unconnected = [e for e in entities if e["id"] not in connected]
    if unconnected:
        target = min(unconnected, key=lambda e: (SCALE_RANK[e["scale"]], e["id"]))
        add_world_gap("depth.relations", "cause", target["id"])
        add_world_gap("depth.history", "history", target["id"])

    chain = scale_chain(graph)
    if chain and len(chain) < len(SCALES):
        add_world_gap("scale.chain", "zoom", chain[-1])

    items: List[Dict[str, Any]] = []
    for kind in sorted(by_kind):
        ranked = sorted(by_kind[kind], key=lambda i: (
            -i["deficit"], str(i["axis"]), str(i["target"])))
        items.extend(ranked[:max_per_kind])
    return items


def candidate_pairs(
    items: Sequence[Mapping[str, Any]], cfg: Mapping[str, Any],
) -> List[Tuple[Dict[str, Any], str]]:
    ops = cfg.get("operators", {})
    pairs = []
    for item in items:
        allowed = ([item.get("operator")] if item.get("operator")
                   else ops.get(item["kind"], []))
        for op in allowed:
            if op and not (op == "zoom" and item.get("target_scale") == "detail"):
                pairs.append((dict(item), op))
    return pairs


# ------------------------------------------------------------------ bandit

def arm_key(operator: str, item: Mapping[str, Any], by_axis: bool) -> str:
    key = f"{operator}|{item['kind']}"
    if by_axis and item.get("axis"):
        key += f"|{item['axis']}"
    return key


class Bandit:
    """UCB1 or Thompson-sampling bandit over named arms with item priors."""

    def __init__(self, cfg: Mapping[str, Any], rng: random.Random,
                 state: Optional[Mapping[str, Any]] = None) -> None:
        self.cfg = dict(cfg)
        self.rng = rng
        self.arms: Dict[str, Dict[str, float]] = {}
        if state:
            self.arms = {k: {"n": int(v["n"]), "sum": float(v["sum"])}
                         for k, v in state.get("arms", {}).items()}

    @property
    def total(self) -> int:
        return sum(int(a["n"]) for a in self.arms.values())

    def _prior(self) -> Tuple[float, float]:
        return (float(self.cfg.get("prior_mean", 0.5)),
                float(self.cfg.get("prior_strength", 1.0)))

    def mean(self, key: str) -> float:
        a = self.arms.get(key, {"n": 0, "sum": 0.0})
        pm, ps = self._prior()
        return (pm * ps + a["sum"]) / (ps + a["n"]) if ps + a["n"] > 0 else pm

    def value(self, key: str) -> float:
        """Deterministic UCB1 value of an arm."""
        a = self.arms.get(key, {"n": 0, "sum": 0.0})
        bonus = float(self.cfg.get("exploration", 0.6)) * math.sqrt(
            math.log(self.total + 1.0) / (a["n"] + 1.0))
        return self.mean(key) + bonus

    def _sample(self, key: str) -> float:
        a = self.arms.get(key, {"n": 0, "sum": 0.0})
        pm, ps = self._prior()
        alpha = max(1e-6, pm * ps + a["sum"])
        beta = max(1e-6, (1.0 - pm) * ps + (a["n"] - a["sum"]))
        return self.rng.betavariate(alpha, beta)

    def select(self, options: Sequence[Tuple[str, float]]) -> int:
        """Return the index of the chosen ``(arm_key, item_prior)`` option."""
        if not options:
            raise ValueError("no options")
        eps = float(self.cfg.get("epsilon", 0.0))
        explore = self.rng.random()  # always drawn, keeps streams aligned
        pick = self.rng.randrange(len(options))
        if explore < eps:
            return pick
        weight = float(self.cfg.get("item_prior_weight", 0.0))
        thompson = self.cfg.get("strategy", "ucb1") == "thompson"
        sampled: Dict[str, float] = {}
        best, best_score = 0, -math.inf
        for i, (key, prior) in enumerate(options):
            if thompson:
                if key not in sampled:
                    sampled[key] = self._sample(key)
                base = sampled[key]
            else:
                base = self.value(key)
            score = base + weight * prior
            if score > best_score:
                best, best_score = i, score
        return best

    def update(self, key: str, reward: float) -> None:
        a = self.arms.setdefault(key, {"n": 0, "sum": 0.0})
        a["n"] += 1
        a["sum"] += max(0.0, min(1.0, float(reward)))

    def to_dict(self) -> Dict[str, Any]:
        return {"arms": {k: {"n": int(v["n"]), "sum": round(v["sum"], 10)}
                         for k, v in sorted(self.arms.items())}}


def _rng_state(rng: random.Random) -> List[Any]:
    version, internal, gauss = rng.getstate()
    return [version, list(internal), gauss]


def _set_rng_state(rng: random.Random, state: Sequence[Any]) -> None:
    rng.setstate((state[0], tuple(state[1]), state[2]))


def item_prior(item: Mapping[str, Any], cfg: Mapping[str, Any]) -> float:
    sel = cfg.get("selection", {})
    dw, aw = float(sel.get("deficit_weight", 0.7)), float(sel.get("axis_weight", 0.3))
    total = dw + aw
    if total <= 0:
        return 0.0
    return (dw * float(item["deficit"]) + aw * float(item["axis_share"])) / total


def pair_prior(
    item: Mapping[str, Any], operator: str, cfg: Mapping[str, Any],
) -> float:
    """Prior of an ``(item, operator)`` pair: item prior plus depth need.

    The depth term is the shortage of entities at the scale the operator
    would add to (one below the target for ``zoom``, the target's own scale
    otherwise), so while lower scales are empty ``zoom`` ranks first.
    """
    sel = cfg.get("selection", {})
    base = item_prior(item, cfg)
    if item.get("kind") == "breadth_gap":
        bw = float(sel.get("breadth_weight", 0.0))
        need = float(item.get("breadth_need", item.get("deficit", 0.0)))
        item_weight = (float(sel.get("deficit_weight", 0.7))
                       + float(sel.get("axis_weight", 0.3)))
        if bw > 0 and item_weight + bw > 0:
            base = (base * item_weight + bw * need) / (item_weight + bw)
    wd = float(sel.get("depth_weight", 0.0))
    need = item.get("depth_need")
    if wd <= 0 or not need:
        return base
    w = float(sel.get("deficit_weight", 0.7)) + float(sel.get("axis_weight", 0.3))
    depth = float(need["below" if operator == "zoom" else "same"])
    return (base * w + wd * depth) / (w + wd)


# ----------------------------------------------------------------- the loop

class _CountingBackend:
    """Counts generation calls and enforces the call budget."""

    def __init__(self, inner: Any, counters: Dict[str, int], parent: Any = None) -> None:
        self._inner = inner
        self._counters = counters
        self._parent = parent  # shares the parent's call budget
        self.limit: Optional[int] = None

    def _tick(self) -> None:
        if self._parent is not None:
            self._parent._tick()
            return
        if self.limit is not None and self._counters["generation_calls"] >= self.limit:
            raise BudgetExhausted("generation-call budget exhausted")
        self._counters["generation_calls"] += 1

    def generate_schema(self, *args: Any, **kwargs: Any) -> Any:
        self._tick()
        return self._inner.generate_schema(*args, **kwargs)

    def generate_text(self, *args: Any, **kwargs: Any) -> Any:
        self._tick()
        return self._inner.generate_text(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


@dataclass
class ExplorationResult:
    stop_reason: str
    iterations: int
    graph: Dict[str, Any]
    counters: Dict[str, int]
    coverage: Dict[str, Any]
    preferences_path: Path
    state: Dict[str, Any] = field(default_factory=dict)


def _fresh_state(seed: int) -> Dict[str, Any]:
    return {
        "version": STATE_VERSION, "seed": seed, "iteration": 0,
        "counters": {"generation_calls": 0, "accepted": 0, "rejected": 0,
                     "no_candidates": 0, "rewrites": 0, "errors": 0},
        "elapsed_seconds": 0.0, "bandit": {"arms": {}}, "rng": None,
        "log_lines": 0, "max_entity_n": 0, "stop_reason": None,
        "consecutive_failures": 0,
    }


def _max_entity_n(graph: Mapping[str, Any]) -> int:
    best = 0
    for e in graph.get("entities", []):
        eid = str(e.get("id", ""))
        if eid[:1] == "e" and eid[1:].isdigit():
            best = max(best, int(eid[1:]))
    return best


class ExplorationLoop:
    def __init__(
        self, backend: Any, package_dir: Union[str, Path],
        brief: Mapping[str, Any],
        axes: Sequence[Mapping[str, Any]], *,
        seed: int = 0,
        language: Optional[str] = None,
        config: Optional[Mapping[str, Any]] = None,
        operator_config: Optional[OperatorConfig] = None,
        checkpoints: Any = None,
        manifest: Any = None,
        clock: Callable[[], float] = time.monotonic,
        raw_input: Optional[str] = None,
        structured_max_attempts: int = 3,
        structured_max_conversions: int = 2,
        judge_backend: Any = None,
    ) -> None:
        self.package_dir = Path(package_dir)
        raw_path = self.package_dir / "input" / "user_input.txt"
        self.raw_input = (raw_input if raw_input is not None else
                          raw_path.read_text(encoding="utf-8") if raw_path.exists() else "")
        self.brief = brief
        self.axes = list(axes)
        self.seed = seed
        self.cfg = dict(config) if config is not None else load_explore_config()
        self.criteria_cfg = load_world_criteria_config()
        self.language = language
        if checkpoints is None:
            from ..checkpoint_manager import CheckpointManager
            checkpoints = CheckpointManager(
                str(self.package_dir / "checkpoints"))
        self.checkpoints = checkpoints
        self.manifest = manifest
        self.clock = clock
        self.state = _fresh_state(seed)
        self.backend = _CountingBackend(backend, self.state["counters"])
        builder_cfg = copy.deepcopy(self.cfg)
        builder_cfg["structured"] = {"max_attempts": structured_max_attempts,
                                     "max_conversions": structured_max_conversions}
        if operator_config is not None:
            builder_cfg["operator"] = asdict(operator_config)
        self.judge_backend = (_CountingBackend(judge_backend, self.state["counters"], self.backend)
                              if judge_backend is not None else self.backend)
        self.builder = EntityBuilder(self.backend, builder_cfg, judge_backend=self.judge_backend)
        self.store = GraphStore(
            self.package_dir, self.checkpoints, self.axes, self.brief)
        self.log_path = self.package_dir / PREFERENCES_RELATIVE_PATH
        self.rng = random.Random(seed)
        self.bandit = Bandit(self.cfg.get("selection", {}), self.rng)

    # -- persistence
    def _load_state(self) -> bool:
        data = self.checkpoints.load_checkpoint(CHECKPOINT_PHASE)
        if not isinstance(data, dict) or data.get("version") != STATE_VERSION \
                or data.get("seed") != self.seed or not data.get("rng"):
            return False
        counters = self.state["counters"]  # keep identity for the backend
        counters.update({k: int(v) for k, v in data["counters"].items()})
        self.state.update({k: data[k] for k in (
            "iteration", "elapsed_seconds", "log_lines", "max_entity_n",
            "stop_reason", "consecutive_failures") if k in data})
        self.bandit.arms = Bandit(self.cfg.get("selection", {}), self.rng,
                                  data.get("bandit")).arms
        if "build" in data:
            self.builder.metrics = copy.deepcopy(data["build"])
        _set_rng_state(self.rng, data["rng"])
        return True

    def _save_state(self) -> None:
        s = self.state
        s["build"] = copy.deepcopy(self.builder.metrics)
        s["bandit"] = self.bandit.to_dict()
        s["rng"] = _rng_state(self.rng)
        self.checkpoints.save_checkpoint(CHECKPOINT_PHASE, copy.deepcopy(s))
        if self.manifest is not None:
            self.manifest.update(build=copy.deepcopy(self.builder.metrics), world_explore={
                "iteration": s["iteration"], "counters": dict(s["counters"]),
                "stop_reason": s["stop_reason"],
                "world_status": copy.deepcopy(s["world_status"]),
                "elapsed_seconds": round(s["elapsed_seconds"], 3)})

    def _log_lines(self) -> List[str]:
        if not self.log_path.exists():
            return []
        return self.log_path.read_text(encoding="utf-8").splitlines()

    def _truncate_log(self, keep: int) -> None:
        lines = self._log_lines()
        if len(lines) > keep:
            self.log_path.write_text(
                "".join(l + "\n" for l in lines[:keep]), encoding="utf-8")

    def _append_log(self, records: Sequence[Mapping[str, Any]]) -> None:
        if not records:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
        self.state["log_lines"] += len(records)

    # -- stop conditions
    def _budget(self, overrides: Mapping[str, Any]) -> Dict[str, Any]:
        b = dict(self.cfg.get("budget", {}))
        b.update({k: v for k, v in overrides.items() if v is not None})
        return b

    def _stop_reason(self, graph, budget) -> Optional[str]:
        s = self.state
        if self.cfg.get("coverage", {}).get("enabled", True) \
                and self._world_status(graph)["met"]:
            return "coverage_met"
        mi = budget.get("max_iterations")
        if mi is not None and s["iteration"] >= int(mi):
            return "max_iterations"
        mw = budget.get("max_wall_seconds")
        if mw is not None and s["elapsed_seconds"] >= float(mw):
            return "max_wall_seconds"
        mc = budget.get("max_generation_calls")
        if mc is not None and s["counters"]["generation_calls"] >= int(mc):
            return "max_generation_calls"
        mf = budget.get("max_consecutive_failures")
        if mf is not None and int(mf) > 0 \
                and s.get("consecutive_failures", 0) >= int(mf):
            return "too_many_failures"
        return None

    def _world_status(self, graph):
        return world_status(graph, self.axes, self.brief,
                            world_premises(graph), self.criteria_cfg)

    # -- the loop
    def run(
        self, max_iterations: Optional[int] = None,
        max_wall_seconds: Optional[float] = None,
        max_generation_calls: Optional[int] = None,
        resume: bool = True,
    ) -> ExplorationResult:
        budget = self._budget({
            "max_iterations": max_iterations,
            "max_wall_seconds": max_wall_seconds,
            "max_generation_calls": max_generation_calls})
        self.backend.limit = (None if budget.get("max_generation_calls") is None
                              else int(budget["max_generation_calls"]))
        resumed = resume and self._load_state()
        if resumed:
            self.state["stop_reason"] = None
            self.state["consecutive_failures"] = 0  # a resume is a fresh try
        language = self.language or guess_language(" ".join(
            str(s.get("text", "")) for s in self.brief.get("statements", [])))
        graph = self.store.load_or_create(language)
        if resumed:
            # A crash between commit and checkpoint leaves one extra entity
            # and log lines the state never recorded; roll both back.
            limit = self.state["max_entity_n"]
            kept = [e for e in graph["entities"]
                    if _max_entity_n({"entities": [e]}) <= limit]
            if len(kept) != len(graph["entities"]):
                graph = {**graph, "entities": kept}
            self._truncate_log(self.state["log_lines"])
        else:
            self.state["log_lines"] = len(self._log_lines())
            self.state["max_entity_n"] = _max_entity_n(graph)
        self.store.save(graph)  # also (re)creates graph.json when absent
        self._set_phase("running")

        while True:
            self.state["world_status"] = self._world_status(graph)
            reason = self._stop_reason(graph, budget)
            if reason is None:
                started = self.clock()
                rng_before = _rng_state(self.rng)
                try:
                    graph, progressed = self._iterate(graph)
                except BudgetExhausted:
                    _set_rng_state(self.rng, rng_before)
                    reason = "max_generation_calls"
                else:
                    self.state["elapsed_seconds"] += max(0.0, self.clock() - started)
                    if not progressed:
                        reason = "frontier_exhausted"
                    else:
                        self.state["iteration"] += 1
                        self._save_state()
                        continue
            self.state["stop_reason"] = reason
            self._save_state()
            self._set_phase("completed")
            return ExplorationResult(
                stop_reason=reason, iterations=self.state["iteration"],
                graph=graph, counters=dict(self.state["counters"]),
                coverage=self._world_status(graph),
                preferences_path=self.log_path, state=copy.deepcopy(self.state))

    def _set_phase(self, status: str) -> None:
        if self.manifest is not None:
            self.manifest.set_phase_status(CHECKPOINT_PHASE, status)

    # -- one iteration
    def _iterate(self, graph: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        by_axis = bool(self.cfg["selection"].get("arm_by_axis", False))
        pairs = candidate_pairs(evaluate_frontier(graph, self.axes, self.cfg), self.cfg)
        if not pairs:
            return graph, False
        options = [(arm_key(op, item, by_axis), pair_prior(item, op, self.cfg))
                   for item, op in pairs]
        item, operator = pairs[self.bandit.select(options)]
        arm = arm_key(operator, item, by_axis)
        target = item["target"]
        it = self.state["iteration"] + 1
        context = (local_context(graph, target) if target else
                   {"language": graph["meta"]["language"], "entity_count": len(graph["entities"])})
        result, error = None, None
        records = []
        try:
            result = self._attempt(graph, operator, target, item)
            records = [{"type": "step", "iteration": it, **asdict(r)} for r in result.steps]
        except BudgetExhausted:
            raise
        except Exception as exc:
            error = {"class": type(exc).__name__, "message": str(exc)[:300]}
            logger.warning("iteration {} ({}) failed: {}", it, arm, error)
        accepted = result is not None and result.entity is not None
        reward = 0.0
        if accepted:
            # Each generated slot can be remade max_step_attempts - 1 times;
            # review can be repeated review_rounds times. Skipped slots cost nothing.
            counts = {}
            for r in result.steps:
                counts[(r.step, r.slot)] = max(counts.get((r.step, r.slot), 0), r.attempt)
            extra = sum(n - 1 for n in counts.values())
            capacity = sum(self.builder.review_rounds if step == "review" else
                           self.builder.max_step_attempts - 1 for step, slot in counts)
            reward = 1 - 0.5 * (extra / capacity if capacity else 0)
            result.entity.setdefault("scores", {})["reward"] = reward
            graph = self._commit(graph, result.entity)
            self.state["counters"]["accepted"] += 1
        else:
            self.state["counters"]["rejected"] += 1
        if result:
            counts = {}
            for r in result.steps:
                counts[(r.step, r.slot)] = max(counts.get((r.step, r.slot), 0), r.attempt)
            self.state["counters"]["rewrites"] += sum(n - 1 for n in counts.values())
        if error:
            self.state["counters"]["errors"] += 1
            self.state["consecutive_failures"] += 1
        else:
            self.state["consecutive_failures"] = 0
        records.append({
            "type": "iteration", "iteration": it, "arm": arm,
            "operator": operator, "target": target,
            "frontier": {k: item[k] for k in ("kind", "axis", "deficit")},
            "context": context, "outcome": "error" if error else "accepted" if accepted else "discarded",
            "accepted_id": result.entity["id"] if accepted else None,
            "arm_reward": round(reward, 4),
            "failure": result.failure if result else None,
            "world_status": self._world_status(graph),
            **({"error": error} if error else {})})
        self.state["world_status"] = records[-1]["world_status"]
        self.bandit.update(arm, reward)
        self._append_log(records)
        self.state["max_entity_n"] = _max_entity_n(graph)
        return graph, True

    def _attempt(self, graph, operator, target, item):
        return self.builder.build(graph, operator, target, brief=self.brief, raw_input=self.raw_input,
                                  axes=self.axes, contract=world_premises(graph),
                                  frontier_axis=item["axis"] if item["kind"] == "axis_gap" else None)

    def _commit(self, graph, entity):
        with self.store.transaction(graph["meta"]["language"]) as working:
            working["entities"].append(copy.deepcopy(entity))
        return working


# ------------------------------------------------------ preference extraction

def read_preference_log(path: Union[str, Path]) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def extract_preference_pairs(source):
    """Pair accepted and rejected outputs of the same build step and slot."""
    records = (read_preference_log(source) if isinstance(source, (str, Path)) else list(source))
    iterations = {r["iteration"]: r for r in records if r.get("type") == "iteration"}
    groups = {}
    for record in records:
        if record.get("type") == "step":
            groups.setdefault((record.get("iteration"), record["step"], record["slot"]), []).append(record)
    pairs = []
    for (iteration, step, slot), rows in groups.items():
        context = iterations.get(iteration, {})
        for chosen in rows:
            if not chosen["accepted"]:
                continue
            for rejected in rows:
                if rejected["accepted"] or chosen["output"] == rejected["output"]:
                    continue
                pairs.append({"kind": "step", "prompt": {"step": step, "slot": slot,
                    "operator": context.get("operator"), "target": context.get("target"),
                    "frontier": context.get("frontier"), "context": context.get("context")},
                    "chosen": chosen["output"], "rejected": rejected["output"],
                    "chosen_checks": chosen["checks"], "rejected_checks": rejected["checks"]})
    return pairs


# ------------------------------------------------------------- entry point

def run_world_engine(
    raw_input: Any, images: Optional[Sequence[Any]] = None,
    package_dir: Union[str, Path] = "output/world", backend: Any = None,
    budget: Optional[Mapping[str, Any]] = None, seed: int = 0, *,
    language: Optional[str] = None,
    config: Optional[Mapping[str, Any]] = None,
    operator_config: Optional[OperatorConfig] = None,
    vision_backend: Any = None, source_name: Optional[str] = None,
    resume: bool = True, render: bool = True,
    structured_max_attempts: int = 3,
    structured_max_conversions: int = 2,
    judge_backend: Any = None,
    models: Optional[Mapping[str, Any]] = None,
) -> ExplorationResult:
    """Input brief -> axes -> graph -> exploration loop, with no human input.

    ``budget`` may set ``max_iterations``, ``max_wall_seconds`` and
    ``max_generation_calls``.  Files written under ``package_dir``:
    ``input/`` (raw input, images, ``input_brief.json``),
    ``world/world_axes.json``, ``world/graph.json``,
    ``world/preferences.jsonl``,
    ``checkpoints/`` and ``run_manifest.json``.  With ``resume`` an
    existing brief, axes and checkpoint are reused instead of regenerated.
    With ``render`` (default) the world reference material is written to
    ``final/`` at the end (see :func:`src.world.render.render_world_package`).
    """
    from ..checkpoint_manager import CheckpointManager
    from ..run_manifest import RunManifest
    from .axes import WorldAxesBuilder, load_axes
    from .input import InputBriefBuilder

    if backend is None:
        raise ValueError("backend is required")
    root = Path(package_dir)
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "run_manifest.json"
    existed = manifest_path.exists()
    manifest = RunManifest(manifest_path, {
        "run_seed": seed, "engine": "world",
        "backend": getattr(backend, "backend_name", None)})
    if existed:
        manifest.reconcile_interrupted()
    if isinstance(structured_max_attempts, bool) or not isinstance(structured_max_attempts, int) or structured_max_attempts < 1:
        raise ValueError("structured.max_attempts must be a positive integer")
    if isinstance(structured_max_conversions, bool) or not isinstance(structured_max_conversions, int) or structured_max_conversions < 0:
        raise ValueError("structured.max_conversions must be a nonnegative integer")
    metrics = copy.deepcopy(manifest.data.get("structured", {}))
    for client in (backend, vision_backend, judge_backend):
        if client is not None:
            client_instance(client)._structured_metrics = metrics
    manifest.set_status("running")
    try:
        brief_path = root / "input" / "input_brief.json"
        axes_path = root / "world" / "world_axes.json"
        raw_text = ""
        if resume and brief_path.exists():
            brief = json.loads(brief_path.read_text(encoding="utf-8"))
            raw = root / "input" / (Path(source_name).name if source_name else "user_input.txt")
            raw_text = raw.read_text(encoding="utf-8") if raw.exists() else ""
        else:
            built = InputBriefBuilder(
                backend, root / "input", vision_backend=vision_backend,
                language=language, max_attempts=structured_max_attempts,
                max_conversions=structured_max_conversions,
            ).build(raw_input, images, source_name)
            brief, raw_text = built.brief, built.raw_source
        # One output language for the brief, axes and every later prompt:
        # explicit, else guessed from the input text.
        lang = language or guess_language(raw_text or " ".join(
            str(s.get("text", "")) for s in brief.get("statements", [])))
        if resume and axes_path.exists():
            axes = load_axes(axes_path)
        else:
            axes = WorldAxesBuilder(
                backend, root / "world", language=lang, max_attempts=structured_max_attempts,
                max_conversions=structured_max_conversions).build(brief).axes
        checkpoints = CheckpointManager(str(root / "checkpoints"))
        loop = ExplorationLoop(
            backend, root, brief, axes, seed=seed, language=lang, raw_input=raw_text,
            config=config, operator_config=operator_config,
            checkpoints=checkpoints, manifest=manifest,
            structured_max_attempts=structured_max_attempts,
            structured_max_conversions=structured_max_conversions,
            judge_backend=judge_backend)
        from .contract import establish_contract
        graph = loop.store.load_or_create(lang)
        try:
            stage = establish_contract(backend, graph, brief, axes, raw_input=raw_text,
                                       max_attempts=structured_max_attempts,
                                       max_conversions=structured_max_conversions,
                                       judge_backend=judge_backend)
        finally:
            loop.store.save(graph)
            if "contract_stage" in graph:
                manifest.update(world_contract=copy.deepcopy(graph["contract_stage"]))
        result = loop.run(
            max_iterations=(budget or {}).get("max_iterations"),
            max_wall_seconds=(budget or {}).get("max_wall_seconds"),
            max_generation_calls=(budget or {}).get("max_generation_calls"),
            resume=resume)
        manifest.update(structured=metrics)
        if render:
            from .render import render_world_package
            render_world_package(root, run_summary={
                "stop_reason": result.stop_reason,
                "iterations": result.iterations,
                "counters": result.counters,
                "structured": metrics,
                "models": dict(models or {}),
                "build": loop.builder.metrics,
            }, explore_config=loop.cfg)
    except BaseException as exc:
        manifest.update(structured=metrics)
        if isinstance(exc, StructuredFailure):
            manifest.update(structured_failure=exc.result.failure(exc.task))
            if render:
                report = root / "final" / "world_report.md"
                report.parent.mkdir(parents=True, exist_ok=True)
                from .contract import contract_metrics_markdown
                contract_report = contract_metrics_markdown(manifest.data.get("world_contract", {}))
                report.write_text(f"# World report\n\nRun failed: {exc}\n\n" +
                                  contract_report + metrics_markdown(metrics), encoding="utf-8")
        manifest.set_status(
            "cancelled" if isinstance(exc, KeyboardInterrupt) else "failed",
            error=None if isinstance(exc, KeyboardInterrupt) else str(exc))
        raise
    manifest.set_status("completed")
    return result


__all__ = [
    "Bandit", "BudgetExhausted", "ExplorationLoop", "ExplorationResult",
    "BREADTH_OPERATORS", "PREFERENCES_RELATIVE_PATH", "STOP_REASONS", "arm_key", "axis_consumption",
    "axis_shares", "candidate_pairs", "evaluate_frontier",
    "extract_preference_pairs", "item_prior", "load_explore_config",
    "operator_consumption", "pair_prior", "scale_needs",
    "read_preference_log", "run_world_engine",
]
