"""Issue #75: independently generated contract slots (offline backend only)."""

import copy
import json
import re
from collections import Counter

import pytest
from jsonschema import Draft202012Validator

from src.llm.fake import FakeLLMBackend
from src.world.contract import ITEMS, establish_contract
from src.world.explore import run_world_engine
from src.world.graph import GraphStore, new_graph
from src.world.schemas import load_schema, step_schema
from src.world.structured import StructuredFailure
from tests.helpers_world import configure_contract, contract_item
from tests.test_world_explore import AXES, BRIEF, RAW, SYNTHETIC_PREMISES, cfg, make_backend


def item_calls(backend):
    return [call for call in backend.schema_calls
            if call["prompt"].startswith("WORLD CONTRACT ITEM\n")]


def slot(prompt):
    return (re.search(r"^ITEM: (.+)$", prompt, re.M).group(1),
            re.search(r"^SLOT: (.+)$", prompt, re.M).group(1))


def test_each_call_generates_only_one_item_in_order_with_decided_context():
    backend = make_backend()
    graph = new_graph("en")
    original = copy.deepcopy((BRIEF, AXES))
    stage = establish_contract(backend, graph, BRIEF, AXES, raw_input=RAW)
    calls = item_calls(backend)
    expected = [(item, str(i) if setting else "None")
                for item, _, _, _, setting, _ in ITEMS
                for i in range(3 if setting else 1)]
    assert [slot(call["prompt"]) for call in calls] == expected
    assert len(calls) == stage["attempts"] == 16
    assert len(backend.schema_calls) == 29
    accepted = {"calendar": {}, "technology": {}, "society": {}}
    position = 0
    for item, section, field, key, setting, _ in ITEMS:
        if setting:
            accepted[section][field] = []
        for _ in range(3 if setting else 1):
            call = calls[position]
            position += 1
            assert call["schema"] == load_schema("contract/" + item)
            assert set(call["schema"]["required"]) == ({key} if key else
                {"symbol", "quantity"} if item == "unit" else {"name", "description"})
            prompt = call["prompt"]
            context = json.JSONDecoder().raw_decode(prompt.split("INPUT BRIEF AND AXES:\n")[1])[0]
            assert context["statements"] == [{"id": s["id"], "text": s["text"]} for s in BRIEF["statements"]]
            assert context["axes"] == [{k: a[k] for k in ("name", "meaning")} for a in AXES]
            assert json.JSONDecoder().raw_decode(prompt.split("CONTRACT ITEMS ALREADY DECIDED:\n")[1])[0] == accepted
            assert "invent names for this world" in prompt
            assert "input may be used verbatim" in prompt
            output = contract_item(SYNTHETIC_PREMISES, prompt)
            value = output[key] if key else output
            if setting:
                accepted[section][field].append(value)
            else:
                accepted[section][field] = value
    assert graph["world_contract"]["world_premises"] == accepted == SYNTHETIC_PREMISES
    assert (BRIEF, AXES) == original
    assert not graph["entities"]
    assert Draft202012Validator(load_schema("world_contract")).is_valid(accepted)
    assert step_schema("fact_element", kind="number", contract=accepted)["properties"]["unit"]["enum"] == ["term", "quota", "vel"]
    assert step_schema("fact_element", kind="period", contract=accepted)["properties"]["marker"]["enum"] == ["VelaCount", "VelaCount", "VelaRise", "VelaRest"]
    terms = [json.JSONDecoder().raw_decode(c["prompt"].split("TERMS:\n")[1])[0]
             for c in backend.schema_calls if "STEP: real_world_check\n" in c["prompt"]]
    assert len(terms) == 13 and all(len(values) == 1 for values in terms)
    assert not any(t in terms for t in [[accepted["calendar"]["origin"]],
        [accepted["technology"]["description"]], [accepted["society"]["description"]]])
    assert establish_contract(backend, graph, BRIEF, AXES) == stage
    assert len(backend.schema_calls) == 29


@pytest.mark.parametrize("bad_symbol", ["L", "kg"])
def test_only_rejected_unit_slot_is_regenerated_with_previous_output_and_category(tmp_path, bad_symbol):
    inner = make_backend()
    attempts = Counter()
    raw_source = "Recorded quota."
    def respond(prompt):
        if prompt.startswith("SOURCE MATERIAL"):
            return {"statements": [{"text": raw_source, "quote": raw_source}],
                    "open_questions": [], "constraints": []}
        if "STEP: real_world_check\n" in prompt:
            terms = json.JSONDecoder().raw_decode(prompt.split("TERMS:\n")[1])[0]
            return {"items": [{"term": t, "category": "real_unit" if t == bad_symbol else "invented",
                               "reason": "Existing real measurement unit." if t == bad_symbol else "Synthetic term."}
                              for t in terms]}
        if prompt.startswith("WORLD CONTRACT ITEM\n"):
            pair = slot(prompt)
            attempts[pair] += 1
            if pair == ("unit", "1"):
                if attempts[pair] == 1:
                    return {"symbol": bad_symbol, "quantity": "Measured capacity"}
                assert f'"symbol": "{bad_symbol}"' in prompt
                assert "real_unit" in prompt and "Existing real measurement unit." in prompt
                assert "PREVIOUS OUTPUT" in prompt
        return json.loads(inner.generate_schema(prompt, {}, constrained=True))
    backend = FakeLLMBackend(respond)
    result = run_world_engine(raw_source, package_dir=tmp_path, backend=backend, config=cfg(), budget={"max_iterations": 1})
    assert len(attempts) == 16 and attempts[("unit", "1")] == 2
    assert all(count == 1 for pair, count in attempts.items() if pair != ("unit", "1"))
    assert result.graph["world_contract"]["world_premises"] == SYNTHETIC_PREMISES
    stage = result.graph["contract_stage"]
    record = next(s for s in stage["steps"] if (s["step"], s["slot"]) == ("unit", 1))
    assert record["attempts"] == 2 and record["calls"] == 4 and record["accepted"]
    violation, = record["violations"][0]
    assert violation["category"] == "real_unit" and violation["reason"] == "Existing real measurement unit."
    assert stage["metrics"]["steps"]["unit"]["attempts"] == {"1": 2, "2": 1}
    assert stage["metrics"]["steps"]["unit"]["calls"] == 8
    manifest = json.loads((tmp_path / "run_manifest.json").read_text())
    assert manifest["world_contract"] == stage
    report = (tmp_path / "final/world_report.md").read_text()
    assert '| unit | 1 | 4 | {"2": 1} | 0 |' in report
    assert '| unit | 8 | {"1": 2, "2": 1} | 0 |' in report
    assert "real_unit" in report and "Existing real measurement unit." in report
    before = copy.deepcopy(stage)
    resumed = make_backend()
    again = run_world_engine(raw_source, package_dir=tmp_path, backend=resumed, config=cfg(), budget={"max_iterations": 2})
    assert not item_calls(resumed) and again.graph["contract_stage"] == before
    assert json.loads((tmp_path / "run_manifest.json").read_text())["world_contract"] == before


def test_item_exhaustion_records_failed_slot_and_reason_in_manifest_and_report(tmp_path):
    inner = make_backend()
    def respond(prompt):
        if "ITEM: unit\nSLOT: 1\n" in prompt:
            return {"symbol": "kg", "quantity": "Measured capacity"}
        if "STEP: real_world_check\n" in prompt:
            terms = json.JSONDecoder().raw_decode(prompt.split("TERMS:\n")[1])[0]
            return {"items": [{"term": t, "category": "real_unit" if t == "kg" else "invented",
                               "reason": "Existing mass unit." if t == "kg" else "Synthetic term."} for t in terms]}
        return json.loads(inner.generate_schema(prompt, {}, constrained=True))
    backend = FakeLLMBackend(respond)
    with pytest.raises(StructuredFailure) as failure:
        run_world_engine(RAW, package_dir=tmp_path, backend=backend, config=cfg(), budget={"max_iterations": 1})
    assert failure.value.task == "world_contract" and failure.value.result.attempts == 4
    graph = GraphStore(tmp_path).load()
    assert not graph["entities"] and "world_contract" not in graph
    stage = graph["contract_stage"]
    assert stage["status"] == "failed" and not stage["checks_enabled"]
    assert stage["failure"]["step"] == "unit" and stage["failure"]["slot"] == 1
    assert "real_unit" in stage["failure"]["reason"] and "Existing mass unit." in stage["failure"]["reason"]
    counts = Counter(slot(call["prompt"]) for call in item_calls(backend))
    assert counts[("unit", "1")] == 4 and counts[("unit", "0")] == 1
    assert all(n == 1 for pair,n in counts.items() if pair != ("unit", "1"))
    assert ("unit", "2") not in counts and ("society_description", "None") not in counts
    assert stage["metrics"]["steps"]["unit"]["attempts"] == {"1": 1, "4": 1}
    assert stage["metrics"]["steps"]["unit"]["failures"] == 1
    manifest = json.loads((tmp_path / "run_manifest.json").read_text())
    assert manifest["status"] == "failed" and manifest["world_contract"] == stage
    report = (tmp_path / "final/world_report.md").read_text()
    assert '| unit | 1 | 8 | {"4": 1} | 1 |' in report
    assert "Existing mass unit." in report and "real_unit" in report
    resumed = make_backend()
    with pytest.raises(StructuredFailure):
        run_world_engine(RAW, package_dir=tmp_path, backend=resumed, config=cfg())
    assert not resumed.schema_calls
    assert json.loads((tmp_path / "run_manifest.json").read_text())["world_contract"] == stage


@pytest.mark.parametrize("item,field", [("calendar_marker", "marker"), ("capability", "capability"),
                                      ("unit", "symbol"), ("institution", "name")])
def test_duplicate_rewrites_only_duplicate_slot(item, field):
    inner = make_backend()
    calls = Counter()
    first = None
    def respond(prompt):
        nonlocal first
        if prompt.startswith("WORLD CONTRACT ITEM\n"):
            current, index = slot(prompt)
            calls[(current, index)] += 1
            good = contract_item(SYNTHETIC_PREMISES, prompt)
            if current == item and index == "0":
                first = good[field]
            if current == item and index == "1":
                if calls[(current, index)] == 1:
                    return {**good, field: first}
                assert "duplicate:" in prompt and "PREVIOUS OUTPUT" in prompt
            return good
        return json.loads(inner.generate_schema(prompt, {}, constrained=True))
    graph = new_graph("en")
    stage = establish_contract(FakeLLMBackend(respond), graph, BRIEF, AXES)
    assert calls[(item, "1")] == 2 and len(calls) == 16
    assert all(n == 1 for pair,n in calls.items() if pair != (item, "1"))
    assert stage["status"] == "success" and graph["world_contract"]["world_premises"] == SYNTHETIC_PREMISES
    assert len(stage["errors"]) == 1 and "duplicate:" in stage["errors"][0]["errors"][0]


def test_configured_counts_and_attempt_limit_are_used(tmp_path, monkeypatch):
    contract = copy.deepcopy(SYNTHETIC_PREMISES)
    contract["calendar"]["markers"] = contract["calendar"]["markers"][:2]
    contract["technology"]["capabilities"] = contract["technology"]["capabilities"][:1]
    contract["technology"]["units"] = contract["technology"]["units"][:1]
    contract["society"]["institutions"] = []
    configure_contract(monkeypatch, tmp_path, contract, max_item_attempts=2)
    from tests.helpers_world import contract_backend
    backend = contract_backend(contract)
    graph = new_graph("en")
    stage = establish_contract(backend, graph, BRIEF, AXES)
    assert stage["attempts"] == 8 and len(item_calls(backend)) == 8
    assert graph["world_contract"]["world_premises"] == contract
    failed = new_graph("en")
    with pytest.raises(StructuredFailure) as caught:
        establish_contract(FakeLLMBackend({}), failed, BRIEF, AXES, max_attempts=5, max_conversions=0)
    assert caught.value.result.attempts == 2
    assert failed["contract_stage"]["failure"]["step"] == "calendar_name"


@pytest.mark.parametrize("item", [entry[0] for entry in ITEMS])
def test_item_schemas_are_closed_and_valid(item):
    schema = load_schema("contract/" + item)
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert not Draft202012Validator(schema).is_valid({})


@pytest.mark.parametrize("value", ["", "x" * 31, "a b", "a(b", "a：b", "a。b"])
def test_capability_uses_bounded_short_notation(value):
    assert not Draft202012Validator(load_schema("contract/capability")).is_valid({"capability": value})


def test_existing_notation_and_definition_constraints_are_preserved():
    whole = load_schema("world_contract")["properties"]
    calendar = whole["calendar"]["properties"]
    technology = whole["technology"]["properties"]
    society = whole["society"]["properties"]
    assert load_schema("contract/calendar_name")["properties"]["name"] == calendar["name"]
    assert load_schema("contract/calendar_marker")["properties"]["marker"] == calendar["markers"]["items"]
    assert load_schema("contract/unit")["properties"] == technology["units"]["items"]["properties"]
    assert load_schema("contract/institution")["properties"] == society["institutions"]["items"]["properties"]
    capability = load_schema("contract/capability")["properties"]["capability"]
    assert capability == {"type": "string", "minLength": 1, "maxLength": 30, "pattern": calendar["name"]["pattern"]}
    for item,key in [("calendar_origin", "origin"), ("technology_description", "description"),
                     ("society_description", "description")]:
        schema = load_schema("contract/" + item)
        validator = Draft202012Validator(schema)
        assert validator.is_valid({key: "x"}) and validator.is_valid({key: "x" * 160})
        assert not validator.is_valid({key: ""}) and not validator.is_valid({key: "x" * 161})


def test_invalid_term_judgment_cannot_accept_a_contract_item():
    inner = make_backend()
    def respond(prompt):
        if "STEP: real_world_check\n" in prompt:
            return {"items": []}
        return json.loads(inner.generate_schema(prompt, {}, constrained=True))
    backend = FakeLLMBackend(respond)
    graph = new_graph("en")
    with pytest.raises(StructuredFailure):
        establish_contract(backend, graph, BRIEF, AXES, max_attempts=2, max_conversions=0)
    assert len(item_calls(backend)) == 4 and len(backend.schema_calls) == 12
    stage = graph["contract_stage"]
    assert stage["failure"]["step"] == "calendar_name" and stage["failure"]["slot"] is None
    assert "no_outside_premises" in stage["failure"]["reason"]
    assert stage["steps"][0]["calls"] == 12 and not stage["steps"][0]["accepted"]
    assert "world_contract" not in graph and not graph["entities"]
    assert backend._structured_metrics["real_world_check"]["failures"] == 4
