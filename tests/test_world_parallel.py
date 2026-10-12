"""Parallel entity builds in the exploration loop (fake backend only)."""

import copy

from src.llm.fake import FakeLLMBackend
from src.world.explore import ExplorationLoop, _merge_metrics, read_preference_log
from tests.test_world_explore import AXES, BRIEF, cfg, make_backend


def loop(tmp_path, backend, builds, seed=3):
    return ExplorationLoop(backend, tmp_path, BRIEF, AXES, seed=seed, language="en",
                           config=cfg(), parallel_builds=builds)


def wrapped(inner, hook):
    """Fake backend that lets hook(prompt) answer first, else defers to inner."""
    return FakeLLMBackend(lambda prompt: hook(prompt) or inner._json_source(prompt))


def seeded(tmp_path, backend, iterations=3):
    """Build a few entities one at a time so later batches have a real frontier."""
    return loop(tmp_path, backend, 1).run(max_iterations=iterations)


def test_batches_keep_ids_counters_and_log_consistent(tmp_path):
    result = loop(tmp_path, make_backend(), 3).run(max_iterations=7)
    assert result.iterations == 7
    ids = [e["id"] for e in result.graph["entities"]]
    assert len(ids) == len(set(ids)) == result.counters["accepted"]
    assert result.counters["accepted"] + result.counters["rejected"] == 7
    records = [r for r in read_preference_log(result.preferences_path) if r["type"] == "iteration"]
    assert [r["iteration"] for r in records] == list(range(1, 8))
    assert sum(r["outcome"] == "accepted" for r in records) == result.counters["accepted"]


def test_same_name_in_one_batch_is_rejected_at_commit(tmp_path):
    inner = make_backend()
    same = {"on": False}
    backend = wrapped(inner, lambda p: {"name": "Dup Name"} if same["on"] and "STEP: name\n" in p else None)
    seeded(tmp_path, backend)
    same["on"] = True
    lp = loop(tmp_path, backend, 3)
    result = lp.run(max_iterations=6)
    assert result.iterations == 6
    assert [e["name"] for e in result.graph["entities"]].count("Dup Name") == 1
    discarded = [r for r in read_preference_log(result.preferences_path)
                 if r["type"] == "iteration" and r["iteration"] > 3 and r["outcome"] == "discarded"]
    assert discarded and all(r["failure"]["step"] == "commit" for r in discarded)
    # A commit rejection moves the worker's "accepted" into the failures.
    assert lp.builder.metrics["failures_by_step"].get("commit", 0) == len(discarded)
    assert lp.builder.metrics["steps"]["commit"]["failures"] == len(discarded)
    ids = [e["id"] for e in result.graph["entities"]]
    assert len(ids) == len(set(ids))


def test_worker_metrics_are_summed(tmp_path):
    lp = loop(tmp_path, make_backend(), 3)
    result = lp.run(max_iterations=7)
    metrics = lp.builder.metrics
    assert metrics["accepted"] + metrics["failed"] == 7
    assert metrics["accepted"] == result.counters["accepted"]
    assert sum(s["calls"] for s in metrics["steps"].values()) == result.counters["generation_calls"]


def test_merge_metrics_adds_every_field():
    a = {"steps": {"name": {"calls": 2, "attempts": {"1": 1}, "reasons": {"x": {"r": 1}}, "failures": 1}},
         "accepted": 1, "failed": 0, "failures_by_step": {}}
    b = copy.deepcopy(a)
    b["failed"], b["failures_by_step"] = 1, {"name": 1}
    _merge_metrics(a, b)
    # accepted / failed / failures_by_step are tallied by _settle, not merged.
    assert a == {"steps": {"name": {"calls": 4, "attempts": {"1": 2}, "reasons": {"x": {"r": 2}}, "failures": 2}},
                 "accepted": 1, "failed": 0, "failures_by_step": {}}


def test_budget_exhausted_in_a_worker_discards_the_whole_batch(tmp_path):
    first = seeded(tmp_path, make_backend())
    lp = loop(tmp_path, make_backend(), 3)
    result = lp.run(max_iterations=6, max_generation_calls=first.counters["generation_calls"] + 10)
    assert result.stop_reason == "max_generation_calls"
    assert result.iterations == first.iterations
    assert len(result.graph["entities"]) == len(first.graph["entities"])
    records = [r for r in read_preference_log(result.preferences_path) if r["type"] == "iteration"]
    assert len(records) == first.iterations
