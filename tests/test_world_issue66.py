"""Issue #66: content validation and short contract notation, offline only."""

import copy
import json
from itertools import combinations

import pytest
from jsonschema import Draft202012Validator

from src.llm.fake import FakeLLMBackend
from tests.helpers_world import contract_backend, configure_contract, contract_item
from src.world.contract import establish_contract
from src.world.explore import run_world_engine
from src.world.graph import GraphStore, make_entity, new_graph
from src.world.premises import normalize_premises, premise_errors, world_premises
from src.world.render import render_world_package
from src.world.schemas import load_schema, step_schema
from src.world.structured import generate_structured, metrics_markdown
from tests.test_world_builder import backend_with, build
from tests.test_world_conversion import object_schema
from tests.test_world_explore import AXES, BRIEF, RAW, SYNTHETIC_PREMISES, cfg, make_backend


@pytest.mark.parametrize("value", [
    "string", "number", "integer", "boolean", "object", "array", "null",
    "description", "...", "…", " \tＳＴＲＩＮＧ\n", " ＤＥＳＣＲＩＰＴＩＯＮ ",
])
def test_placeholder_values_skip_conversion_and_rewrite(value):
    schema = load_schema("image_description")
    good = {"description": "A visible surface with fine lines"}
    backend = FakeLLMBackend([{"description": value}, good])
    result = generate_structured(backend, "Describe input", schema,
                                 task="image_description", max_attempts=2)
    assert result.data == good and result.attempts == 2
    assert result.conversions == 0 and not result.converted
    violation, = result.violations[0]
    assert violation["path"] == '$["description"]' and violation["actual"] == value
    assert "Placeholder" in violation["message"]
    assert len(backend.schema_calls) == 2
    assert "REPAIR INSTRUCTIONS" in backend.json_prompts[1]
    assert violation["message"] in backend.json_prompts[1]
    assert backend._structured_metrics["image_description"]["placeholder_violations"] == 1
    assert backend._structured_metrics["image_description"]["schema_echo"] == 0


def test_all_nested_property_names_are_placeholders_but_enums_are_exempt():
    schema = object_schema({
        "records": {"type": "array", "items": object_schema({
            "caption": {"type": "string"},
            "terms": {"type": "array", "items": {"type": "string"}},
            "choice": {"enum": ["string"]},
            "choices": {"type": "array", "items": {"enum": ["caption", "…"]}},
        })},
        "value": {"type": "string"},
    })
    bad = {"records": [{"caption": "records", "terms": [" ＶＡＬＵＥ ", "null"],
                         "choice": "string", "choices": ["caption", "…"]}], "value": "terms"}
    good = copy.deepcopy(bad)
    good["records"][0].update(caption="Visible surface", terms=["Measured edge", "Fine lines"])
    good["value"] = "A complete record"
    backend = FakeLLMBackend([bad, good])
    result = generate_structured(backend, "Generate records", schema, task="nested", max_attempts=2)
    assert result.data == good and result.conversions == 0
    assert {v["path"] for v in result.violations[0]} == {
        '$["records"][0]["caption"]', '$["records"][0]["terms"][0]',
        '$["records"][0]["terms"][1]', '$["value"]'}
    assert backend._structured_metrics["nested"]["placeholder_violations"] == 4


@pytest.mark.parametrize("value", ["string theory", "description of surface", "....", "two words"])
def test_only_exact_placeholder_matches_are_rejected(value):
    data = {"description": value}
    backend = FakeLLMBackend(data)
    result = generate_structured(backend, "Describe input", load_schema("image_description"),
                                 task="image_description", max_attempts=1)
    assert result.data == data and result.violations == [[]]


def test_conversion_preserves_enum_values_that_match_placeholders():
    schema = object_schema({"choice": {"enum": ["string"]},
                            "choices": {"type": "array", "items": {"enum": ["description", "…"]}},
                            "description": {"type": "string"}})
    data = {"choice": "string", "choices": ["description", "…"], "description": "Visible surface"}
    backend = FakeLLMBackend(["Visible surface", data])
    result = generate_structured(backend, "Describe input", schema, task="synthetic", max_attempts=1)
    assert result.data == data and result.converted and result.conversions == 1
    assert backend._structured_metrics["synthetic"]["placeholder_violations"] == 0


def test_placeholder_contract_rewrites_without_conversion():
    def respond(prompt):
        good = contract_item(SYNTHETIC_PREMISES, prompt)
        bad = {key: "string" for key in good}
        item = prompt.split("ITEM: ", 1)[1].split("\n", 1)[0]
        assert Draft202012Validator(load_schema("contract/" + item)).is_valid(bad)
        return bad if "PREVIOUS OUTPUT" not in prompt else good
    backend = contract_backend(respond)
    graph = new_graph("en")
    stage = establish_contract(backend, graph, BRIEF, AXES, max_attempts=2)
    assert stage["status"] == "success" and stage["attempts"] == 32
    assert graph["world_contract"]["world_premises"] == SYNTHETIC_PREMISES
    assert len(backend.schema_calls) == 45
    for item in stage["metrics"]["steps"]:
        entry = backend._structured_metrics["contract/" + item]
        assert entry["placeholder_violations"] >= 1
        assert entry["conversions"]["tried"] == 0
    assert sum(e["placeholder_violations"] for k,e in backend._structured_metrics.items()
               if k.startswith("contract/")) == 22


def test_placeholder_candidate_name_rewrites_and_entity_is_built():
    def change(step, slot, attempt, prompt, good):
        return {"name": "string"} if step == "name" and attempt == 1 else good

    backend = backend_with(change)
    _, result = build(backend, contract=SYNTHETIC_PREMISES)
    assert result.entity and result.failure is None
    assert result.entity["name"] != "string"
    assert backend.attempts[("name", None)] == 2
    assert not any(p.startswith("OUTPUT SCHEMA:\n") for p in backend.json_prompts)
    assert backend._structured_metrics["name"]["placeholder_violations"] == 1
    assert backend._structured_metrics["name"]["conversions"]["tried"] == 0


SCHEMA_KEYS = ("$schema", "properties", "required", "additionalProperties", "type")


@pytest.mark.parametrize("keys", list(combinations(SCHEMA_KEYS, 2)))
def test_two_schema_keywords_are_rejected_before_schema_validation(keys):
    bad = {key: {} for key in keys}
    good = {"description": "Visible surface"}
    backend = FakeLLMBackend([bad, good])
    result = generate_structured(backend, "Describe input", load_schema("image_description"),
                                 task="image_description", max_attempts=2)
    assert result.data == good and result.attempts == 2 and result.conversions == 0
    violation, = result.violations[0]
    assert violation["path"] == "$" and "Schema echo" in violation["message"]
    assert len(backend.schema_calls) == 2 and "REPAIR INSTRUCTIONS" in backend.json_prompts[1]
    assert backend._structured_metrics["image_description"]["schema_echo"] == 1


@pytest.mark.parametrize("fenced", [False, True])
def test_entire_schema_echo_rewrites_contract(fenced):
    def respond(prompt):
        if "ITEM: calendar_name\n" in prompt and "PREVIOUS OUTPUT" not in prompt:
            echo = load_schema("contract/calendar_name")
            return "```json\n" + json.dumps(echo) + "\n```" if fenced else echo
        return contract_item(SYNTHETIC_PREMISES, prompt)
    backend = contract_backend(respond)
    graph = new_graph("en")
    stage = establish_contract(backend, graph, BRIEF, AXES, max_attempts=2)
    assert stage["status"] == "success" and stage["attempts"] == 17
    assert graph["world_contract"]["world_premises"] == SYNTHETIC_PREMISES
    assert backend._structured_metrics["contract/calendar_name"]["schema_echo"] == 1
    assert backend._structured_metrics["contract/calendar_name"]["conversions"]["tried"] == 0


@pytest.mark.parametrize("data", [{"type": "record"}, {"nested": {"type": "record", "properties": {}}}])
def test_schema_echo_threshold_applies_only_to_top_level(data):
    backend = FakeLLMBackend(data)
    result = generate_structured(backend, "Generate data", {"type": "object"},
                                 task="synthetic", max_attempts=1)
    assert result.data == data and result.violations == [[]]
    assert backend._structured_metrics["synthetic"]["schema_echo"] == 0


@pytest.mark.parametrize("converted,counter", [
    ({"description": "string"}, "placeholder_violations"),
    (load_schema("image_description"), "schema_echo"),
])
def test_conversion_content_violation_fails_and_rewrites(converted, counter):
    # The source contains "string", so the existing fidelity check alone passes it.
    good = {"description": "Substantive rewritten content"}
    backend = FakeLLMBackend(["description: string", converted, good])
    result = generate_structured(backend, "Describe input", load_schema("image_description"),
                                 task="image_description", max_attempts=2, max_conversions=2)
    assert result.data == good and result.attempts == 2
    assert not result.converted and result.conversions == 1
    assert len(backend.schema_calls) == 3
    assert "SOURCE OUTPUT:\ndescription: string" in backend.json_prompts[1]
    assert "REPAIR INSTRUCTIONS" in backend.json_prompts[2]
    assert backend._structured_metrics["image_description"][counter] == 1
    assert backend._structured_metrics["image_description"]["conversions"]["succeeded"] == 0


def test_failed_placeholder_conversion_is_not_accepted_at_attempt_limit():
    backend = FakeLLMBackend(["description: string", {"description": "string"}])
    result = generate_structured(backend, "Describe input", load_schema("image_description"),
                                 task="image_description", max_attempts=1)
    assert result.data is None and not result.converted and result.conversions == 1
    assert any("Placeholder" in v["message"] for v in result.violations[0])


NOTATIONS = (("calendar_name", 20), ("calendar_marker", 12), ("institution_name", 30))


def contract_with_notation(field, value):
    contract = copy.deepcopy(SYNTHETIC_PREMISES)
    contract["society"]["institutions"] = [{"name": "QuotaBoard", "description": "Records shared allocations"}]
    if field == "calendar_name":
        contract["calendar"]["name"] = value
    elif field == "calendar_marker":
        contract["calendar"]["markers"] = [value]
    else:
        contract["society"]["institutions"][0]["name"] = value
    return contract


@pytest.mark.parametrize("field,limit", NOTATIONS)
@pytest.mark.parametrize("value", ["", 3, None, "a b", "a\tb", "a\nb", "a\u3000b",
                                     "a(b", "a)b", "a（b", "a）b", "a:b", "a：b",
                                     "a,b", "a、b", "a;b", "a；b", "a。b"])
def test_contract_schema_rejects_invalid_short_notations(field, limit, value):
    validator = Draft202012Validator(load_schema("world_contract"))
    assert not validator.is_valid(contract_with_notation(field, value))


@pytest.mark.parametrize("field,limit", NOTATIONS)
def test_contract_schema_notation_length_boundaries(field, limit):
    validator = Draft202012Validator(load_schema("world_contract"))
    for value in ("x", "x" * limit):
        assert validator.is_valid(contract_with_notation(field, value))
    assert not validator.is_valid(contract_with_notation(field, "x" * (limit + 1)))


@pytest.mark.parametrize("institution", [
    "QuotaBoard", {}, {"name": "QuotaBoard"}, {"description": "Records allocations"},
    {"name": "QuotaBoard", "description": "Records allocations", "extra": "unexpected"},
    *({"name": "QuotaBoard", "description": value} for value in ("", "x" * 81, 3, None)),
])
def test_contract_rejects_malformed_institution_definitions(institution):
    contract = contract_with_notation("institution_name", "QuotaBoard")
    contract["society"]["institutions"] = [institution]
    assert not Draft202012Validator(load_schema("world_contract")).is_valid(contract)
    if isinstance(institution, dict):
        assert premise_errors(contract)


@pytest.mark.parametrize("description", ["x", "x" * 80, "Records allocations: shared, rotating (limited)。"])
def test_institution_explanations_remain_in_description(description):
    contract = contract_with_notation("institution_name", "QuotaBoard")
    contract["society"]["institutions"][0]["description"] = description
    assert Draft202012Validator(load_schema("world_contract")).is_valid(contract)
    assert normalize_premises(contract) == contract


def test_legacy_bare_institution_names_remain_readable():
    contract = copy.deepcopy(SYNTHETIC_PREMISES)
    contract["society"]["institutions"] = ["Existing institution"]
    assert normalize_premises(contract) == contract


@pytest.mark.parametrize("field,limit", NOTATIONS)
def test_explanatory_notations_are_repaired_as_schema_violations(field, limit, tmp_path, monkeypatch):
    bad = contract_with_notation(field, "短名：説明。")
    good = contract_with_notation(field, "短名")
    configure_contract(monkeypatch, tmp_path, good)
    item = {"calendar_name": "calendar_name", "calendar_marker": "calendar_marker",
            "institution_name": "institution"}[field]
    calls = 0
    last = [""]
    def respond(prompt):
        nonlocal calls
        if f"ITEM: {item}\n" in prompt:
            last[0] = prompt
        if f"ITEM: {item}\n" in prompt or "SOURCE OUTPUT:" in prompt:
            calls += 1
            return contract_item(bad if calls <= 3 else good, last[0])
        return contract_item(good, prompt)
    backend = contract_backend(respond)
    graph = new_graph("en")
    stage = establish_contract(backend, graph, BRIEF, AXES, max_attempts=2)
    assert stage["status"] == "success" and stage["attempts"] == len(stage["steps"]) + 1
    assert graph["world_contract"]["world_premises"] == good
    selected = [c for c in backend.schema_calls if f"ITEM: {item}\n" in c["prompt"]
                or "SOURCE OUTPUT:" in c["prompt"]]
    assert len(selected) == 4
    assert all("SOURCE OUTPUT:" in c["prompt"] for c in selected[1:3])
    repair = selected[3]["prompt"]
    errors = json.loads(repair.split("Fix EVERY violation below.\n", 1)[1]
                        .split("\nPREVIOUS OUTPUT:", 1)[0])
    assert all(v["actual"] == "短名：説明。" and "pattern" in v["expected"] for v in errors)
    assert [v["message"] for v in errors] == stage["errors"][0]["errors"]
    assert "short notations to write verbatim in body text" in selected[0]["prompt"]
    assert "Put explanations in description," in selected[0]["prompt"]


def test_institution_definitions_survive_persistence_rendering_and_review(tmp_path, monkeypatch):
    contract = contract_with_notation("institution_name", "QuotaBoard")
    graph = new_graph("en")
    configure_contract(monkeypatch, tmp_path, contract)
    establish_contract(contract_backend(contract), graph, BRIEF, AXES)
    root = make_entity("e1", "place", "Test world", "world",
                       provenance={"statement_ids": ["s1"], "derived_from": [], "reason": ""})
    root.update(origin_operator="premise", world_premises=copy.deepcopy(contract))
    graph["entities"].append(root)
    store = GraphStore(tmp_path, brief=BRIEF)
    store.save(graph)
    assert world_premises(store.load())["society"] == contract["society"]
    (tmp_path / "input").mkdir()
    (tmp_path / "input/input_brief.json").write_text(json.dumps(BRIEF), encoding="utf-8")
    paths = render_world_package(tmp_path)
    for file in (paths["report"], tmp_path / "final/world_bible/entities/e1.md"):
        assert "QuotaBoard (Records shared allocations)" in file.read_text(encoding="utf-8")
    final = json.loads(paths["world_json"].read_text(encoding="utf-8"))
    assert final["world_contract"]["world_premises"] == contract
    backend = make_backend()
    _, result = build(backend, g=graph, contract=world_premises(graph))
    assert result.entity
    entity_prompts = [p for p in backend.json_prompts if "WORLD CONTRACT:\n" in p]
    assert len(entity_prompts) == 9
    for prompt in entity_prompts:
        passed = json.JSONDecoder().raw_decode(prompt.split("WORLD CONTRACT:\n", 1)[1])[0]
        context = json.JSONDecoder().raw_decode(prompt.split("LOCAL CONTEXT:\n", 1)[1])[0]
        assert passed["society"] == context["world_premises"]["society"] == contract["society"]
        assert "society.institutions[].name verbatim" in prompt
    period = step_schema("fact", kind="period", contract=contract)
    assert period["properties"]["marker"]["enum"] == ["VelaCount", *contract["calendar"]["markers"]]


def test_content_metrics_accumulate_persist_and_resume_with_legacy_defaults(tmp_path):
    inner = make_backend()
    contract_calls = 0
    name_calls = 0

    def respond(prompt):
        nonlocal contract_calls, name_calls
        if "ITEM: calendar_name\n" in prompt:
            contract_calls += 1
            if contract_calls == 1:
                return load_schema("contract/calendar_name")
        if "STEP: name\n" in prompt:
            name_calls += 1
            if name_calls <= 2:
                return {"name": "string"}
        return json.loads(inner.generate_schema(prompt, {}, constrained=True))

    backend = FakeLLMBackend(respond)
    result = run_world_engine(RAW, package_dir=tmp_path, backend=backend,
                              config=cfg(), budget={"max_iterations": 1})
    assert result.counters["accepted"] == 1
    manifest = json.loads((tmp_path / "run_manifest.json").read_text())
    assert manifest["structured"]["contract/calendar_name"]["schema_echo"] == 1
    assert manifest["structured"]["name"]["placeholder_violations"] == 2
    assert manifest["structured"]["name"]["conversions"]["tried"] == 0
    report = (tmp_path / "final/world_report.md").read_text()
    assert "Placeholder violations | Schema echo" in report
    run_world_engine(RAW, package_dir=tmp_path, backend=make_backend(),
                     config=cfg(), budget={"max_iterations": 2})
    resumed = json.loads((tmp_path / "run_manifest.json").read_text())["structured"]
    assert resumed["contract/calendar_name"]["schema_echo"] == 1
    assert resumed["name"]["placeholder_violations"] == 2
    assert resumed["name"]["calls"] > manifest["structured"]["name"]["calls"]

    legacy = {"calls": 1, "attempts": {"1": 1}, "failures": 0, "elapsed": 1.0,
              "modes": {"constrained": 1}}
    assert "Placeholder violations | Schema echo" in metrics_markdown({"image_description": legacy})
    backend = FakeLLMBackend([{"description": "string"}, {"description": "Visible surface"}])
    backend._structured_metrics = {"image_description": legacy}
    generate_structured(backend, "Describe input", load_schema("image_description"),
                        task="image_description", max_attempts=2)
    assert legacy["calls"] == 2 and legacy["attempts"] == {"1": 1, "2": 1}
    assert legacy["placeholder_violations"] == 1 and legacy["schema_echo"] == 0
