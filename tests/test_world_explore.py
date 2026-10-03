"""Tests for the autonomous exploration loop (fake backend only)."""

import builtins
import json
import random
import re
import zlib
from pathlib import Path

import pytest

from src.llm.fake import FakeLLMBackend
from src.world.explore import (
    Bandit, ExplorationLoop, STOP_REASONS, arm_key, candidate_pairs,
    coverage_status, evaluate_frontier, extract_preference_pairs,
    load_explore_config, read_preference_log, run_world_engine,
)
from src.world.graph import make_entity, new_graph, validate_graph

CONFIG = Path(__file__).resolve().parent.parent / "config"

BRIEF = {"statements": [
    {"id": "s1", "text": "alpha rule", "quote": "alpha rule"},
    {"id": "s2", "text": "beta supply", "quote": "beta supply"}]}
AXES = [{"id": "a1", "name": "One", "meaning": "first", "weight": 0.6},
        {"id": "a2", "name": "Two", "meaning": "second", "weight": 0.3},
        {"id": "a3", "name": "Three", "meaning": "third", "weight": 0.1}]
RAW = "alpha rule. beta supply."

SYL = ["ka", "mo", "ri", "tu", "ven", "sol", "dar", "pe", "lu", "zan", "ith",
       "bro", "fe", "qui", "nol", "sam", "ort", "wy", "dek", "hal"]
GENERIC_SUMMARY = ("The organization is an important body that supports "
                   "various activities of the community in many ways.")
GENERIC_FACTS = [
    {"kind": "proper_noun", "text": "Guild Hall"},
    {"kind": "number", "text": "50 members"},
    {"kind": "object", "text": "oak table"},
    {"kind": "object", "text": "iron lamp"}]
SYNTHETIC_PREMISES = {
    "calendar": {"name": "Vela Count", "origin": "first quota agreement",
                 "markers": ["Vela Count"]},
    "technology": {"description": "Seals and hand-written ledgers; no automated records",
                   "capabilities": ["seal", "ledger"], "units": ["term", "quota"]}}

OPS = {"Propose": "premise", "Add sibling": "expand", "Add child": "zoom",
       "Explain why": "cause", "Describe how": "perspective",
       "Link something": "history", "Create a document": "document"}


def _words(rng, k):
    return ["".join(rng.choice(SYL) for _ in range(rng.randint(2, 3)))
            for _ in range(k)]


def _specific(rng, ids, axis_ids):
    w = _words(rng, 24)
    return {
        "type": "concept", "name": f"{w[0].title()} {w[1].title()}",
        "axes": [axis_ids[rng.randrange(len(axis_ids))]] if axis_ids else [],
        "summary": " ".join(w[2:14]) + ".",
        "facts": [
            {"kind": "proper_noun", "text": f"{w[14].title()} {w[15].title()}"},
            {"kind": "number", "text": f"{w[16]} quota {rng.randint(2, 900)}"},
            {"kind": "object", "text": f"{w[17]} {w[18]} seal"},
            {"kind": "object", "text": f"{w[19]} {w[20]} ledger"},
            {"kind": "period", "text": f"{w[21]} term {rng.randint(2, 90)}"}],
        "statement_ids": ids[:1], "derived_from": [], "reason": ""}


def _generic(i, ids):
    return {"type": "concept", "name": f"Central Guild {chr(65 + i)}",
            "axes": [], "summary": GENERIC_SUMMARY,
            "facts": GENERIC_FACTS, "statement_ids": ids[:1],
            "derived_from": [], "reason": ""}


def make_backend(generic_ops=(), always_generic=False, fail_after=None):
    """Prompt-dependent synthetic backend; deterministic per prompt."""
    calls = {"n": 0}

    def respond(prompt):
        calls["n"] += 1
        if fail_after is not None and calls["n"] > fail_after:
            # A user interrupt / kill: unlike a backend error, it is never
            # swallowed by the loop's per-iteration failure handling.
            raise KeyboardInterrupt("interrupted")
        if prompt.startswith("SOURCE MATERIAL"):
            return {"statements": [
                {"text": "alpha rule", "quote": "alpha rule"},
                {"text": "beta supply", "quote": "beta supply"}],
                "open_questions": [], "constraints": []}
        if "DOMAIN CATALOG" in prompt:
            return {"axes": [{"domain": "resources_economy", "meaning": "m",
                              "weight": 0.9, "statement_ids": ["s1"]}]}
        m = re.search(r"that you may tag:\n(.*?)\n\n", prompt, re.S)
        axis_ids = [l.split(":")[0] for l in m.group(1).splitlines()
                    if ":" in l] if m else []
        m = re.search(r"that you may cite:\n(.*?)\n\n", prompt, re.S)
        ids = [l.split(":")[0] for l in m.group(1).splitlines()
               if re.match(r"s\d+:", l)] if m else []
        ids = ids or ["s1"]
        rng = random.Random(zlib.crc32(prompt.encode("utf-8")))
        def with_contract(rows):
            for row in rows:
                row["world_premises"] = SYNTHETIC_PREMISES
                row["reason"] = "Quota agreements determine record cycles and recording methods"
            return {"candidates": rows}

        if "REVIEW FINDINGS" in prompt:
            if always_generic:
                return with_contract([_generic(0, ids)])
            return with_contract([_specific(rng, ids, axis_ids)])
        n = int(re.search(r"exactly (\d+) candidates", prompt).group(1))
        task = re.search(r"TASK: (.*)", prompt).group(1)
        op = next(v for k, v in OPS.items() if task.startswith(k))
        no_input = ids == ["s1"] and "(none)" in prompt
        if no_input or always_generic or op in generic_ops:
            return with_contract([_generic(i, ids) for i in range(n)])
        return with_contract([_specific(rng, ids, axis_ids) for _ in range(n)])

    backend = FakeLLMBackend(respond)
    backend.calls = calls
    return backend


def cfg(**over):
    c = load_explore_config()
    c["budget"]["max_iterations"] = 12
    c["coverage"]["enabled"] = False
    for k, v in over.items():
        c[k].update(v)
    return c


def loop(tmp_path, backend=None, config=None, seed=3, **kw):
    return ExplorationLoop(
        backend or make_backend(), tmp_path, BRIEF, AXES, seed=seed,
        language="en", config=config or cfg(), **kw)


# ----------------------------------------------------------------- frontier

PROV = {"statement_ids": ["s1"], "derived_from": [], "reason": ""}


def small_graph():
    g = new_graph("en")
    g["entities"] = [
        make_entity("e1", "place", "Root", "world", axes=["a1"], summary="r",
                    provenance=PROV),
        make_entity("e2", "place", "Mid", "region", axes=["a1"], parent="e1",
                    summary="m", provenance=PROV,
                    facts=[{"kind": "number", "text": "n 1",
                            "provenance": PROV}] * 3,
                    scores={"genericity": 0.2, "specificity": 0.9}),
        make_entity("e4", "place", "Leaf", "region", axes=["a1"], parent="e1",
                    summary="l", provenance=PROV),
        make_entity("e3", "place", "Low", "detail", axes=["a1"], parent="e2",
                    summary="d", provenance=PROV),
    ]
    return g


def test_empty_graph_frontier_is_premise_on_world():
    items = evaluate_frontier(new_graph("en"), AXES, load_explore_config())
    assert [i["kind"] for i in items] == ["empty"]
    pairs = candidate_pairs(items, load_explore_config())
    assert [op for _, op in pairs] == ["premise"]


def test_frontier_kinds_and_axis_budget():
    c = load_explore_config()
    items = evaluate_frontier(small_graph(), AXES, c)
    kinds = {}
    for i in items:
        kinds.setdefault(i["kind"], []).append(i)
    assert {i["target"] for i in kinds["unexpanded"]} == {"e4"}
    assert "e3" not in {i["target"] for i in kinds["unexpanded"]}  # detail
    assert {"e1", "e2", "e3", "e4"} <= {i["target"] for i in kinds["uncaused"]}
    assert {"e1", "e3", "e4"} <= {i["target"] for i in kinds["thin"]}
    assert "e2" not in {i["target"] for i in kinds["thin"]}
    assert [i["target"] for i in kinds["low_score"]] == ["e2"]
    # Every axis with no entity is under-served; its share raises the prior.
    gaps = {i["axis"]: i for i in kinds["axis_gap"]}
    assert set(gaps) == {"a2", "a3"}
    assert gaps["a2"]["axis_share"] > gaps["a3"]["axis_share"]


def test_cause_link_removes_uncaused_item():
    g = small_graph()
    g["entities"].append(make_entity(
        "e4", "concept", "Why", "region", axes=["a1"], parent="e1",
        relations=[{"type": "causes", "target": "e2"}], summary="c",
        provenance=PROV))
    items = evaluate_frontier(g, AXES, load_explore_config())
    unc = {i["target"] for i in items if i["kind"] == "uncaused"}
    assert "e2" not in unc and "e4" not in unc


def test_coverage_status_requires_axes_scales_and_reward():
    c = load_explore_config()
    st = coverage_status(small_graph(), AXES, c)
    assert not st["met"] and not st["axes_ok"] and not st["scales_ok"]


# ------------------------------------------------------------------- bandit

@pytest.mark.parametrize("strategy", ["ucb1", "thompson"])
def test_bandit_prefers_arms_with_higher_reward(strategy):
    rng = random.Random(1)
    b = Bandit({"strategy": strategy, "exploration": 0.5, "epsilon": 0.0,
                "prior_mean": 0.5, "prior_strength": 1.0,
                "item_prior_weight": 0.0}, rng)
    truth = {"good": 0.9, "mid": 0.5, "bad": 0.1}
    picks = {k: 0 for k in truth}
    for step in range(300):
        idx = b.select([(k, 0.0) for k in truth])
        key = list(truth)[idx]
        picks[key] += 1
        b.update(key, truth[key])
    assert picks["good"] > picks["mid"] > picks["bad"]
    assert picks["good"] > 150
    assert b.mean("good") > b.mean("bad")


def test_bandit_item_prior_breaks_ties_and_state_round_trips():
    rng = random.Random(2)
    b = Bandit({"exploration": 0.0, "epsilon": 0.0, "item_prior_weight": 1.0},
               rng)
    assert b.select([("x", 0.1), ("y", 0.9)]) == 1
    b.update("x", 0.8)
    b2 = Bandit({}, rng, b.to_dict())
    assert b2.arms == b.arms and b2.total == 1


def test_arm_key_optionally_includes_axis():
    item = {"kind": "axis_gap", "axis": "a2"}
    assert arm_key("expand", item, False) == "expand|axis_gap"
    assert arm_key("expand", item, True) == "expand|axis_gap|a2"


# --------------------------------------------------------------- the loop

def test_loop_runs_without_human_input_to_coverage(tmp_path, monkeypatch):
    def no_input(*a, **k):
        raise AssertionError("the loop must never ask for input")
    monkeypatch.setattr(builtins, "input", no_input)
    c = load_explore_config()
    c["budget"]["max_iterations"] = 80
    c["coverage"].update({"depth": "settlement", "min_entities_per_scale": 2,
                          "target_mean_reward": 0.6})
    result = loop(tmp_path, config=c).run()
    assert result.stop_reason == "coverage_met", result.stop_reason
    assert result.stop_reason in STOP_REASONS
    assert result.coverage["met"]
    graph = json.loads((tmp_path / "world" / "graph.json").read_text("utf-8"))
    assert validate_graph(graph, AXES, BRIEF) == []
    # Persistence sorts ids lexically; e10 can precede the first accepted e3.
    first = min(graph["entities"], key=lambda e: int(e["id"][1:]))
    assert first["scale"] == "world"  # premise first
    log = read_preference_log(tmp_path / "world" / "preferences.jsonl")
    assert any(r["type"] == "candidate" and r["decision"] == "accepted"
               for r in log)
    # genericity is on inside the loop and contrasts are cached in the package
    accepted = [r for r in log if r.get("decision") == "accepted"]
    assert all("genericity" in r["result"]["scores"] for r in accepted)
    assert (tmp_path / "world" / "contrasts.json").exists()
    assert all(0 <= e["scores"]["reward"] <= 1 for e in graph["entities"])


def test_critique_and_rewrite_path(tmp_path):
    backend = make_backend(generic_ops={"premise", "zoom", "cause"})
    result = loop(tmp_path, backend, cfg(budget={"max_iterations": 6})).run()
    log = read_preference_log(tmp_path / "world" / "preferences.jsonl")
    revised = [r for r in log if r["type"] == "candidate" and r["round"] >= 1]
    assert revised and result.counters["rewrites"] >= 1
    first = next(r for r in revised)
    base = next(r for r in log if r.get("id") == first["revision_of"])
    assert not base["result"]["passed"] and base["decision"] == "rejected"
    assert first["result"]["passed"] and first["decision"] == "accepted"
    assert any(f["code"] == "resembles_prior" for f in first["findings"])
    assert any("REVIEW FINDINGS" in p and "resembles_prior" in p
               for p in backend.json_prompts)
    assert first["result"]["reward"] > base["result"]["reward"]


def test_discarded_iteration_records_low_reward_for_the_arm(tmp_path):
    c = cfg(budget={"max_iterations": 3}, generation={"max_rewrites": 1})
    lp = loop(tmp_path, make_backend(always_generic=True), c)
    result = lp.run()
    assert result.counters["accepted"] == 0 and result.counters["rejected"] == 3
    log = read_preference_log(tmp_path / "world" / "preferences.jsonl")
    its = [r for r in log if r["type"] == "iteration"]
    assert all(r["outcome"] == "discarded" and r["arm_reward"] == 0.0
               for r in its)
    assert all(lp.bandit.mean(a) < 0.5 for a in lp.bandit.arms)
    assert json.loads((tmp_path / "world" / "graph.json").read_text()
                      )["entities"] == []


def test_preferences_yield_chosen_rejected_pairs(tmp_path):
    backend = make_backend(generic_ops={"premise", "cause"})
    loop(tmp_path, backend, cfg(budget={"max_iterations": 8})).run()
    path = tmp_path / "world" / "preferences.jsonl"
    pairs = extract_preference_pairs(path)
    assert pairs
    kinds = {p["kind"] for p in pairs}
    assert "revision" in kinds
    for p in pairs:
        assert p["chosen_reward"] >= p["rejected_reward"]
        assert p["chosen"] != p["rejected"] and p["chosen_text"]
        assert p["prompt"]["operator"] and "context" in p["prompt"]
    rev = next(p for p in pairs if p["kind"] == "revision")
    assert rev["prompt"]["revision_findings"]
    assert extract_preference_pairs(path, min_margin=2.0) == []


def test_group_pairs_rank_by_pass_then_reward_and_respect_margin():
    def rec(cid, passed, reward):
        return {"type": "candidate", "id": cid, "iteration": 1, "round": 0,
                "operator": "expand", "target": "e1", "revision_of": None,
                "candidate": {"name": cid, "summary": cid, "facts": []},
                "result": {"passed": passed, "reward": reward,
                           "deductions": []}}
    records = [
        {"type": "iteration", "iteration": 1, "frontier": {
            "kind": "unexpanded", "axis": None}, "context": {"k": 1}},
        rec("a", True, 0.8), rec("b", False, 0.9), rec("c", False, 0.4)]
    pairs = extract_preference_pairs(records)
    assert [(p["chosen_id"], p["rejected_id"]) for p in pairs] == [
        ("a", "c")]  # a-over-b is dropped: its reward gap is negative
    assert pairs[0]["prompt"]["context"] == {"k": 1}
    assert extract_preference_pairs(records, min_margin=0.5) == []


def test_resume_after_interruption_matches_uninterrupted_run(tmp_path):
    c = cfg(budget={"max_iterations": 9})
    full = tmp_path / "full"
    loop(full, config=c).run()

    part = tmp_path / "part"
    with pytest.raises(KeyboardInterrupt):
        loop(part, make_backend(fail_after=10), c).run()
    mid = json.loads((part / "world" / "graph.json").read_text())
    assert 0 < len(mid["entities"])
    resumed = loop(part, config=c).run()
    assert resumed.iterations == 9
    for rel in ("world/graph.json", "world/preferences.jsonl"):
        assert (full / rel).read_text() == (part / rel).read_text(), rel


def test_resume_rolls_back_commit_without_checkpoint(tmp_path, monkeypatch):
    c = cfg(budget={"max_iterations": 7})
    full = tmp_path / "full"
    loop(full, config=c).run()

    part = tmp_path / "part"
    original = ExplorationLoop._save_state
    seen = {"n": 0}

    def flaky(self):
        seen["n"] += 1
        if seen["n"] == 4:  # graph + log written, state not
            raise RuntimeError("crash before checkpoint")
        return original(self)

    monkeypatch.setattr(ExplorationLoop, "_save_state", flaky)
    with pytest.raises(RuntimeError):
        loop(part, config=c).run()
    monkeypatch.setattr(ExplorationLoop, "_save_state", original)
    loop(part, config=c).run()
    for rel in ("world/graph.json", "world/preferences.jsonl"):
        assert (full / rel).read_text() == (part / rel).read_text(), rel


def test_same_seed_same_result_and_budget_can_be_extended(tmp_path):
    a = loop(tmp_path / "a", config=cfg(budget={"max_iterations": 5})).run()
    b = loop(tmp_path / "b", config=cfg(budget={"max_iterations": 5})).run()
    assert a.graph == b.graph and a.state["bandit"] == b.state["bandit"]
    more = loop(tmp_path / "a", config=cfg(budget={"max_iterations": 8})).run()
    assert more.iterations == 8 and more.stop_reason == "max_iterations"
    assert len(more.graph["entities"]) >= len(a.graph["entities"])


def test_generation_call_and_wall_time_budgets(tmp_path):
    r = loop(tmp_path / "calls", config=cfg(budget={"max_iterations": 50})
             ).run(max_generation_calls=12)
    assert r.stop_reason == "max_generation_calls"
    assert r.counters["generation_calls"] <= 12

    ticks = iter(range(0, 1000, 10))
    r2 = loop(tmp_path / "wall", config=cfg(budget={"max_iterations": 50}),
              clock=lambda: float(next(ticks))
              ).run(max_wall_seconds=25)
    assert r2.stop_reason == "max_wall_seconds"
    assert 1 <= r2.iterations <= 4


def test_stop_reason_is_recorded_in_checkpoint_and_manifest(tmp_path):
    from src.run_manifest import RunManifest
    manifest = RunManifest(tmp_path / "run_manifest.json", {"run_seed": 1})
    result = loop(tmp_path, config=cfg(budget={"max_iterations": 2}),
                  manifest=manifest).run()
    assert result.stop_reason == "max_iterations"
    data = json.loads((tmp_path / "run_manifest.json").read_text())
    assert data["world_explore"]["stop_reason"] == "max_iterations"
    assert data["world_explore"]["iteration"] == 2


def test_thompson_strategy_is_deterministic(tmp_path):
    c = cfg(budget={"max_iterations": 6}, selection={"strategy": "thompson"})
    a = loop(tmp_path / "a", config=c).run()
    b = loop(tmp_path / "b", config=c).run()
    assert a.graph == b.graph


# ------------------------------------------------------------ entry function

def test_run_world_engine_chains_input_axes_graph_and_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda *a: pytest.fail("input()"))
    backend = make_backend()
    c = cfg(budget={"max_iterations": 4})
    r = run_world_engine(RAW, None, tmp_path, backend,
                         {"max_iterations": 3}, 5, config=c)
    assert r.stop_reason == "max_iterations" and r.iterations == 3
    for rel in ("input/user_input.txt", "input/input_brief.json",
                "world/world_axes.json", "world/graph.json",
                "world/contrasts.json", "world/preferences.jsonl",
                "run_manifest.json"):
        assert (tmp_path / rel).exists(), rel
    assert (tmp_path / "checkpoints").is_dir()
    manifest = json.loads((tmp_path / "run_manifest.json").read_text())
    assert manifest["status"] == "completed"
    assert manifest["world_explore"]["stop_reason"] == "max_iterations"
    assert sum(p.startswith("SOURCE MATERIAL")
               for p in backend.json_prompts) == 1

    again = make_backend()
    r2 = run_world_engine(RAW, None, tmp_path, again,
                          {"max_iterations": 5}, 5, config=c)
    assert r2.iterations == 5
    assert not any(p.startswith("SOURCE MATERIAL") for p in again.json_prompts)


# --------------------------------------------------------- prompts / config

BANNED_TERMS = [
    "protagonist", "主人公", "plot", "プロット", "chapter", "章", "novel",
    "小説", "story", "物語", "dialogue", "台詞", "character arc", "future",
    "未来", "past", "過去", "fantasy", "ファンタジー", "sci-fi",
    "science fiction", "SF", "medieval", "中世", "magic", "魔法", "kingdom",
    "王国", "city", "都市", "robot", "ロボット", "cyberpunk",
]


@pytest.mark.parametrize("rel", [
    "prompts/world/revision.yaml", "world/explore.yaml"])
def test_revision_prompt_and_config_have_no_story_or_genre_terms(rel):
    raw = (CONFIG / rel).read_text("utf-8").lower()
    for t in BANNED_TERMS:
        if t.isascii():
            assert not re.search(r"\b" + re.escape(t.lower()) + r"\b", raw), t
        else:
            assert t not in raw, t


def test_revision_prompt_carries_findings_language_and_bounded_context():
    from src.world.operators import load_revision_prompts
    p = load_revision_prompts()["common"]
    text = p["system"] + p["user"]
    for needle in ("{language}", "{findings}", "{draft}", "{context}",
                   "neutral"):
        assert needle in text
