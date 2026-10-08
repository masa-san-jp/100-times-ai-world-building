"""Two-stage fact generation and bounded repairs using synthetic backends."""

import json

import pytest
from jsonschema import Draft202012Validator

from src.world.schemas import step_schema
from tests.test_world_builder import backend_with, build, graph
from tests.test_world_explore import SYNTHETIC_PREMISES, make_backend


def rows(result, step, slot):
    return [row for row in result.steps if row.step == step and row.slot == slot]


def test_all_five_fact_kinds_generate_elements_then_body():
    backend = make_backend()
    builder, result = build(backend, graph("site"), "zoom", "e5", SYNTHETIC_PREMISES)
    assert result.entity, result.failure
    stages = [(row.step, row.slot) for row in result.steps if row.step.startswith("fact_")]
    assert stages == [(step, slot) for slot in range(5) for step in ("fact_element", "fact_text")]
    for slot, fact in enumerate(result.entity["facts"]):
        element, = rows(result, "fact_element", slot)
        body, = rows(result, "fact_text", slot)
        assert "fact" not in element.output
        assert body.output == {"fact": fact["text"]}
        assert all(fact[key] == value for key, value in element.output.items())
    assert "fact" not in builder.metrics["steps"]
    assert builder.metrics["steps"]["fact_element"]["calls"] == 5
    assert builder.metrics["steps"]["fact_text"]["calls"] == 5
    assert result.calls == len(backend.schema_calls)


@pytest.mark.parametrize("slot", range(5))
def test_missing_elements_retry_only_body_with_same_decided_elements(slot):
    def change(step, current, attempt, prompt, good):
        if step == "fact_text" and current == slot and attempt == 1:
            return {"fact": "This body omits every required element."}
        if step == "fact_text" and current == slot and attempt == 2:
            assert "FAILED CHECKS" in prompt and "detail" in prompt
        return good
    backend = backend_with(change)
    _, result = build(backend, graph("site"), "zoom", "e5", SYNTHETIC_PREMISES)
    assert result.entity, result.failure
    element, = rows(result, "fact_element", slot)
    assert [row.accepted for row in rows(result, "fact_text", slot)] == [False, True]
    assert all(result.entity["facts"][slot][key] == value for key, value in element.output.items())
    calls = [call for call in backend.schema_calls
             if f"STEP: fact_text\nSLOT: {slot}\n" in call["prompt"]]
    for call in calls:
        assert "Include the following decided elements verbatim" in call["prompt"]
        assert all(f'{key}: {json.dumps(value, ensure_ascii=False)}' in call["prompt"]
                   for key, value in element.output.items())
    assert backend.attempts[("fact_element", slot)] == 1
    assert backend.attempts[("fact_text", slot)] == 2


@pytest.mark.parametrize("recover", [False, True])
def test_body_exhaustion_restarts_elements_once_and_has_a_hard_limit(recover):
    elements = []
    def change(step, slot, attempt, prompt, good):
        if slot == 1 and step == "fact_element":
            chosen = {"name": "Zelvra" if attempt == 1 else "Tavren"}
            elements.append(chosen)
            if attempt == 2:
                assert "FAILED CHECKS" in prompt and "contain name" in prompt
            return chosen
        if slot == 1 and step == "fact_text":
            assert elements[-1]["name"] in prompt
            if attempt <= 2 or not recover:
                return {"fact": "This body omits the required name."}
        return good
    backend = backend_with(change)
    builder, result = build(backend, config={"build": {"max_step_attempts": 2}})
    assert backend.attempts[("fact_element", 1)] == 2
    assert backend.attempts[("fact_text", 1)] == (3 if recover else 4)
    assert [row.output for row in rows(result, "fact_element", 1)] == elements
    assert elements == [{"name": "Zelvra"}, {"name": "Tavren"}]
    if recover:
        assert result.entity["facts"][1]["name"] == "Tavren"
    else:
        assert result.entity is None and result.failure["step"] == "fact_text"
        assert result.failure["slot"] == 1
        assert builder.metrics["failures_by_step"] == {"fact_text": 1}
    assert builder.metrics["steps"]["fact_element"]["attempts"] == {"1": 1, "2": 1}
    assert builder.metrics["steps"]["fact_text"]["attempts"] == {"1": 1, str(3 if recover else 4): 1}
    assert result.calls == len(backend.schema_calls)


def test_restarted_elements_have_their_own_bounded_attempts():
    def change(step, slot, attempt, prompt, good):
        if slot == 1 and step == "fact_element":
            return {"name": "Zelvra" if attempt == 1 else "alpha"}
        if slot == 1 and step == "fact_text":
            return {"fact": "This body omits the required name."}
        return good
    backend = backend_with(change)
    _, result = build(backend, config={"build": {"max_step_attempts": 2}})
    assert result.entity is None and result.failure["step"] == "fact_element"
    assert backend.attempts[("fact_element", 1)] == 3
    assert backend.attempts[("fact_text", 1)] == 2
    assert [row.accepted for row in rows(result, "fact_element", 1)] == [True, False, False]


@pytest.mark.parametrize("rejection", ["existing", "real"])
def test_rejected_proper_name_retries_elements_before_any_body(rejection):
    def change(step, slot, attempt, prompt, good):
        if step == "fact_element" and slot == 1 and attempt == 1:
            return {"name": "alpha" if rejection == "existing" else "Zelvra"}
        if step == "real_world_check" and good["items"][0]["term"] == "Zelvra":
            good["items"][0].update(category="real_person_name", reason="Real fixture name.")
        if step == "fact_element" and slot == 1 and attempt == 2:
            assert "FAILED CHECKS" in prompt
            assert ("name must be new" if rejection == "existing" else "Real fixture name.") in prompt
        return good
    backend = backend_with(change)
    _, result = build(backend)
    assert result.entity, result.failure
    assert [row.accepted for row in rows(result, "fact_element", 1)] == [False, True]
    assert len(rows(result, "fact_text", 1)) == 1
    assert backend.attempts[("fact_text", 0)] == 1
    assert result.entity["facts"][1]["name"] == rows(result, "fact_element", 1)[1].output["name"]


@pytest.mark.parametrize("value", ["tiny", "x" * 201, None, 3, True])
def test_fact_body_schema_retains_type_and_length_checks(value):
    validator = Draft202012Validator(step_schema("fact_text"))
    assert not validator.is_valid({"fact": value})
    assert not validator.is_valid({})
    assert not validator.is_valid({"fact": "A valid body.", "name": "Zelvra"})
    for length in (5, 200):
        assert validator.is_valid({"fact": "x" * length})


def test_combined_fact_schema_has_been_removed():
    with pytest.raises(FileNotFoundError):
        step_schema("fact", kind="proper_noun")
    element = Draft202012Validator(step_schema("fact_element", kind="proper_noun"))
    assert not element.is_valid({"name": "Zelvra", "fact": "Zelvra stores the records."})


def test_review_does_not_grant_a_second_body_exhaustion_restart():
    def change(step, slot, attempt, prompt, good):
        if step == "fact_text" and slot == 1 and attempt != 3:
            return {"fact": "This body omits the required name."}
        if step == "review":
            good["verdicts"]["consistent"] = False
            good["issues"] = [{"field": "facts[1]", "criterion": "consistent",
                               "reason": "Correct the stated connection."}]
        return good
    backend = backend_with(change)
    _, result = build(backend, config={"build": {"max_step_attempts": 2}})
    assert result.entity is None and result.failure["step"] == "fact_text"
    assert backend.attempts[("fact_element", 1)] == 3  # First cycle, restart, review repair.
    assert backend.attempts[("fact_text", 1)] == 4
    assert backend.attempts[("review", None)] == 1
