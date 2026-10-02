"""Autonomous exploration loop for the world graph.

One iteration: evaluate the graph into frontier items, pick one
(frontier item x operator) pair with a bandit, generate candidates, score
them, accept the best passing one (or critique and rewrite failing ones),
and commit the result with a checkpoint.  No step asks a human anything.

Bandit arms are ``operator|frontier-kind`` (optionally ``|axis``).  An arm's
value is its mean reward (with a prior), plus a UCB1 exploration bonus or a
Thompson sample; the frontier item adds a prior from its deficit and its
axis weight.  All randomness comes from one seeded ``random.Random`` whose
state is checkpointed, so a resumed run continues exactly where it stopped.

Every candidate, its scores, deductions, decision and rewrite lineage is
appended to ``world/preferences.jsonl``; :func:`extract_preference_pairs`
turns that log into (prompt, chosen, rejected) records.
"""

from __future__ import annotations

import copy
import json
import math
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union,
)

import yaml
from loguru import logger

from .graph import (
    SCALE_RANK, SCALES, GraphStore, guess_language, local_context,
)
from .operators import OperatorConfig, OperatorError, OperatorRunner
from .reward import RewardVerifier
from .verify import ContrastProvider, entity_text

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
DEFAULT_EXPLORE_PATH = CONFIG_DIR / "world" / "explore.yaml"
PREFERENCES_RELATIVE_PATH = Path("world") / "preferences.jsonl"
CHECKPOINT_PHASE = "world_explore"
STATE_VERSION = 1

STOP_REASONS = (
    "coverage_met", "max_iterations", "max_wall_seconds",
    "max_generation_calls", "frontier_exhausted", "too_many_failures",
)


NO_CANDIDATES = object()  # the operator returned nothing usable


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
    """Shortage per scale in [0, 1]: how far below ``min_entities_per_scale``.

    Only scales down to ``coverage.depth`` count; deeper ones need nothing.
    """
    c = cfg.get("coverage", {})
    depth = SCALE_RANK[c.get("depth", "district")]
    want = max(1, int(c.get("min_entities_per_scale", 1)))
    counts = {s: 0 for s in SCALES}
    for e in graph.get("entities", []):
        if e.get("scale") in counts:
            counts[e["scale"]] += 1
    return {s: (max(0, want - counts[s]) / want if SCALE_RANK[s] <= depth
                else 0.0) for s in SCALES}


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
    ccfg = cfg.get("coverage", {})
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

    used = axis_consumption(graph, axes)
    min_axis = int(ccfg.get("min_axis_entities", 1))
    n = len(entities)
    for axis_id in sorted(used):
        expected = max(float(min_axis), shares.get(axis_id, 0.0) * n)
        if used[axis_id] < expected:
            target = _axis_target(graph, axis_id, needs)
            if target is not None:
                add("axis_gap", target, (expected - used[axis_id]) / expected,
                    axis_id, shares.get(axis_id, 0.0) / top if top > 0 else 0.0)

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
    return [(dict(i), op) for i in items for op in ops.get(i["kind"], [])
            if not (op == "zoom" and i.get("target_scale") == "detail")]


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
    wd = float(sel.get("depth_weight", 0.0))
    need = item.get("depth_need")
    if wd <= 0 or not need:
        return base
    w = float(sel.get("deficit_weight", 0.7)) + float(sel.get("axis_weight", 0.3))
    depth = float(need["below" if operator == "zoom" else "same"])
    return (base * w + wd * depth) / (w + wd)


# ---------------------------------------------------------------- coverage

def mean_reward(graph: Mapping[str, Any]) -> Optional[float]:
    vals = [e["scores"]["reward"] for e in graph.get("entities", [])
            if isinstance((e.get("scores") or {}).get("reward"), (int, float))]
    return sum(vals) / len(vals) if vals else None


def coverage_status(
    graph: Mapping[str, Any],
    axes: Optional[Sequence[Mapping[str, Any]]],
    cfg: Mapping[str, Any],
) -> Dict[str, Any]:
    c = cfg.get("coverage", {})
    used = axis_consumption(graph, axes)
    axes_ok = all(v >= int(c.get("min_axis_entities", 1)) for v in used.values())
    depth = SCALE_RANK[c.get("depth", "district")]
    per_scale = {s: 0 for s in SCALES[: depth + 1]}
    for e in graph.get("entities", []):
        if e.get("scale") in per_scale:
            per_scale[e["scale"]] += 1
    scales_ok = all(v >= int(c.get("min_entities_per_scale", 1))
                    for v in per_scale.values())
    mr = mean_reward(graph)
    reward_ok = mr is not None and mr >= float(c.get("target_mean_reward", 0.0))
    return {"met": bool(axes_ok and scales_ok and reward_ok
                        and graph.get("entities")),
            "axes_ok": axes_ok, "scales_ok": scales_ok,
            "reward_ok": reward_ok, "mean_reward": mr,
            "axis_entities": used, "scale_entities": per_scale}


# ----------------------------------------------------------------- the loop

class _CountingBackend:
    """Counts generation calls and enforces the call budget."""

    def __init__(self, inner: Any, counters: Dict[str, int]) -> None:
        self._inner = inner
        self._counters = counters
        self.limit: Optional[int] = None

    def _tick(self) -> None:
        if self.limit is not None and self._counters["generation_calls"] >= self.limit:
            raise BudgetExhausted("generation-call budget exhausted")
        self._counters["generation_calls"] += 1

    def generate_json(self, *args: Any, **kwargs: Any) -> Any:
        self._tick()
        return self._inner.generate_json(*args, **kwargs)

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
        verifier: Optional[RewardVerifier] = None,
        checkpoints: Any = None,
        manifest: Any = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.package_dir = Path(package_dir)
        self.brief = brief
        self.axes = list(axes)
        self.seed = seed
        self.cfg = dict(config) if config is not None else load_explore_config()
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
        self.runner = OperatorRunner(self.backend, operator_config)
        self.provider = ContrastProvider(
            self.runner, self.package_dir,
            int(self.cfg["generation"].get("contrast_count", 3)))
        self.verifier = verifier or RewardVerifier()
        if self.verifier.contrasts is None:
            self.verifier.contrasts = self.provider  # genericity always on
        if getattr(self.verifier, "judge", None) is not None:
            # Judge calls spend the same generation-call budget.
            self.verifier.judge.backend = self.backend
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
        _set_rng_state(self.rng, data["rng"])
        return True

    def _save_state(self) -> None:
        s = self.state
        s["bandit"] = self.bandit.to_dict()
        s["rng"] = _rng_state(self.rng)
        self.checkpoints.save_checkpoint(CHECKPOINT_PHASE, copy.deepcopy(s))
        if self.manifest is not None:
            self.manifest.update(world_explore={
                "iteration": s["iteration"], "counters": dict(s["counters"]),
                "stop_reason": s["stop_reason"],
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
                and coverage_status(graph, self.axes, self.cfg)["met"]:
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
                coverage=coverage_status(graph, self.axes, self.cfg),
                preferences_path=self.log_path, state=copy.deepcopy(self.state))

    def _set_phase(self, status: str) -> None:
        if self.manifest is not None:
            self.manifest.set_phase_status(CHECKPOINT_PHASE, status)

    # -- one iteration
    def _iterate(self, graph: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        gen = self.cfg["generation"]
        by_axis = bool(self.cfg["selection"].get("arm_by_axis", False))
        pairs = candidate_pairs(evaluate_frontier(graph, self.axes, self.cfg), self.cfg)
        if not pairs:
            return graph, False
        options = [(arm_key(op, item, by_axis), pair_prior(item, op, self.cfg))
                   for item, op in pairs]
        item, operator = pairs[self.bandit.select(options)]
        arm = arm_key(operator, item, by_axis)
        target = item["target"]
        gen_axes = self.axes
        if item["kind"] == "axis_gap":
            gen_axes = [a for a in self.axes if a["id"] == item["axis"]] or self.axes

        it = self.state["iteration"] + 1
        context = (local_context(graph, target) if target else
                   {"language": graph["meta"]["language"],
                    "entity_count": len(graph["entities"])})
        records: List[Dict[str, Any]] = []
        decisions: Dict[str, str] = {}

        def score(cands, rnd, revision_of=None, findings=None, siblings=None):
            rows = []
            for idx, c in enumerate(cands):
                try:
                    res = self.verifier.verify(
                        graph, c, brief=self.brief, axes=self.axes,
                        store=True,
                        siblings=cands if siblings is None else siblings)
                except BudgetExhausted:
                    raise
                except Exception as exc:  # skip this candidate only
                    logger.warning(
                        f"candidate {idx} could not be verified: "
                        f"{type(exc).__name__}: {exc}")
                    self.state["counters"]["errors"] += 1
                    records.append({
                        "type": "candidate_error", "iteration": it,
                        "round": rnd, "index": idx, "operator": operator,
                        "error": {"class": type(exc).__name__,
                                  "message": str(exc)[:300]}})
                    continue
                cid = f"i{it}.r{rnd}.c{idx}"
                records.append({
                    "type": "candidate", "id": cid, "iteration": it,
                    "round": rnd, "index": idx, "arm": arm,
                    "operator": operator, "target": target,
                    "candidate": copy.deepcopy(c["entity"]),
                    "result": res.to_dict(), "revision_of": revision_of,
                    "findings": findings or [], "decision": "rejected"})
                decisions[cid] = "rejected"
                rows.append({"id": cid, "cand": c, "res": res})
            return rows

        def best_of(rows):
            return max(rows, key=lambda r: (r["res"].passed, r["res"].reward))

        accepted = None
        error: Optional[Dict[str, str]] = None
        try:
            accepted = self._attempt(
                graph, operator, target, gen, gen_axes, score, best_of)
            if accepted is not None and accepted is not NO_CANDIDATES:
                graph = self._commit(graph, accepted["cand"]["entity"])
        except BudgetExhausted:
            raise
        except Exception as exc:  # bad model data or a backend failure
            error = {"class": type(exc).__name__, "message": str(exc)[:300]}
            logger.warning(
                f"iteration {it} ({arm}) failed: "
                f"{error['class']}: {error['message']}")
            accepted = None
        if error is not None:
            self.state["counters"]["errors"] += 1
            self.state["consecutive_failures"] += 1
        else:
            self.state["consecutive_failures"] = 0
        if accepted is NO_CANDIDATES:
            accepted = None
            self.state["counters"]["no_candidates"] += 1
            self.state["counters"]["rejected"] += 1
        elif accepted is not None:
            decisions[accepted["id"]] = "accepted"
            arm_reward = accepted["res"].reward
            self.state["counters"]["accepted"] += 1
        else:
            self.state["counters"]["rejected"] += 1
        if accepted is None:
            arm_reward = float(gen.get("discard_reward", 0.0))
        for r in records:
            if "id" in r:
                r["decision"] = decisions[r["id"]]
        records.append({
            "type": "iteration", "iteration": it, "arm": arm,
            "operator": operator, "target": target,
            "frontier": {k: item[k] for k in ("kind", "axis", "deficit")},
            "context": context,
            "outcome": ("error" if error else
                        "accepted" if accepted else "discarded"),
            "accepted_id": accepted["id"] if accepted else None,
            "arm_reward": round(arm_reward, 4),
            **({"error": error} if error else {})})
        self.bandit.update(arm, arm_reward)
        self._append_log(records)
        self.state["max_entity_n"] = _max_entity_n(graph)
        return graph, True

    def _attempt(self, graph, operator, target, gen, gen_axes, score, best_of):
        """Generate, score and rewrite; return the accepted row, ``None``
        (nothing passed) or :data:`NO_CANDIDATES`."""
        try:
            cands = self.runner.run(
                operator, graph, target, int(gen["candidates"]),
                brief=self.brief, axes=gen_axes)
        except OperatorError:
            cands = []
        if not cands:
            return NO_CANDIDATES
        rows = score(cands, 0)
        if not rows:
            return None
        base = best_of(rows)
        if base["res"].passed:
            return base
        for rnd in range(1, int(gen["max_rewrites"]) + 1):
            findings = self._findings(base["res"], int(gen["max_findings"]))
            revised = self.runner.revise(
                base["cand"], findings, graph,
                brief=self.brief, axes=gen_axes)
            self.state["counters"]["rewrites"] += 1
            if revised is None:
                break
            new_rows = score([revised], rnd, base["id"], findings,
                             siblings=[c for c in cands
                                       if c is not base["cand"]])
            if not new_rows:
                break
            row = new_rows[0]
            if row["res"].passed:
                return row
            if row["res"].reward > base["res"].reward:
                base = row
        return None

    @staticmethod
    def _findings(result, limit: int) -> List[Dict[str, Any]]:
        ded = sorted(result.deductions, key=lambda d: -d.penalty)[:limit]
        out = [{"field": d.field, "code": d.code, "message": d.message}
               for d in ded]
        if not out:
            out = [{"field": "entity", "code": "below_threshold",
                    "message": "overall reward is below the threshold; make "
                               "it more specific and better grounded"}]
        return out

    def _commit(self, graph: Dict[str, Any], entity: Mapping[str, Any]):
        with self.store.transaction(graph["meta"]["language"]) as working:
            working["entities"].append(copy.deepcopy(dict(entity)))
        return working


# ------------------------------------------------------ preference extraction

def read_preference_log(path: Union[str, Path]) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def _rank(rec: Mapping[str, Any]) -> Tuple[bool, float]:
    return (bool(rec["result"]["passed"]), float(rec["result"]["reward"]))


def extract_preference_pairs(
    source: Union[str, Path, Sequence[Mapping[str, Any]]],
    min_margin: float = 0.0,
) -> List[Dict[str, Any]]:
    """Return ``(prompt, chosen, rejected)`` records for DPO-style training.

    Within each generation round the best candidate (passing first, then
    higher reward) is *chosen* over every strictly worse sibling; a rewrite
    that outranks the draft it revised is *chosen* over that draft.  The
    prompt holds the operator, target, frontier kind and bounded context.
    ``min_margin`` drops pairs whose reward gap is smaller.
    """
    records = (read_preference_log(source)
               if isinstance(source, (str, Path)) else list(source))
    its = {r["iteration"]: r for r in records if r.get("type") == "iteration"}
    cands = [r for r in records if r.get("type") == "candidate"]
    by_id = {c["id"]: c for c in cands}

    def prompt(c, findings=None):
        it = its.get(c["iteration"], {})
        p = {"operator": c["operator"], "target": c["target"],
             "frontier_kind": (it.get("frontier") or {}).get("kind"),
             "axis": (it.get("frontier") or {}).get("axis"),
             "context": it.get("context")}
        if findings:
            p["revision_findings"] = findings
        return p

    def pair(kind, win, lose, findings=None):
        return {
            "kind": kind, "prompt": prompt(win, findings),
            "chosen": win["candidate"], "rejected": lose["candidate"],
            "chosen_text": entity_text(win["candidate"]),
            "rejected_text": entity_text(lose["candidate"]),
            "chosen_id": win["id"], "rejected_id": lose["id"],
            "chosen_reward": win["result"]["reward"],
            "rejected_reward": lose["result"]["reward"],
            "chosen_deductions": win["result"]["deductions"],
            "rejected_deductions": lose["result"]["deductions"]}

    pairs: List[Dict[str, Any]] = []
    groups: Dict[Tuple[int, int], List[Mapping[str, Any]]] = {}
    for c in cands:
        groups.setdefault((c["iteration"], c["round"]), []).append(c)
    for key in sorted(groups):
        group = groups[key]
        if len(group) < 2:
            continue
        top = max(group, key=lambda c: _rank(c))
        for c in group:
            if c is top or _rank(c) >= _rank(top):
                continue
            if top["result"]["reward"] - c["result"]["reward"] >= min_margin:
                pairs.append(pair("group", top, c))
    for c in cands:
        base = by_id.get(c.get("revision_of") or "")
        if base is not None and _rank(c) > _rank(base) and \
                c["result"]["reward"] - base["result"]["reward"] >= min_margin:
            pairs.append(pair("revision", c, base, c.get("findings")))
    return pairs


# ------------------------------------------------------------- entry point

def run_world_engine(
    raw_input: Any, images: Optional[Sequence[Any]] = None,
    package_dir: Union[str, Path] = "output/world", backend: Any = None,
    budget: Optional[Mapping[str, Any]] = None, seed: int = 0, *,
    language: Optional[str] = None,
    config: Optional[Mapping[str, Any]] = None,
    operator_config: Optional[OperatorConfig] = None,
    verifier: Optional[RewardVerifier] = None,
    vision_backend: Any = None, source_name: Optional[str] = None,
    resume: bool = True, render: bool = True,
) -> ExplorationResult:
    """Input brief -> axes -> graph -> exploration loop, with no human input.

    ``budget`` may set ``max_iterations``, ``max_wall_seconds`` and
    ``max_generation_calls``.  Files written under ``package_dir``:
    ``input/`` (raw input, images, ``input_brief.json``),
    ``world/world_axes.json``, ``world/graph.json``,
    ``world/contrasts.json``, ``world/preferences.jsonl``,
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
    manifest.set_status("running")
    try:
        brief_path = root / "input" / "input_brief.json"
        axes_path = root / "world" / "world_axes.json"
        raw_text = ""
        if resume and brief_path.exists():
            brief = json.loads(brief_path.read_text(encoding="utf-8"))
            raw = root / "input" / "user_input.txt"
            raw_text = raw.read_text(encoding="utf-8") if raw.exists() else ""
        else:
            built = InputBriefBuilder(
                backend, root / "input", vision_backend=vision_backend,
                language=language,
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
                backend, root / "world", language=lang).build(brief).axes
        checkpoints = CheckpointManager(str(root / "checkpoints"))
        loop = ExplorationLoop(
            backend, root, brief, axes, seed=seed, language=lang,
            config=config, operator_config=operator_config,
            verifier=verifier, checkpoints=checkpoints, manifest=manifest)
        result = loop.run(
            max_iterations=(budget or {}).get("max_iterations"),
            max_wall_seconds=(budget or {}).get("max_wall_seconds"),
            max_generation_calls=(budget or {}).get("max_generation_calls"),
            resume=resume)
        if render:
            from .render import render_world_package
            render_world_package(root, run_summary={
                "stop_reason": result.stop_reason,
                "iterations": result.iterations,
                "counters": result.counters,
            }, explore_config=loop.cfg)
    except BaseException as exc:
        manifest.set_status(
            "cancelled" if isinstance(exc, KeyboardInterrupt) else "failed",
            error=None if isinstance(exc, KeyboardInterrupt) else str(exc))
        raise
    manifest.set_status("completed")
    return result


__all__ = [
    "Bandit", "BudgetExhausted", "ExplorationLoop", "ExplorationResult",
    "PREFERENCES_RELATIVE_PATH", "STOP_REASONS", "arm_key", "axis_consumption",
    "axis_shares", "candidate_pairs", "coverage_status", "evaluate_frontier",
    "NO_CANDIDATES", "extract_preference_pairs", "item_prior", "load_explore_config",
    "mean_reward", "pair_prior", "scale_needs", "read_preference_log", "run_world_engine",
]
