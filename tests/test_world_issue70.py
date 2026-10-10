"""Purpose-derived entity criteria, using only synthetic fake responses."""

import copy
import json
import re

import pytest
from jsonschema import Draft202012Validator

from src.llm.fake import FakeLLMBackend
from src.world.builder import EntityBuilder
from src.world.contract import establish_contract
from src.world.criteria import contract_terms, measurement_present, new_name, outside_terms, real_world_check
from src.world.graph import new_graph
from src.world.quantities import outside_units
from src.world.schemas import step_schema
from src.world.structured import StructuredFailure
from tests.test_world_builder import backend_with, build, graph
from tests.helpers_world import contract_item, split_fact_output
from tests.test_world_explore import AXES, BRIEF, RAW, SYNTHETIC_PREMISES, cfg, make_backend


FACTS = {
    "proper_noun": {"name": "Zelvra", "fact": "Zelvra marks discarded containers."},
    "object": {"object": "container", "fact": "A container holds discarded tokens."},
    "procedure": {"actor": "clerk", "action": "checks seals", "fact": "The clerk checks seals before storage."},
}


@pytest.mark.parametrize("kind", FACTS)
def test_kind_schemas_require_all_fields_and_preserve_fact_bounds(kind):
    element = split_fact_output("fact_element", FACTS[kind])
    validator = Draft202012Validator(step_schema("fact_element", kind=kind))
    assert validator.is_valid(element)
    for field in element:
        assert not validator.is_valid({k: v for k, v in element.items() if k != field})
        for value in [None, True, 3, ""]:
            assert not validator.is_valid({**element, field: value})
    assert not validator.is_valid({**element, "extra": "extra"})
    body = Draft202012Validator(step_schema("fact_text"))
    assert body.is_valid(split_fact_output("fact_text", FACTS[kind]))
    for value in [None, True, 3, "", "x" * 4, "x" * 201]:
        assert not body.is_valid({"fact": value})


@pytest.mark.parametrize("kind,field,minimum,maximum", [
    ("proper_noun", "name", 2, 30), ("object", "object", 1, 30),
    ("procedure", "actor", 1, 30), ("procedure", "action", 1, 60),
])
def test_kind_schema_exact_field_bounds(kind, field, minimum, maximum):
    validator = Draft202012Validator(step_schema("fact_element", kind=kind))
    element = split_fact_output("fact_element", FACTS[kind])
    for length in [minimum, maximum]:
        assert validator.is_valid({**element, field: "x" * length})
    for length in [minimum - 1, maximum + 1]:
        assert not validator.is_valid({**element, field: "x" * length})


@pytest.mark.parametrize("slot,field", [(1, "name"), (2, "object"), (3, "actor"), (3, "action")])
def test_missing_field_in_body_is_detail_failure(slot, field):
    def change(step, current, attempt, prompt, good):
        if step == "fact_text" and current == slot:
            fields = {key: json.loads(value) for key, value in
                      re.findall(r'^(name|object|actor|action): (.+)$', prompt, re.M)}
            return {"fact": "Retained " + " ".join(value for key, value in fields.items()
                                                     if key != field) + "."}
        return good
    _, result = build(backend_with(change), graph("site"), "zoom", "e5", SYNTHETIC_PREMISES,
                      config={"build": {"max_step_attempts": 2}})
    assert result.entity is None and result.failure["slot"] == slot
    assert "detail" in result.failure["reason"]
    assert len([r for r in result.steps if r.step == "fact_text" and r.slot == slot]) == 4


@pytest.mark.parametrize("source", ["raw", "brief", "local_name", "local_fact", "all_names",
                                  "calendar", "marker", "unit", "institution", "capability"])
@pytest.mark.parametrize("embedded", [False, True])
def test_new_name_normalizes_and_checks_every_source(source, embedded):
    value = "prefix Ｚｅｌ Ｖｒａ suffix" if embedded else "Ｚｅｌ Ｖｒａ"
    raw, brief, views, entities, contract = "", {}, [], [], {}
    if source == "raw":
        raw = value
    elif source == "brief":
        brief = {"statements": [{"text": value}]}
    elif source == "local_name":
        views = [{"name": value}]
    elif source == "local_fact":
        views = [{"facts": [{"text": value}]}]
    elif source == "all_names":
        entities = [{"name": value}]
    elif source == "calendar":
        contract = {"calendar": {"name": value}}
    elif source == "marker":
        contract = {"calendar": {"markers": [value]}}
    elif source == "unit":
        contract = {"technology": {"units": [{"symbol": value, "quantity": "description"}]}}
    elif source == "institution":
        contract = {"society": {"institutions": [{"name": value, "description": "description"}]}}
    else:
        contract = {"technology": {"capabilities": [value]}}
    assert not new_name("zelvra", raw, brief, views, entities, contract)
    assert new_name("Tavren", raw, brief, views, entities, contract)


def test_existing_proper_name_is_rejected_by_new_information():
    def change(step, slot, attempt, prompt, good):
        if step in {"fact_element", "fact_text"} and slot == 1:
            return split_fact_output(step, {"name": "alpha", "fact": "The alpha registry handles the records."})
        return good
    _, result = build(backend_with(change), config={"build": {"max_step_attempts": 2}})
    assert not result.entity and result.failure["slot"] == 1
    assert "new_information" in result.failure["reason"] and "name must be new" in result.failure["reason"]


@pytest.mark.parametrize("text", ["Capacity is 120 k2s.", "Capacity is １２０ ｋ２ｓ。",
                                  "Capacity is 120k2s and 3 k2."])
def test_digit_bearing_contract_symbols_are_removed_as_whole_tokens(text):
    contract = copy.deepcopy(SYNTHETIC_PREMISES)
    contract["technology"]["units"] = [{"symbol": s, "quantity": "capacity"} for s in ["k", "k2", "k2s"]]
    assert outside_units(text, contract, {}) == []
    assert outside_units(text + " Additional capacity is 4 uv.", contract, {}) == ["uv"]
    assert outside_units("Capacity is 120k2sx.", contract, {})


@pytest.mark.parametrize("field", ["summary", "number", "object"])
def test_digit_bearing_unit_passes_entity_checks(field):
    contract = copy.deepcopy(SYNTHETIC_PREMISES)
    contract["technology"]["units"].append({"symbol": "k2s", "quantity": "capacity"})
    def change(step, slot, attempt, prompt, good):
        if field == "summary" and step == "summary":
            return {"summary": "The retained containers have a measured capacity of 120 k2s."}
        if field == "number" and step in {"fact_element", "fact_text"} and slot == 0:
            return split_fact_output(step, {**good, "value": 120, "unit": "k2s", "fact": "Capacity is 120 k2s."})
        if field == "object" and step in {"fact_element", "fact_text"} and slot == 2:
            return split_fact_output(step, {"object": "containers", "fact": "The containers retain 120 k2s."})
        return good
    _, result = build(backend_with(change), graph("settlement"), "expand", "e3", contract)
    assert result.entity, result.failure


@pytest.mark.parametrize("field", ["summary", "object"])
def test_unregistered_body_units_fail_no_outside_premises(field):
    def change(step, slot, attempt, prompt, good):
        if field == "summary" and step == "summary":
            return {"summary": "The retained containers have a measured capacity of 120 uv."}
        if field == "object" and step in {"fact_element", "fact_text"} and slot == 2:
            return split_fact_output(step, {"object": "containers", "fact": "The containers retain 120 uv."})
        return good
    _, result = build(backend_with(change), graph("settlement"), "expand", "e3", SYNTHETIC_PREMISES)
    assert not result.entity and "no_outside_premises" in result.failure["reason"]


def test_number_body_rejects_unregistered_units_after_element_acceptance():
    backend = backend_with(lambda step, slot, attempt, prompt, good:
        split_fact_output(step, {**good, "fact": good["fact"] + " Additional reading is 120 uv."})
        if step == "fact_text" and slot == 0 else good)
    _, result = build(backend, contract=SYNTHETIC_PREMISES)
    assert result.entity is None and result.failure["step"] == "fact_text"
    assert "no_outside_premises" in result.failure["reason"]


TERMS = ["Zelvra", "Tavren"]
GOOD_CHECK = {"items": [{"term": t, "category": "invented", "reason": "Invented name."} for t in TERMS]}


REAL_CATEGORIES = ["real_calendar", "real_unit", "real_person_name",
                   "real_place_name", "real_organization_name"]
CATEGORIES = [*REAL_CATEGORIES, "general_word", "invented"]


@pytest.mark.parametrize("category", CATEGORIES)
def test_real_world_category_schema_and_reason_bounds(category):
    validator = Draft202012Validator(step_schema("real_world_check", terms=["Zelvra"]))
    item = {"term": "Zelvra", "category": category, "reason": "Explanation."}
    assert validator.is_valid({"items": [item]})
    for length in [1, 200]:
        assert validator.is_valid({"items": [{**item, "reason": "x" * length}]})
    for length in [0, 201]:
        assert not validator.is_valid({"items": [{**item, "reason": "x" * length}]})
    for field in item:
        assert not validator.is_valid({"items": [{k: v for k, v in item.items() if k != field}]})
    for invalid in [True, False, "real_other", "", None, 3]:
        assert not validator.is_valid({"items": [{**item, "category": invalid}]})
    assert not validator.is_valid({"items": [{**item, "real_world": False}]})
    assert not validator.is_valid({"items": [{**item, "term": "Other"}]})


@pytest.mark.parametrize("category", CATEGORIES)
@pytest.mark.parametrize("allowed", [False, True])
def test_only_real_categories_absent_from_normalized_input_are_violations(category, allowed):
    item = {"term": "Zelvra", "category": category, "reason": "Classification fixture."}
    raw = "prefix ＺＥＬ ＶＲＡ suffix" if allowed else "Unrelated source."
    assert outside_terms({"items": [item]}, raw) == (
        [item] if category in REAL_CATEGORIES and not allowed else [])


def test_contract_accepts_general_words_absent_from_original_input():
    general_words = {"term", "quota", "seal", "ledger"}
    contract_calls, judgments = [], []
    def respond(prompt):
        if prompt.startswith("WORLD CONTRACT"):
            contract_calls.append(prompt)
            return contract_item(SYNTHETIC_PREMISES, prompt)
        terms = json.JSONDecoder().raw_decode(prompt.split("TERMS:\n", 1)[1])[0]
        judgments.extend(terms)
        return {"items": [{"term": t,
                           "category": "general_word" if t in general_words else "invented",
                           "reason": "Ordinary word." if t in general_words else "Invented name."}
                          for t in terms]}
    backend = FakeLLMBackend(respond)
    g = new_graph("en")
    stage = establish_contract(backend, g, BRIEF, AXES, max_attempts=2, raw_input=RAW)
    assert stage["status"] == "success" and stage["attempts"] == len(contract_calls) == 16
    assert g["world_contract"]["world_premises"] == SYNTHETIC_PREMISES
    assert general_words <= set(judgments)
    assert all(t not in RAW for t in general_words)
    assert backend._structured_metrics["real_world_check"]["conversions"]["tried"] == 0


@pytest.mark.parametrize("bad", [
    {"items": GOOD_CHECK["items"][:1]},
    {"items": GOOD_CHECK["items"] + GOOD_CHECK["items"][:1]},
    {"items": [GOOD_CHECK["items"][0], GOOD_CHECK["items"][0]]},
    {"items": [GOOD_CHECK["items"][0], {"term": "Other", "category": "invented", "reason": "Other name."}]},
    "Unstructured answer",
])
def test_real_world_check_repairs_term_underflow_overflow_duplicates_and_unknowns(bad):
    backend = FakeLLMBackend([bad, GOOD_CHECK])
    result = real_world_check(backend, TERMS, language="en", max_attempts=2, max_conversions=2)
    assert result.data == GOOD_CHECK and result.attempts == 2
    assert len(backend.schema_calls) == 2 and result.conversions == 0
    assert "REPAIR INSTRUCTIONS" in backend.json_prompts[1]
    assert all(v["message"] in backend.json_prompts[1] for v in result.violations[0])


@pytest.mark.parametrize("field", ["calendar", "marker", "unit", "institution", "capability"])
@pytest.mark.parametrize("allowed", [False, True])
def test_contract_real_world_terms_regenerate_unless_in_original_input(field, allowed):
    bad = copy.deepcopy(SYNTHETIC_PREMISES)
    term = "Zelvra"
    if field == "calendar":
        bad["calendar"]["name"] = term
    elif field == "marker":
        bad["calendar"]["markers"][0] = term
    elif field == "unit":
        bad["technology"]["units"][0]["symbol"] = term
    elif field == "institution":
        bad["society"]["institutions"][0]["name"] = term
    else:
        bad["technology"]["capabilities"][0] = term
    contracts = []
    def respond(prompt):
        if prompt.startswith("WORLD CONTRACT"):
            contracts.append(prompt)
            if "PREVIOUS OUTPUT" in prompt:
                assert term in prompt and "Real system fixture." in prompt and "real_unit" in prompt
            return contract_item(SYNTHETIC_PREMISES if "PREVIOUS OUTPUT" in prompt else bad, prompt)
        terms = json.JSONDecoder().raw_decode(prompt.split("TERMS:\n", 1)[1])[0]
        return {"items": [{"term": t, "category": "real_unit" if t == term else "invented",
                           "reason": "Real system fixture."} for t in terms]}
    backend = FakeLLMBackend(respond)
    g = new_graph("en")
    stage = establish_contract(backend, g, BRIEF, AXES, max_attempts=2,
                              raw_input="prefix ＺＥＬ ＶＲＡ suffix" if allowed else "")
    assert stage["attempts"] == len(contracts) == (16 if allowed else 17)
    assert g["world_contract"]["world_premises"] == (bad if allowed else SYNTHETIC_PREMISES)
    assert all(entry["conversions"]["tried"] == 0 for task, entry in backend._structured_metrics.items() if task.startswith("contract/"))


def test_contract_real_world_exhaustion_is_failed_and_resumable():
    inner = make_backend()
    backend = FakeLLMBackend(lambda prompt:
        {"items": [{"term": t, "category": "real_calendar", "reason": "Real fixture system."}
                   for t in json.JSONDecoder().raw_decode(prompt.split("TERMS:\n", 1)[1])[0]]}
        if "STEP: real_world_check\n" in prompt else inner.generate_schema(prompt, {}, constrained=True))
    g = new_graph("en")
    with pytest.raises(StructuredFailure):
        establish_contract(backend, g, BRIEF, AXES, max_attempts=2)
    assert g["contract_stage"]["status"] == "failed" and g["contract_stage"]["attempts"] == 4
    assert "world_contract" not in g
    count = len(backend.schema_calls)
    with pytest.raises(StructuredFailure):
        establish_contract(backend, g, BRIEF, AXES)
    assert len(backend.schema_calls) == count


@pytest.mark.parametrize("step,slot", [("name", None), ("fact_element", 1)])
def test_real_name_rewrites_only_its_step_with_reason(step, slot):
    judged = 0
    def change(current, current_slot, attempt, prompt, good):
        nonlocal judged
        if current == step and current_slot == slot and attempt == 1:
            if step == "name":
                return {"name": "Zelvra"}
            return {"name": "Zelvra"}
        if current == "real_world_check":
            if good["items"][0]["term"] == "Zelvra":
                judged += 1
                good["items"][0].update(category="real_person_name", reason="Real fixture name.")
        if current == step and current_slot == slot and attempt == 2:
            assert "Zelvra" in prompt and "Real fixture name." in prompt
        return good
    backend = backend_with(change)
    _, result = build(backend)
    assert result.entity and judged == 1
    assert backend.attempts[(step, slot)] == 2
    assert backend.attempts[("summary", None)] == 1
    assert result.calls == len(backend.schema_calls)
    row = next(r for r in result.steps if r.step == step and r.slot == slot)
    assert not row.accepted and any(c["criterion"] == "no_outside_premises" and not c["ok"] for c in row.checks)


def test_entity_name_in_original_input_is_allowed_even_if_real():
    def change(step, slot, attempt, prompt, good):
        if step == "name":
            return {"name": "Zelvra"}
        if step == "real_world_check" and good["items"][0]["term"] == "Zelvra":
            good["items"][0].update(category="real_person_name", reason="Real fixture name.")
        return good
    builder = EntityBuilder(backend_with(change))
    result = builder.build(new_graph("en"), "premise", None, brief=BRIEF, axes=AXES,
        contract={}, frontier_axis=None, raw_input="prefix ＺＥＬ ＶＲＡ suffix")
    assert result.entity and result.entity["name"] == "Zelvra"
    assert [r.attempt for r in result.steps if r.step == "name"] == [1]


@pytest.mark.parametrize("source", ["brief", "local", "global"])
@pytest.mark.parametrize("structured", [False, True])
def test_measurement_pairs_found_in_all_reference_sources(source, structured):
    fact = {"text": "Capacity is １，２００ k2s."}
    if structured:
        fact.update(value=1200, unit="k2s")
    brief, views, entities = {}, [], []
    if source == "brief":
        brief = {"statements": [{"text": fact["text"]}]}
    elif source == "local":
        views = [{"facts": [fact]}]
    else:
        entities = [{"facts": [fact]}]
    assert measurement_present(1200, "k2s", brief, views, entities)
    assert not measurement_present(120, "k2s", brief, views, entities)
    assert not measurement_present(1200, "k2", brief, views, entities)


@pytest.mark.parametrize("recover", [False, True])
def test_repeated_measurement_pair_rebuilds_only_the_element_stage(monkeypatch, recover):
    monkeypatch.setattr("src.world.builder.fact_plan", lambda *args: ["number", "object"])
    g = graph()
    g["entities"][0]["facts"] = [{"kind": "number", "value": 12, "unit": "quota",
                                  "text": "Measured capacity is 12 quota."}]
    def change(step, slot, attempt, prompt, good):
        if step == "fact_element" and slot == 0:
            if attempt > 1:
                assert "new_information" in prompt and "(12, quota)" in prompt
            value = 13 if attempt > 1 and recover else 12
            return split_fact_output(step, {**good, "value": value, "fact": f"Measured capacity is {value} quota."})
        return good
    backend = backend_with(change)
    builder, result = build(backend, g, config={"build": {"max_step_attempts": 2}})
    assert backend.attempts[("fact_element", 0)] == 2
    assert backend.attempts.get(("fact_text", 0), 0) == (1 if recover else 0)
    assert not next(r for r in result.steps if r.step == "fact_element" and r.slot == 0).accepted
    assert builder.metrics["steps"]["fact_element"]["reasons"]["new_information"]
    if recover:
        assert result.entity and result.entity["facts"][0]["value"] == 13
    else:
        assert result.entity is None and result.failure["step"] == "fact_element" and result.failure["slot"] == 0
        assert "new_information" in result.failure["reason"]


def test_repeated_period_pair_is_rejected_at_the_element_stage(monkeypatch):
    monkeypatch.setattr("src.world.builder.fact_plan", lambda *args: ["period"])
    g = graph()
    g["entities"][0]["facts"] = [{"kind": "period", "marker": "VelaCount", "value": 3,
                                  "text": "The cycle lasts VelaCount 3."}]
    def change(step, slot, attempt, prompt, good):
        if step == "fact_element":
            return {"marker": "VelaCount", "value": 3 if attempt == 1 else 4}
        if step == "fact_text":
            return {"fact": "Records are rotated after VelaCount 4 completes."}
        return good
    backend = backend_with(change)
    _, result = build(backend, g, contract=SYNTHETIC_PREMISES, config={"build": {"max_step_attempts": 2}})
    assert result.entity, result.failure
    assert backend.attempts[("fact_element", 0)] == 2 and backend.attempts[("fact_text", 0)] == 1
    first = next(r for r in result.steps if r.step == "fact_element")
    assert any(c["criterion"] == "new_information" and not c["ok"] for c in first.checks)


def test_duplicate_fact_text_rebuilds_only_the_text_stage(monkeypatch):
    monkeypatch.setattr("src.world.builder.fact_plan", lambda *args: ["number", "object"])
    g = graph()
    existing = "The containers hold the sealed tokens across every exchange cycle."
    g["entities"][0]["facts"] = [{"kind": "object", "object": "containers", "text": existing}]
    def change(step, slot, attempt, prompt, good):
        if step == "fact_element" and slot == 1:
            return {"object": "containers"}
        if step == "fact_text" and slot == 1:
            if attempt > 1:
                assert "new_information" in prompt and existing in prompt
                return {"fact": "Physical containers keep discarded tokens apart."}
            return {"fact": existing.replace("The", "the")}
        return good
    backend = backend_with(change)
    _, result = build(backend, g, config={"build": {"max_step_attempts": 2}})
    assert result.entity
    assert backend.attempts[("fact_element", 1)] == 1 and backend.attempts[("fact_text", 1)] == 2


def test_contract_term_collection_uses_names_and_symbols_without_descriptions():
    contract = copy.deepcopy(SYNTHETIC_PREMISES)
    contract["society"]["institutions"] = [{"name": "Zelvra", "description": "Tavren"}]
    terms = contract_terms(contract)
    assert set(terms) == {"VelaCount", "VelaRise", "VelaRest", "term", "quota", "vel", "seal", "ledger", "tally", "Zelvra"}
    assert len(terms) == len(set(terms))


@pytest.mark.parametrize("text", ["容量は12quota。", "容量は１２ ｑｕｏｔａ。", "Capacity is 12 quota."])
def test_measurement_pair_matches_cjk_prose(text):
    assert measurement_present(12, "quota", {"statements": [{"text": text}]}, [], [])


def test_summary_overlap_is_not_a_rejection_when_entity_adds_new_information():
    g = graph()
    summary = "The records define paired checks after each exchange and retain discarded tokens in separate boxes."
    g["entities"][0]["summary"] = summary
    _, result = build(backend_with(lambda step, slot, attempt, prompt, good:
        {"summary": summary} if step == "summary" else good), g, "expand", "e1")
    assert result.entity and result.entity["summary"] == summary
    assert [r.attempt for r in result.steps if r.step == "summary"] == [1]


@pytest.mark.parametrize("source_name", [None, "original.txt"])
def test_raw_input_reaches_contract_and_entity_checks_through_engine(tmp_path, source_name):
    from src.world.explore import run_world_engine
    inner = make_backend()
    def respond(prompt):
        if "STEP: name\n" in prompt:
            return {"name": "alpha rule"}
        if "STEP: real_world_check\n" in prompt:
            terms = json.JSONDecoder().raw_decode(prompt.split("TERMS:\n", 1)[1])[0]
            return {"items": [{"term": t, "category": "real_organization_name" if t == "alpha rule" else "invented", "reason": "Real fixture name."}
                              for t in terms]}
        return inner.generate_schema(prompt, {}, constrained=True)
    backend = FakeLLMBackend(respond)
    result = run_world_engine(RAW, package_dir=tmp_path, backend=backend,
        source_name=source_name, config=cfg(), budget={"max_iterations": 1})
    assert result.counters["accepted"] == 1
    assert result.graph["entities"][0]["name"] == "alpha rule"
    names = [c for c in backend.schema_calls if "STEP: name\n" in c["prompt"]]
    assert len(names) == 1
    proper_names = [e["facts"][1]["name"] for e in result.graph["entities"]]
    assert all(n not in RAW for n in proper_names)


def test_new_name_checks_descriptions_without_generated_brief_ids():
    brief = {"statements": [{"id": "Zelvra", "text": "Records are shared.", "quote": "Records"}],
             "open_questions": [{"id": "Tavren", "text": "Who keeps records?"}],
             "constraints": [{"id": "Ravlek", "text": "Keep the descriptions objective."}]}
    for name in ["Zelvra", "Tavren", "Ravlek"]:
        assert new_name(name, "", brief, [], [], {})
    for name in ["records", "keeps", "objective"]:
        assert not new_name(name, "", brief, [], [], {})
