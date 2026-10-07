"""Issue #62: contract unit notation is separate from its description."""

import copy
import json

import pytest
from jsonschema import Draft202012Validator

from src.llm.fake import FakeLLMBackend
from src.world.contract import establish_contract
from src.world.graph import GraphStore, make_entity, new_graph
from src.world.language import load_language_rules, rules_for
from src.world.premises import normalize_premises, premise_errors, unit_symbols, world_premises
from src.world.quantities import registered_unit, units_in_text
from src.world.render import render_world_package
from src.world.schemas import load_schema, step_schema
from tests.test_world_explore import AXES, BRIEF, SYNTHETIC_PREMISES


def contract_with_units(*units):
    contract = copy.deepcopy(SYNTHETIC_PREMISES)
    contract["technology"]["units"] = list(units)
    return contract


@pytest.mark.parametrize("unit", [
    "qx", {}, {"symbol": "qx"}, {"quantity": "Capacity"},
    {"symbol": "qx", "quantity": "Capacity", "extra": "unexpected"},
    *({"symbol": symbol, "quantity": "Capacity"} for symbol in (
        "", "x" * 13, 3, None, "a b", "a\tb", "a\nb", "a\u3000b",
        "a(b", "a)b", "a（b", "a）b", "a:b", "a：b", "a,b", "a、b", "a;b", "a；b")),
    *({"symbol": "qx", "quantity": quantity} for quantity in ("", "x" * 61, 3, None)),
])
def test_contract_schema_rejects_malformed_unit_definitions(unit):
    errors = list(Draft202012Validator(load_schema("world_contract"))
                  .iter_errors(contract_with_units(unit)))
    assert errors
    assert all(list(error.absolute_path)[:3] == ["technology", "units", 0]
               for error in errors)
    if isinstance(unit, dict):
        assert premise_errors(contract_with_units(unit))


@pytest.mark.parametrize("symbol", ["q", "x" * 12, "槽", "qx/uv", "qx²", "%", "μx"])
@pytest.mark.parametrize("quantity", ["x", "x" * 60])
def test_contract_accepts_bounded_arbitrary_symbols_and_descriptions(symbol, quantity):
    contract = contract_with_units({"symbol": symbol, "quantity": quantity})
    assert Draft202012Validator(load_schema("world_contract")).is_valid(contract)
    assert normalize_premises(contract) == contract


@pytest.mark.parametrize("description", ["length measurement", "長さ（比較用）", "長さ：比較値"])
def test_description_used_as_symbol_enters_contract_schema_repair_loop(description):
    invalid = contract_with_units({"symbol": description, "quantity": "Measured length"})
    valid = contract_with_units({"symbol": "qx", "quantity": "Measured length"})
    backend = FakeLLMBackend([invalid, valid])
    graph = new_graph("en")
    stage = establish_contract(backend, graph, BRIEF, AXES, max_attempts=2)
    assert stage["status"] == "success" and stage["attempts"] == 2
    assert not graph["entities"]
    assert graph["world_contract"]["world_premises"] == valid
    assert len(backend.schema_calls) == 2
    repaired_prompt = backend.schema_calls[1]["prompt"]
    assert '"symbol"' in repaired_prompt and "REPAIR INSTRUCTIONS" in repaired_prompt
    repair_errors = json.loads(repaired_prompt.split("Fix EVERY violation below.\n", 1)[1]
                               .split("\nPREVIOUS OUTPUT:", 1)[0])
    assert [error["message"] for error in repair_errors] == stage["errors"][0]["errors"]
    assert all(error["path"] == '$["technology"]["units"][0]["symbol"]'
               and error["actual"] == description for error in repair_errors)
    assert any("pattern" in error["expected"] for error in repair_errors)
    prompt = backend.schema_calls[0]["prompt"]
    assert "immediately after a number" in prompt
    assert "In quantity, describe what the unit measures" in prompt


def test_number_enum_contains_only_symbols_and_rejects_descriptions():
    contract = contract_with_units(
        {"symbol": "qx", "quantity": "uv"}, {"symbol": "槽", "quantity": "Container volume"})
    schema = step_schema("fact", kind="number", contract=contract)
    assert schema["properties"]["unit"] == {"enum": ["qx", "槽"]}
    validator = Draft202012Validator(schema)
    for symbol in unit_symbols(contract):
        assert validator.is_valid({"subject": "Capacity", "value": 3,
                                   "unit": symbol, "fact": f"Capacity is 3{symbol}."})
    for quantity in ("uv", "Container volume"):
        errors = list(validator.iter_errors({"subject": "Capacity", "value": 3,
            "unit": quantity, "fact": f"Capacity is 3{quantity}."}))
        assert any(error.validator == "enum" and list(error.path) == ["unit"]
                   for error in errors)


def test_unit_extraction_and_registration_use_symbols_without_registering_descriptions():
    contract = contract_with_units(
        {"symbol": "qx", "quantity": "uv"}, {"symbol": "槽", "quantity": "別量"})
    rules = rules_for(load_language_rules(), "ja")
    assert units_in_text("測定値は３ｑｘ、容量は2槽。", contract, rules) == ["qx", "槽"]
    assert registered_unit("qx²/槽", contract, rules)
    assert not registered_unit("QX", contract, rules)
    assert not registered_unit("uv", contract, rules)
    assert not registered_unit("別量", contract, rules)
    assert units_in_text("測定値は3uv。", contract, rules) == ["uv"]
    assert units_in_text("測定値は3別量。", contract, rules) == []


def test_unit_descriptions_survive_persistence_and_both_renderers(tmp_path):
    contract = contract_with_units({"symbol": "qx", "quantity": "Measured container volume"})
    graph = new_graph("en")
    establish_contract(FakeLLMBackend(contract), graph, BRIEF, AXES)
    provenance = {"statement_ids": ["s1"], "derived_from": [], "reason": ""}
    root = make_entity("e1", "place", "Test world", "world", provenance=provenance)
    root.update(origin_operator="premise", world_premises=copy.deepcopy(contract))
    graph["entities"].append(root)
    store = GraphStore(tmp_path, brief=BRIEF)
    store.save(graph)
    assert world_premises(store.load())["technology"]["units"] == contract["technology"]["units"]
    (tmp_path / "input").mkdir()
    (tmp_path / "input/input_brief.json").write_text(json.dumps(BRIEF), encoding="utf-8")
    paths = render_world_package(tmp_path)
    for path in (paths["report"], tmp_path / "final/world_bible/entities/e1.md"):
        assert "qx (Measured container volume)" in path.read_text(encoding="utf-8")
    final = json.loads(paths["world_json"].read_text(encoding="utf-8"))
    assert final["world_contract"]["world_premises"] == contract
