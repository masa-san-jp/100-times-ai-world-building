"""Restatement judgment of new facts, using only synthetic fake responses."""

import json

import pytest
from jsonschema import Draft202012Validator

from src.llm.fake import FakeLLMBackend
from src.world.builder import EntityBuilder
from src.world.criteria import restatement_candidates
from src.world.schemas import step_schema
from tests.test_world_builder import build, graph, slot_of, step_of
from tests.test_world_explore import AXES, BRIEF, make_backend

EXISTING = "The containers hold the sealed tokens across every exchange cycle."
RESTATED = "Sealed tokens are held in containers through each exchange cycle."
NEW_FACT = "Physical containers keep discarded tokens apart."


def judged_backend(verdicts, fact_texts):
    """Generation answers come from make_backend; restatement_check follows verdicts."""
    inner = make_backend()
    seen = {"judge": 0, "texts": 0}

    def respond(prompt):
        step = step_of(prompt)
        if step == "restatement_check":
            verdict = verdicts[min(seen["judge"], len(verdicts) - 1)]
            seen["judge"] += 1
            return {"restates": verdict, "reason": "Synthetic verdict."}
        good = json.loads(inner.generate_schema(prompt, {}, constrained=True))
        if step == "fact_element" and slot_of(prompt) == 1:
            return {"object": "containers"}
        if step == "fact_text" and slot_of(prompt) == 1:
            text = fact_texts[min(seen["texts"], len(fact_texts) - 1)]
            seen["texts"] += 1
            return {"fact": text}
        return good

    backend = FakeLLMBackend(respond)
    backend.seen = seen
    return backend


def world(monkeypatch):
    monkeypatch.setattr("src.world.builder.fact_plan", lambda *args: ["number", "object"])
    g = graph()
    g["entities"][0]["facts"] = [{"kind": "object", "object": "containers", "text": EXISTING}]
    return g


def test_restatement_check_runs_on_the_judge_backend_only(monkeypatch):
    generation = judged_backend(["none"], [NEW_FACT])
    judge = judged_backend(["none"], [NEW_FACT])
    g = world(monkeypatch)
    builder = EntityBuilder(generation, {"build": {"max_step_attempts": 2}}, judge_backend=judge)
    result = builder.build(g, "premise", None, brief=BRIEF, axes=AXES, contract={}, frontier_axis=None)
    assert result.entity
    gen_steps = {step_of(c["prompt"]) for c in generation.schema_calls}
    judge_steps = {step_of(c["prompt"]) for c in judge.schema_calls}
    assert "restatement_check" in judge_steps and "restatement_check" not in gen_steps


def test_a_restatement_rebuilds_the_fact_from_its_elements(monkeypatch):
    g = world(monkeypatch)
    backend = judged_backend(["f1", "none"], [RESTATED, NEW_FACT])
    _, result = build(backend, g, config={"build": {"max_step_attempts": 2}})
    assert result.entity and result.entity["facts"][1]["text"] == NEW_FACT
    elements = [c for c in backend.schema_calls if step_of(c["prompt"]) == "fact_element" and slot_of(c["prompt"]) == 1]
    texts = [c for c in backend.schema_calls if step_of(c["prompt"]) == "fact_text" and slot_of(c["prompt"]) == 1]
    assert len(elements) == 2 and len(texts) == 2
    assert EXISTING in elements[1]["prompt"] and "new_information" in elements[1]["prompt"]
    rejected = next(r for r in result.steps if r.step == "fact_text" and not r.accepted)
    assert any(c["criterion"] == "new_information" and EXISTING in c["reason"] for c in rejected.checks)


def test_none_passes_without_rebuilding(monkeypatch):
    g = world(monkeypatch)
    backend = judged_backend(["none"], [NEW_FACT])
    _, result = build(backend, g, config={"build": {"max_step_attempts": 2}})
    assert result.entity
    assert backend.seen["texts"] == 1
    assert sum(step_of(c["prompt"]) == "restatement_check" for c in backend.schema_calls) == 1


def test_restatement_limit_is_the_slot_attempt_budget(monkeypatch):
    g = world(monkeypatch)
    backend = judged_backend(["f1"], [RESTATED])
    builder, result = build(backend, g, config={"build": {"max_step_attempts": 2}})
    assert result.entity is None and result.failure["step"] == "fact_text"
    assert builder.metrics["steps"]["restatement_check"]["failures"] >= 1
    assert builder.metrics["steps"]["restatement_check"]["calls"] >= 2


def test_no_candidate_means_no_judgment(monkeypatch):
    monkeypatch.setattr("src.world.builder.fact_plan", lambda *args: ["number", "object"])
    g = graph()
    g["entities"][0]["facts"] = [{"kind": "object", "object": "x", "text": "zzzz qqqq"}]
    backend = judged_backend(["f1"], ["containers"])
    _, result = build(backend, g, config={"build": {"max_step_attempts": 2}})
    assert result.entity
    assert not any(step_of(c["prompt"]) == "restatement_check" for c in backend.schema_calls)


def test_candidates_are_the_top_k_by_jaccard_without_zero_overlap():
    texts = ["abcdefg", "abcdxyz", "abcdefh", "qqqqqqq", "abcdefg!"]
    picked = restatement_candidates("abcdefg", texts, limit=2)
    assert picked == ["abcdefg", "abcdefg!"]
    assert restatement_candidates("abcdefg", ["qqqqqqq"], limit=5) == []
    assert len(restatement_candidates("abcdefg", texts, limit=10)) == 4


def test_schema_enum_is_none_plus_the_candidate_ids():
    validator = Draft202012Validator(step_schema("restatement_check", candidate_ids=["f1", "f2"]))
    assert validator.is_valid({"restates": "f2", "reason": "same claim"})
    assert validator.is_valid({"restates": "none", "reason": "new"})
    assert not validator.is_valid({"restates": "f3", "reason": "x"})
    assert not validator.is_valid({"restates": "none", "reason": ""})
    assert not validator.is_valid({"restates": "none", "reason": "x", "extra": 1})


def test_candidate_count_comes_from_criteria_config():
    from src.world.criteria import restatement_candidates_limit
    assert restatement_candidates_limit() == 5


def test_restatement_check_forbids_conversion():
    from src.world.criteria import restatement_check
    backend = FakeLLMBackend({"restates": True, "reason": "bad"})
    result = restatement_check(backend, "a fact", ["other fact"], language="en",
                               max_attempts=1, max_conversions=2)
    assert result.data is None and result.conversions == 0
