"""Issue #62: synthetic step generation, local repairs and hard acceptance."""
import copy
import json
import re
from dataclasses import asdict
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from src.llm.fake import FakeLLMBackend
from src.world.builder import ALLOWED_TYPES, EntityBuilder, fact_plan, overlap
from src.world.explore import ExplorationLoop, extract_preference_pairs, read_preference_log, run_world_engine
from src.world.graph import GraphStore, SCALES, make_entity, new_graph, validate_graph
from src.world.schemas import step_schema
from tests.test_world_explore import AXES, BRIEF, RAW, SYNTHETIC_PREMISES, cfg, make_backend

CRITERIA = yaml.safe_load((Path(__file__).resolve().parents[1] / "config/world/criteria.yaml").read_text())
PROV = {"statement_ids": ["s1"], "derived_from": [], "reason": ""}


def graph(scale="world"):
    g = new_graph("en")
    for i, level in enumerate(SCALES[:SCALES.index(scale) + 1], 1):
        g["entities"].append(make_entity(f"e{i}", "place", f"Existing {i}", level,
            parent=f"e{i - 1}" if i > 1 else None, axes=["a1"], provenance=PROV))
    return g


def step_of(prompt):
    return re.search(r"^STEP: (.+)$", prompt, re.M).group(1)


def slot_of(prompt):
    slot = re.search(r"^SLOT: (.+)$", prompt, re.M).group(1)
    return None if slot == "None" else int(slot)


def backend_with(change):
    inner = make_backend()
    attempts = {}
    def respond(prompt):
        step, slot = step_of(prompt), slot_of(prompt)
        key = (step, slot)
        attempts[key] = attempts.get(key, 0) + 1
        good = json.loads(inner.generate_schema(prompt, {}, constrained=True))
        return change(step, slot, attempts[key], prompt, good)
    backend = FakeLLMBackend(respond)
    backend.attempts = attempts
    return backend


def build(backend=None, g=None, operator="premise", target=None, contract=None, config=None, frontier=None):
    builder = EntityBuilder(backend or make_backend(), config)
    result = builder.build(g or new_graph("en"), operator, target, brief=BRIEF, axes=AXES,
                           contract=contract or {}, frontier_axis=frontier)
    return builder, result


def test_each_call_generates_exactly_one_item_in_the_planned_order():
    backend = make_backend()
    builder, result = build(backend)
    assert result.entity and result.failure is None
    assert [s.step for s in result.steps] == ["type", "grounding", "name", "axes", "summary", "fact", "fact", "review"]
    expected = [{"type"}, {"statement_ids", "derived_from", "reason"}, {"name"}, {"axes"},
                {"summary"}, {"subject", "value", "unit", "fact"}, {"fact"}, {"matches", "reason"}, {"verdicts", "issues"}]
    assert [set(c["schema"]["properties"]) for c in backend.schema_calls] == expected
    assert result.calls == len(backend.schema_calls) == 9
    assert all(s.accepted and s.attempt == 1 for s in result.steps)
    assert all(c["system_prompt"] == builder.prompts["common"]["system"] for c in backend.schema_calls)
    assert result.entity["id"] == "e1" and result.entity["scale"] == "world"


def test_duplicate_name_is_corrected_without_regenerating_other_steps():
    g = graph()
    def change(step, slot, attempt, prompt, good):
        if step == "name" and attempt == 1:
            return {"name": " ＥＸＩＳＴＩＮＧ 1! "}
        if step == "name" and attempt == 2:
            assert "PREVIOUS OUTPUT" in prompt and "distinct" in prompt
        return good
    backend = backend_with(change)
    _, result = build(backend, g)
    assert result.entity and not result.failure
    rows = [s for s in result.steps if s.step == "name"]
    assert [r.accepted for r in rows] == [False, True]
    assert [r.attempt for r in rows] == [1, 2]
    assert all(n == (2 if key == ("name", None) else 1) for key, n in backend.attempts.items())
    assert len(g["entities"]) == 1


def test_low_capability_backend_recovers_both_duplicate_name_and_wrong_fact_kind():
    g = graph()
    def change(step, slot, attempt, prompt, good):
        if step == "name" and attempt == 1:
            return {"name": "Existing 1"}
        if step == "fact" and slot == 0 and attempt == 1:
            return {**good, "value": 50, "fact": "50 members"}
        if step == "fact" and slot == 0 and attempt == 2:
            assert "specific" in prompt and "50 members" in prompt
        return good
    backend = backend_with(change)
    _, result = build(backend, g)
    assert result.entity and result.calls == len(backend.schema_calls)
    assert len([r for r in result.steps if not r.accepted]) == 2
    assert [f["kind"] for f in result.entity["facts"]] == ["number", "proper_noun"]
    g["entities"].append(result.entity)
    assert validate_graph(g, AXES, BRIEF) == []


@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("has_contract", [True, False])
def test_fact_kinds_and_count_are_planned_by_scale(scale, has_contract):
    minimum = dict(zip(SCALES, [0, 1, 2, 2, 3, 4]))
    contract = SYNTHETIC_PREMISES if has_contract else {}
    plan = fact_plan(scale, minimum, contract)
    assert len(plan) == max(2, minimum[scale] + 1)
    assert plan[:2] == ["number", "proper_noun"]
    assert plan[2:] == ["object", "procedure", "period" if has_contract else "procedure"][:len(plan) - 2]


def test_fact_plan_cycles_and_uses_existing_configured_minimum():
    assert fact_plan("detail", {"detail": 8}, SYNTHETIC_PREMISES) == [
        "number", "proper_noun", "object", "procedure", "period", "object", "procedure", "period", "object"]


def test_fact_confirmation_is_a_small_task_for_each_semantic_kind():
    g = graph("site")
    backend = make_backend()
    _, result = build(backend, g, "zoom", "e5", SYNTHETIC_PREMISES)
    assert result.entity, result.failure
    assert [f["kind"] for f in result.entity["facts"]] == ["number", "proper_noun", "object", "procedure", "period"]
    calls = [c for c in backend.schema_calls if "STEP: fact_check\n" in c["prompt"]]
    assert len(calls) == 3
    for call, kind in zip(calls, ("proper_noun", "object", "procedure")):
        assert f"is a {kind} fact about {result.entity['name']}" in call["prompt"]
        assert set(call["schema"]["properties"]) == {"matches", "reason"}


def test_wrong_semantic_kind_regenerates_only_that_fact():
    def change(step, slot, attempt, prompt, good):
        if step == "fact_check" and slot == 1 and attempt == 1:
            return {"matches": False, "reason": "No proper name is present."}
        if step == "fact" and slot == 1 and attempt == 2:
            assert "No proper name is present." in prompt
        return good
    backend = backend_with(change)
    _, result = build(backend)
    assert result.entity
    assert backend.attempts[("fact", 0)] == 1
    assert backend.attempts[("fact", 1)] == 2
    assert backend.attempts[("summary", None)] == 1


@pytest.mark.parametrize("value,unit,text", [(50, "members", "50 members"),
    (5, "years", "Capacity is 5 years."), (5, "hours", "Capacity is 5 hours.")])
def test_number_rejects_counts_and_time_only_units(value, unit, text):
    backend = backend_with(lambda step, slot, attempt, prompt, good: {**good, "value": value, "unit": unit, "fact": text} if step == "fact" and slot == 0 else good)
    _, result = build(backend, config={"build": {"max_step_attempts": 2}})
    assert not result.entity and result.failure["step"] == "fact" and result.failure["slot"] == 0
    assert all(any(c["criterion"] == "specific" and not c["ok"] for c in r.checks) for r in result.steps if r.step == "fact")


@pytest.mark.parametrize("unit", ["qx", "quota/qx"])
def test_unknown_units_cannot_be_proposed_or_approved(unit):
    backend = backend_with(lambda step, slot, attempt, prompt, good: {**good, "value": 3, "unit": unit, "fact": f"Capacity is 3 {unit}."} if step == "fact" and slot == 0 else good)
    _, result = build(backend, contract=SYNTHETIC_PREMISES)
    assert result.entity is None and '"enum"' in result.failure["reason"]
    assert all("premise_extension" not in call["schema"]["properties"] for call in backend.schema_calls)


@pytest.mark.parametrize("unit", ["quota", "quota²", "quota/term", "(quota/term)^2"])
def test_explicitly_registered_units_and_combinations_pass(unit):
    contract = copy.deepcopy(SYNTHETIC_PREMISES)
    contract["technology"]["units"].append(unit)
    backend = backend_with(lambda step, slot, attempt, prompt, good: {**good, "value": 3, "unit": unit, "fact": f"Measured capacity is 3 {unit}."} if step == "fact" and slot == 0 else good)
    _, result = build(backend, contract=contract)
    assert result.entity, result.failure


@pytest.mark.parametrize("text", ["Founded in Other Count 18.", "Founded in 1987.", "Elapsed for 3 years."])
def test_period_requires_the_contract_marker(text):
    g = graph("site")
    backend = backend_with(lambda step, slot, attempt, prompt, good: {**good, "fact": text} if step == "fact" and slot == 4 else good)
    _, result = build(backend, g, "zoom", "e5", SYNTHETIC_PREMISES)
    assert result.entity is None and result.failure["slot"] == 4
    assert "specific" in result.failure["reason"] or "fits_world" in result.failure["reason"]


def test_fullwidth_number_and_defined_calendar_are_recognized():
    g = graph("site")
    def change(step, slot, attempt, prompt, good):
        if step == "fact" and slot == 4:
            return {**good, "value": 18, "fact": "Opening records identify Vela Count １８."}
        if step == "fact" and slot == 0:
            return {**good, "value": 12, "fact": "The measured capacity is １２ quota."}
        return good
    _, result = build(backend_with(change), g, "zoom", "e5", SYNTHETIC_PREMISES)
    assert result.entity, result.failure


@pytest.mark.parametrize("kind,fields", [
    ("number", {"subject", "value", "unit", "fact"}),
    ("period", {"marker", "value", "fact"}),
    ("proper_noun", {"fact"}), ("object", {"fact"}),
    ("procedure", {"fact"}), ("other", {"fact"}),
])
def test_fact_schema_has_only_the_required_fields_for_its_kind(kind, fields):
    schema = step_schema("fact", kind=kind, contract=SYNTHETIC_PREMISES)
    Draft202012Validator.check_schema(schema)
    assert set(schema["properties"]) == set(schema["required"]) == fields
    assert schema["additionalProperties"] is False
    assert schema["properties"]["fact"] == {"type": "string", "minLength": 5, "maxLength": 200}


@pytest.mark.parametrize("field,value", [
    ("subject", ""), ("subject", "x" * 81), ("subject", 3),
    ("value", "12"), ("value", True), ("unit", ""), ("unit", "x" * 21),
    ("unit", 3), ("fact", "tiny"), ("fact", "x" * 201),
])
def test_number_schema_enforces_types_and_lengths_without_a_contract(field, value):
    validator = Draft202012Validator(step_schema("fact", kind="number"))
    data = {"subject": "Capacity", "value": 12, "unit": "quota", "fact": "Capacity is 12 quota."}
    assert not list(validator.iter_errors(data))
    data[field] = value
    assert list(validator.iter_errors(data))


@pytest.mark.parametrize("kind,data", [
    ("number", {"subject": "Capacity", "value": 12, "unit": "quota", "fact": "Capacity is 12 quota."}),
    ("period", {"marker": "Vela Count", "value": 18, "fact": "Founded in Vela Count 18."}),
])
def test_each_structured_fact_field_is_required(kind, data):
    validator = Draft202012Validator(step_schema("fact", kind=kind, contract=SYNTHETIC_PREMISES))
    assert not list(validator.iter_errors(data))
    for field in data:
        errors = list(validator.iter_errors({k: v for k, v in data.items() if k != field}))
        assert any(e.validator == "required" for e in errors), field


@pytest.mark.parametrize("unit", ["quota²", "quota/term", "(quota/term)^2", "qx"])
def test_number_schema_rejects_units_not_explicitly_listed_in_the_contract(unit):
    validator = Draft202012Validator(step_schema("fact", kind="number", contract=SYNTHETIC_PREMISES))
    data = {"subject": "Capacity", "value": 3, "unit": unit, "fact": f"Capacity is 3 {unit}."}
    assert any(e.validator == "enum" and list(e.path) == ["unit"] for e in validator.iter_errors(data))


def test_period_schema_accepts_calendar_name_and_markers_only():
    contract = copy.deepcopy(SYNTHETIC_PREMISES)
    contract["calendar"]["markers"] = ["Quota Cycle", "Ledger Cycle"]
    validator = Draft202012Validator(step_schema("fact", kind="period", contract=contract))
    for marker in ["Vela Count", "Quota Cycle", "Ledger Cycle"]:
        assert not list(validator.iter_errors({"marker": marker, "value": 18, "fact": f"Founded in {marker} 18."}))
    assert any(e.validator == "enum" for e in validator.iter_errors(
        {"marker": "Other Count", "value": 18, "fact": "Founded in Other Count 18."}))


def test_numberless_fact_only_fake_enters_schema_repair_loop():
    def change(step, slot, attempt, prompt, good):
        if step == "fact" and slot == 0:
            if attempt == 1:
                return {"fact": "The capacity is measured with quota."}
            assert "REPAIR INSTRUCTIONS" in prompt
            assert "required" in prompt and "value" in prompt
        return good
    backend = backend_with(change)
    _, result = build(backend)
    assert result.entity, result.failure
    assert backend.attempts[("fact", 0)] == 2
    assert len([r for r in result.steps if r.step == "fact" and r.slot == 0]) == 1
    assert backend._structured_metrics["fact"]["attempts"] == {"2": 1, "1": 1}
    assert backend.attempts[("summary", None)] == backend.attempts[("name", None)] == 1


@pytest.mark.parametrize("text", [
    "Capacity is measured with quota.", "Capacity is 112 quota.",
    "Capacity is 12.", "Capacity is 12 term.",
])
def test_number_requires_its_declared_value_and_unit_in_the_text(text):
    backend = backend_with(lambda step, slot, attempt, prompt, good:
        {**good, "value": 12, "fact": text} if step == "fact" and slot == 0 else good)
    _, result = build(backend, contract=SYNTHETIC_PREMISES, config={"build": {"max_step_attempts": 2}})
    assert result.entity is None and result.failure["slot"] == 0
    assert all(any(c["criterion"] == "specific" and not c["ok"] for c in r.checks)
               for r in result.steps if r.step == "fact")


def test_non_time_check_uses_declared_unit_even_when_text_has_another_measurement():
    backend = backend_with(lambda step, slot, attempt, prompt, good:
        {**good, "value": 12, "unit": "hours", "fact": "Capacity is 12 quota over 12 hours."}
        if step == "fact" and slot == 0 else good)
    _, result = build(backend, config={"build": {"max_step_attempts": 1}})
    assert result.entity is None and "specific" in result.failure["reason"]


@pytest.mark.parametrize("value,spelling", [
    (1200, "1,200"), (1200, "１，２００"), (12.5, "１２．５"),
    (-12, "－１２"), (1200, "1.2e3"),
])
@pytest.mark.parametrize("slot", [0, 4])
def test_fact_value_comparison_normalizes_width_and_grouping(value, spelling, slot):
    def change(step, current_slot, attempt, prompt, good):
        if step == "fact" and current_slot == slot:
            text = (f"Capacity measured {spelling} quota." if slot == 0 else
                    f"Opening records identify Vela Count {spelling}.")
            return {**good, "value": value, "fact": text}
        return good
    _, result = build(backend_with(change), graph("site"), "zoom", "e5", SYNTHETIC_PREMISES)
    assert result.entity, result.failure


@pytest.mark.parametrize("text", [
    "Founded in Vela Count without a date.", "Founded in Vela Count 118.",
    "Founded in Other Count 18.", "Founded long before 18 quota were recorded.",
])
def test_period_requires_its_declared_marker_and_value_in_the_text(text):
    backend = backend_with(lambda step, slot, attempt, prompt, good:
        {**good, "value": 18, "fact": text} if step == "fact" and slot == 4 else good)
    _, result = build(backend, graph("site"), "zoom", "e5", SYNTHETIC_PREMISES,
                      config={"build": {"max_step_attempts": 1}})
    assert result.entity is None and result.failure["slot"] == 4
    assert "specific" in result.failure["reason"]


def test_structured_fact_fields_survive_graph_validation_and_roundtrip(tmp_path):
    g = graph("site")
    _, result = build(g=g, operator="zoom", target="e5", contract=SYNTHETIC_PREMISES)
    assert result.entity, result.failure
    for slot, fields in [(0, {"subject", "value", "unit"}), (4, {"marker", "value"})]:
        output = next(r.output for r in result.steps if r.step == "fact" and r.slot == slot)
        fact = result.entity["facts"][slot]
        assert fact["text"] == output["fact"]
        assert {field: fact[field] for field in fields} == {field: output[field] for field in fields}
        assert fact["provenance"] == result.entity["provenance"]
    assert set(result.entity["facts"][1]) == {"kind", "text", "provenance"}
    g["entities"].append(result.entity)
    assert validate_graph(g, AXES, BRIEF) == []
    store = GraphStore(tmp_path, axes=AXES, brief=BRIEF)
    store.save(g)
    assert store.load()["entities"][-1]["facts"] == result.entity["facts"]


def test_number_conflict_is_detected_against_other_facts():
    g = graph("settlement")
    def change(step, slot, attempt, prompt, good):
        if step == "fact" and slot == 0:
            return {**good, "value": 3, "fact": "Capacity measured 3 quota."}
        if step == "fact" and slot == 2:
            return {"fact": "Capacity measured 4 quota with physical containers."}
        return good
    _, result = build(backend_with(change), g, "expand", "e3", SYNTHETIC_PREMISES)
    assert not result.entity and "consistent" in result.failure["reason"]


def test_informative_rejects_copied_summary_and_fact():
    original = "The records define paired checks after each exchange and retain the discarded tokens in separate boxes."
    g = graph()
    g["entities"][0]["summary"] = original
    backend = backend_with(lambda step, slot, attempt, prompt, good: {"summary": original} if step == "summary" else good)
    _, result = build(backend, g, "expand", "e1")
    assert not result.entity and result.failure["step"] == "summary"
    assert "informative" in result.failure["reason"]
    g["entities"][0]["facts"] = [{"kind": "number", "text": "Capacity is 18 quota.", "provenance": PROV}]
    backend = backend_with(lambda step, slot, attempt, prompt, good: {**good, "value": 18, "fact": "Capacity is 18 quota."} if step == "fact" and slot == 0 else good)
    _, result = build(backend, g, "expand", "e1")
    assert not result.entity and "informative" in result.failure["reason"]


def test_fact_duplicates_are_rejected_after_normalization():
    saved = {}
    def change(step, slot, attempt, prompt, good):
        if step == "fact" and slot == 0:
            saved["fact"] = good["fact"]
        if step == "fact" and slot == 1:
            return {"fact": saved["fact"].upper() + "!"}
        return good
    _, result = build(backend_with(change))
    assert not result.entity
    assert any(c["criterion"] == "distinct" and not c["ok"] for r in result.steps if r.step == "fact" and r.slot == 1 for c in r.checks)


@pytest.mark.parametrize("field", ["name", "summary", "facts[0]", "facts[1]"])
def test_review_rewrites_only_the_named_field_then_reviews_again(field):
    def change(step, slot, attempt, prompt, good):
        if step == "review" and attempt == 1:
            good["verdicts"]["fits_world"] = False
            good["issues"] = [{"field": field, "criterion": "fits_world", "reason": "Clarify the connection to the supplied world."}]
        if (step == field or (step == "fact" and field == f"facts[{slot}]")) and attempt == 2:
            assert "REVIEW ISSUES" in prompt and "Clarify the connection" in prompt
        return good
    backend = backend_with(change)
    _, result = build(backend)
    assert result.entity, result.failure
    assert backend.attempts[("review", None)] == 2
    for key, n in backend.attempts.items():
        extra = key == (field, None) or (key[0] in {"fact", "fact_check"} and field == f"facts[{key[1]}]")
        assert n == (2 if extra or key == ("review", None) else 1)


def test_review_groups_multiple_issues_for_one_field_into_one_repair():
    def change(step, slot, attempt, prompt, good):
        if step == "review" and attempt == 1:
            for criterion in ("consistent", "fits_world"):
                good["verdicts"][criterion] = False
                good["issues"].append({"field": "summary", "criterion": criterion, "reason": criterion + " explanation"})
        return good
    backend = backend_with(change)
    _, result = build(backend)
    assert result.entity and backend.attempts[("summary", None)] == 2


def test_review_limit_is_hard_and_failure_identifies_review():
    def change(step, slot, attempt, prompt, good):
        if step == "review":
            good["verdicts"]["consistent"] = False
            good["issues"] = [{"field": "summary", "criterion": "consistent", "reason": "Still inconsistent."}]
        return good
    backend = backend_with(change)
    builder, result = build(backend)
    assert not result.entity and result.failure == {"step": "review", "slot": None, "reason": "consistent: Still inconsistent."}
    assert backend.attempts[("review", None)] == 3 and backend.attempts[("summary", None)] == 3
    assert builder.metrics["failed"] == 1 and builder.metrics["failures_by_step"] == {"review": 1}


def test_review_cannot_accept_a_false_verdict_without_a_field_issue():
    def change(step, slot, attempt, prompt, good):
        if step == "review":
            good["verdicts"]["objective"] = False
        return good
    _, result = build(backend_with(change))
    assert not result.entity and result.failure["step"] == "review"
    assert "no issue" in result.failure["reason"]


def test_review_repairs_share_the_step_attempt_limit():
    def change(step, slot, attempt, prompt, good):
        if step == "review":
            good["verdicts"]["consistent"] = False
            good["issues"] = [{"field": "name", "criterion": "consistent", "reason": "Name remains inconsistent."}]
        return good
    backend = backend_with(change)
    _, result = build(backend, config={"build": {"max_step_attempts": 2, "review_rounds": 2}})
    assert not result.entity and result.failure["step"] == "name"
    assert backend.attempts[("name", None)] == 2


@pytest.mark.parametrize("step", ["type", "grounding", "name", "axes", "summary", "fact", "relations", "review"])
def test_each_step_schema_exhaustion_rejects_the_entity_and_records_failure(step):
    g = graph()
    backend = backend_with(lambda current, slot, attempt, prompt, good: {} if current == step else good)
    builder, result = build(backend, g, config={"build": {"max_step_attempts": 2, "review_rounds": 1}, "structured": {"max_attempts": 2}})
    assert not result.entity and result.failure["step"] == step
    assert result.calls == len(backend.schema_calls)
    assert builder.metrics["steps"][step]["failures"] == 1
    assert "schema" in result.failure["reason"]
    assert not any(s.accepted for s in result.steps if s.step == step)


def test_schema_repair_does_not_regenerate_accepted_fields():
    def change(step, slot, attempt, prompt, good):
        if step == "name" and attempt == 1:
            return {"name": "", "id": "model-id", "parent": "model-parent"}
        if step == "name" and attempt == 2:
            assert "REPAIR INSTRUCTIONS" in prompt
        return good
    backend = backend_with(change)
    _, result = build(backend)
    assert result.entity and result.entity["id"] == "e1"
    assert backend.attempts[("type", None)] == backend.attempts[("grounding", None)] == 1
    assert len([s for s in result.steps if s.step == "name"]) == 1
    assert result.calls == len(backend.schema_calls) == 10


@pytest.mark.parametrize("grounding", [{"statement_ids": [], "derived_from": [], "reason": ""},
    {"statement_ids": [], "derived_from": ["e1"], "reason": "short"}])
def test_grounding_is_required_and_derivation_needs_ten_characters(grounding):
    backend = backend_with(lambda step, slot, attempt, prompt, good: grounding if step == "grounding" else good)
    _, result = build(backend, graph())
    assert not result.entity and result.failure["step"] == "grounding"
    assert "grounded" in result.failure["reason"]


@pytest.mark.parametrize("op", ["cause", "history", "perspective", "document"])
def test_target_grounding_is_added_by_the_harness(op):
    _, result = build(g=graph(), operator=op, target="e1")
    assert result.entity and result.entity["provenance"]["derived_from"] == ["e1"]
    assert all(f["provenance"] == result.entity["provenance"] for f in result.entity["facts"])


def test_frontier_axis_is_forced_with_at_most_three_tags():
    axes = [*AXES, {"id": "a4", "name": "Four", "meaning": "fourth"}]
    backend = backend_with(lambda step, slot, attempt, prompt, good: {"axes": ["a1", "a2", "a3"]} if step == "axes" else good)
    builder = EntityBuilder(backend)
    result = builder.build(new_graph("en"), "premise", None, brief=BRIEF, axes=axes, contract={}, frontier_axis="a4")
    assert result.entity and result.entity["axes"] == ["a4", "a1", "a2"]


@pytest.mark.parametrize("name", ["日本語名称", "Русский"])
def test_name_script_check_uses_the_output_language(name):
    backend = backend_with(lambda step, slot, attempt, prompt, good: {"name": name} if step == "name" else good)
    _, result = build(backend)
    assert not result.entity and "script" in result.failure["reason"]


@pytest.mark.parametrize("summary", ["We compare each record and keep our tokens after a failed exchange.",
    '"Bring the records!" he shouted before removing each token from its box.'])
def test_existing_objectivity_and_narrative_rules_are_hard_checks(summary):
    backend = backend_with(lambda step, slot, attempt, prompt, good: {"summary": summary} if step == "summary" else good)
    _, result = build(backend)
    assert not result.entity and result.failure["step"] == "summary"
    assert {c["criterion"] for c in result.steps[-1].checks if not c["ok"]} >= {"objective", "no_story"}


def test_all_checks_use_defined_criterion_ids_and_definitions_map_to_checks():
    backend = make_backend(generic_ops={"premise"})
    _, result = build(backend, graph())
    observed = {c["criterion"] for r in result.steps for c in r.checks}
    assert observed == set(CRITERIA) == {"grounded", "consistent", "objective", "no_story", "specific", "informative", "distinct", "fits_world"}
    assert all(item["definition"] and item["checks"] for item in CRITERIA.values())
    for row in result.steps:
        assert set(asdict(row)) == {"step", "slot", "attempt", "output", "checks", "accepted"}
        assert all(set(c) == {"criterion", "ok", "reason"} for c in row.checks)


def test_preference_pairs_are_scoped_to_one_build_step_and_slot():
    def row(it, step, slot, ok, output):
        return {"type": "step", "iteration": it, "step": step, "slot": slot, "attempt": 1, "accepted": ok, "output": output, "checks": []}
    records = [row(1, "name", None, False, {"name": "old"}), row(1, "name", None, True, {"name": "new"}),
               row(1, "fact", 0, False, {"fact": "bad"}), row(1, "fact", 1, True, {"fact": "good"}),
               row(2, "fact", 0, True, {"fact": "unrelated"})]
    pairs = extract_preference_pairs(records)
    assert len(pairs) == 1 and pairs[0]["chosen"] == {"name": "new"} and pairs[0]["rejected"] == {"name": "old"}
    assert pairs[0]["prompt"]["step"] == "name" and pairs[0]["prompt"]["slot"] is None


def test_loop_step_logs_preferences_and_bandit_reward_use_repairs(tmp_path):
    backend = make_backend(generic_ops={"premise"})
    loop = ExplorationLoop(backend, tmp_path, BRIEF, AXES, language="en", config=cfg())
    result = loop.run(max_iterations=1)
    records = read_preference_log(result.preferences_path)
    iteration = records[-1]
    assert result.counters["accepted"] == 1 and iteration["outcome"] == "accepted"
    steps = [r for r in records if r["type"] == "step"]
    assert len(steps) == 9
    capacity = 7 * 3 + 2
    assert iteration["arm_reward"] == round(1 - 0.5 / capacity, 4)
    assert loop.bandit.arms["premise|empty"]["sum"] == pytest.approx(1 - 0.5 / capacity)
    pair, = extract_preference_pairs(records)
    assert pair["prompt"]["step"] == "fact" and pair["prompt"]["slot"] == 0
    assert pair["rejected"] == {"subject": "Capacity", "value": 50, "unit": "quota", "fact": "50 members"}


def test_loop_discards_hard_failure_with_zero_reward_and_reports_step(tmp_path):
    loop = ExplorationLoop(make_backend(always_generic=True), tmp_path, BRIEF, AXES, language="en", config=cfg())
    result = loop.run(max_iterations=1)
    iteration = read_preference_log(result.preferences_path)[-1]
    assert not result.graph["entities"] and iteration["outcome"] == "discarded"
    assert iteration["arm_reward"] == 0 and iteration["failure"]["step"] == "fact"
    assert loop.builder.metrics["failures_by_step"] == {"fact": 1}


def test_metrics_calls_distributions_reasons_and_entity_counts_reach_both_reports(tmp_path):
    backend = make_backend(generic_ops={"premise"})
    run_world_engine(RAW, package_dir=tmp_path, backend=backend, config=cfg(), budget={"max_iterations": 1})
    manifest = json.loads((tmp_path / "run_manifest.json").read_text())
    metrics = manifest["build"]
    assert metrics["accepted"] == 1 and metrics["failed"] == 0
    assert metrics["steps"]["fact"]["calls"] == 3
    assert metrics["steps"]["fact"]["attempts"] == {"2": 1, "1": 1}
    assert "specific" in metrics["steps"]["fact"]["reasons"]
    assert sum(e["calls"] for e in metrics["steps"].values()) == manifest["world_explore"]["counters"]["generation_calls"]
    report = (tmp_path / "final/world_report.md").read_text()
    assert "Entity building" in report and "Attempt distribution" in report and "specific" in report
    run_world_engine(RAW, package_dir=tmp_path, backend=make_backend(), config=cfg(), budget={"max_iterations": 2})
    again = json.loads((tmp_path / "run_manifest.json").read_text())["build"]
    assert again["accepted"] == 2
    assert again["steps"]["fact"]["calls"] > metrics["steps"]["fact"]["calls"]


@pytest.mark.parametrize("step", ["type", "grounding", "axes", "relations", "review"])
def test_runtime_enums_are_scoped_and_empty_context_is_valid_schema(step):
    schema = step_schema(step, types=["practice"], statement_ids=["s1"], entity_ids=["e1"], axis_ids=["a1"], fact_count=2)
    Draft202012Validator.check_schema(schema)
    empty = step_schema(step, types=["practice"])
    Draft202012Validator.check_schema(empty)
    valid = {"type": {"type": "practice"}, "grounding": {"statement_ids": ["s1"], "derived_from": ["e1"], "reason": "derivation"},
        "axes": {"axes": ["a1"]}, "relations": {"relations": [{"type": "related_to", "target": "e1"}]},
        "review": {"verdicts": {k: True for k in ("consistent", "objective", "no_story", "fits_world")}, "issues": []}}[step]
    assert not list(Draft202012Validator(schema).iter_errors(valid))
    if step == "grounding":
        valid["derived_from"] = ["e999"]
    elif step == "relations":
        valid["relations"][0]["target"] = "e999"
    elif step == "axes":
        valid["axes"] = ["unknown"]
    elif step == "type":
        valid["type"] = "document"
    else:
        valid["issues"] = [{"field": "facts[2]", "criterion": "consistent", "reason": "unknown field"}]
    assert list(Draft202012Validator(schema).iter_errors(valid))


@pytest.mark.parametrize("setting,value", [("max_step_attempts", 0), ("max_step_attempts", True), ("review_rounds", -1), ("review_rounds", 1.5)])
def test_invalid_build_settings_are_rejected(setting, value):
    with pytest.raises(ValueError):
        EntityBuilder(make_backend(), {"build": {setting: value}})


@pytest.mark.parametrize("unit", ["hours^2", "years/hours"])
def test_pure_time_combinations_are_not_number_measurements(unit):
    backend = backend_with(lambda step, slot, attempt, prompt, good: {**good, "value": 3, "unit": unit, "fact": f"Capacity is 3 {unit}."} if step == "fact" and slot == 0 else good)
    _, result = build(backend)
    assert result.entity is None and "specific" in result.failure["reason"]


@pytest.mark.parametrize("language,name", [("ja", "照合番"), ("ko", "검사소"), ("zh", "核验处"), ("ru", "Проверка"), ("ar", "تدقيق")])
def test_name_scripts_supported_by_input_detection_are_allowed(language, name):
    g = new_graph(language)
    backend = backend_with(lambda step, slot, attempt, prompt, good: {"name": name} if step == "name" else good)
    _, result = build(backend, g)
    assert result.entity and result.entity["name"] == name, result.failure


@pytest.mark.parametrize("criterion,field,reason", [
    ("fits_world", "summary", "The claimed authority does not follow from the supplied social rules."),
    ("fits_world", "facts[0]", "This method assumes a capability absent from the contract."),
    ("consistent", "facts[0]", "The quantity is incompatible with the described subject."),
    ("consistent", "facts[1]", "The stated object has no connection to this entity."),
    ("no_story", "summary", "The explanation narrates a scene instead of describing reference material."),
])
def test_semantic_review_problems_remain_hard_failures(criterion, field, reason):
    def change(step, slot, attempt, prompt, good):
        if step == "review":
            good["verdicts"][criterion] = False
            good["issues"] = [{"field": field, "criterion": criterion, "reason": reason}]
        return good
    _, result = build(backend_with(change))
    assert result.entity is None and criterion in result.failure["reason"]
    assert reason in result.failure["reason"]
