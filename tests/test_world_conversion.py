"""Issue #64: offline format conversion and deterministic fidelity checks."""

import copy
import json

import pytest
import yaml

from src.llm.fake import FakeLLMBackend
from src.world.criteria import real_world_check
from src.world.explore import run_world_engine
from src.world.schemas import load_schema, step_schema
from src.world.structured import CONVERT_PROMPT_PATH, generate_structured, metrics_markdown
from tests.test_world_explore import RAW, cfg, make_backend


def object_schema(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


DESCRIPTION = load_schema("image_description")
MEASUREMENT = object_schema({"label": {"type": "string"}, "value": {"type": "number"}})


def convert(backend, schema=DESCRIPTION, **kwargs):
    return generate_structured(backend, "Generate content", schema, task="synthetic",
                               system_prompt="Content generation", max_attempts=kwargs.pop("max_attempts", 2),
                               **kwargs)


def test_prose_is_converted_without_content_rewrite_and_with_separate_prompt():
    raw = "説明: 明るい面と細い線"
    data = {"description": "明るい面と細い線"}
    backend = FakeLLMBackend([raw, data])
    result = convert(backend, images=[b"source"])
    assert result.data == data and result.attempts == 1
    assert result.converted is True and result.conversions == 1
    assert len(backend.schema_calls) == 2
    generation, conversion = backend.schema_calls
    assert generation["prompt"].startswith("Generate content")
    assert generation["system_prompt"] == "Content generation"
    assert generation["images"] == [b"source"]
    prompts = yaml.safe_load(CONVERT_PROMPT_PATH.read_text(encoding="utf-8"))
    assert conversion["system_prompt"] == prompts["system"]
    assert "Do not add, remove or change content" in prompts["system"]
    assert "Keep the source output's language. Do not translate" in prompts["system"]
    assert conversion["images"] is None
    assert "SOURCE OUTPUT:\n" + raw in conversion["prompt"]
    assert "Generate content" not in conversion["prompt"]
    assert "REPAIR INSTRUCTIONS" not in conversion["prompt"]
    assert conversion["schema"] == generation["schema"] == DESCRIPTION
    assert [c["constrained"] for c in backend.schema_calls] == [True, False]
    assert backend._structured_metrics["synthetic"]["conversions"] == {
        "tried": 1, "succeeded": 1, "fidelity_failures": 0, "schema_failures": 0}


@pytest.mark.parametrize("fabricated,path", [
    ({"label": "invented", "value": 42}, '$["label"]'),
    ({"label": "visible", "value": 99}, '$["value"]'),
])
def test_invented_strings_and_numbers_fail_then_content_is_rewritten(fabricated, path):
    raw = "label: visible; value: 42"
    rewritten = {"label": "new content", "value": 99}
    backend = FakeLLMBackend([raw, fabricated, fabricated, rewritten])
    result = convert(backend, MEASUREMENT)
    assert result.data == rewritten and result.attempts == 2
    assert result.converted is False and result.conversions == 2
    assert len(backend.schema_calls) == 4
    assert all("SOURCE OUTPUT:\n" + raw in p for p in backend.json_prompts[1:3])
    feedback = json.loads(backend.json_prompts[2].split("PREVIOUS CONVERSION VIOLATIONS:\n")[1])
    assert [v["path"] for v in feedback] == [path]
    assert any(v["path"] == path and v["actual"] == fabricated[path.split('"')[1]]
               for v in result.violations[0])
    assert backend.json_prompts[3].startswith(backend.json_prompts[0])
    assert "REPAIR INSTRUCTIONS" in backend.json_prompts[3]
    assert "PREVIOUS OUTPUT:\n" + raw in backend.json_prompts[3]
    assert backend._structured_metrics["synthetic"]["conversions"] == {
        "tried": 2, "succeeded": 0, "fidelity_failures": 2, "schema_failures": 0}


def test_retry_reports_schema_and_fidelity_failures_and_uses_original_source():
    raw = "description: visible"
    backend = FakeLLMBackend([raw, {"description": "invented", "extra": 9}, {"description": "visible"}])
    result = convert(backend)
    assert result.data == {"description": "visible"}
    assert result.attempts == 1 and result.converted and result.conversions == 2
    second = backend.json_prompts[2]
    assert "SOURCE OUTPUT:\n" + raw in second
    feedback = json.loads(second.split("PREVIOUS CONVERSION VIOLATIONS:\n")[1])
    assert any("additionalProperties" in v["expected"] for v in feedback)
    assert {v["path"] for v in feedback if v["expected"] == "value present in SOURCE OUTPUT"} == {
        '$["description"]', '$["extra"]'}
    assert backend._structured_metrics["synthetic"]["conversions"] == {
        "tried": 2, "succeeded": 1, "fidelity_failures": 1, "schema_failures": 1}


def test_previous_conversion_cannot_become_the_fidelity_source():
    backend = FakeLLMBackend(["description: visible", {"description": "invented"}, {"description": "invented"}])
    result = convert(backend, max_attempts=1)
    assert result.data is None and not result.converted and result.conversions == 2
    assert backend._structured_metrics["synthetic"]["conversions"]["fidelity_failures"] == 2
    assert result.violations[-1][-1]["path"] == '$["description"]'


@pytest.mark.parametrize("source,value", [
    ("value: １，２３４，５６７", 1234567),
    ("value: -１，２３４.５０", -1234.5),
    ("value: 12", 12.0),
    ("value: ０.１２５", 0.125),
])
def test_number_notation_width_and_grouping_normalization(source, value):
    data = {"label": "visible", "value": value}
    backend = FakeLLMBackend(["ＶＩＳＩＢＬＥ; " + source, data])
    result = convert(backend, MEASUREMENT, max_attempts=1)
    assert result.data == data and result.converted and result.conversions == 1


def test_nested_arrays_objects_and_string_normalization():
    schema = object_schema({"records": {"type": "array", "items": object_schema({
        "text": {"type": "string"}, "values": {"type": "array", "items": {"type": "number"}}})}})
    data = {"records": [{"text": "alpha beta", "values": [1234, 0.5]}]}
    backend = FakeLLMBackend(["ＡＬＰＨＡ\n\tＢＥＴＡ １，２３４ ０.５", data])
    result = convert(backend, schema)
    assert result.data == data and result.converted
    fabricated = copy.deepcopy(data)
    fabricated["records"][0]["values"][1] = 9
    backend = FakeLLMBackend(["alpha beta 1234 0.5", fabricated, fabricated])
    result = convert(backend, schema, max_attempts=1)
    assert result.data is None
    assert result.violations[-1][-1]["path"] == '$["records"][0]["values"][1]'


def test_string_enums_are_exempt_in_properties_and_array_items():
    schema = object_schema({"choice": {"type": "string", "enum": ["allowed"]},
                            "choices": {"type": "array", "items": {"enum": ["selected"]}},
                            "text": {"type": "string"}})
    data = {"choice": "allowed", "choices": ["selected"], "text": "visible"}
    result = convert(FakeLLMBackend(["visible", data]), schema)
    assert result.data == data and result.converted


def test_enums_still_require_schema_compliance_and_numeric_fidelity():
    schema = object_schema({"choice": {"enum": ["allowed"]}, "value": {"enum": [9]}})
    backend = FakeLLMBackend(["source", {"choice": "invalid", "value": 9}])
    result = convert(backend, schema, max_attempts=1, max_conversions=1)
    assert result.data is None and not result.converted
    assert backend._structured_metrics["synthetic"]["conversions"] == {
        "tried": 1, "succeeded": 0, "fidelity_failures": 1, "schema_failures": 1}
    assert any(v["path"] == '$["value"]' and v["expected"] == "value present in SOURCE OUTPUT"
               for v in result.violations[0])


@pytest.mark.parametrize("task,good", [
    ("real_world_check", {"items": [{"term": "Synthetic", "category": "invented", "reason": "visible"}]}),
    ("review", {"verdicts": {k: True for k in ("consistent", "objective", "no_outside_premises")}, "issues": []}),
])
def test_classification_and_boolean_tasks_bypass_conversion(task, good):
    backend = FakeLLMBackend(["ambiguous", good])
    if task == "real_world_check":
        result = real_world_check(backend, ["Synthetic"], language="en", max_attempts=2, max_conversions=2)
    else:
        result = generate_structured(backend, "Generate content", step_schema(task), task=task, max_attempts=2)
    assert result.data == good and result.attempts == 2
    assert not result.converted and result.conversions == 0
    assert len(backend.schema_calls) == 2
    assert "REPAIR INSTRUCTIONS" in backend.json_prompts[1]
    assert backend._structured_metrics[task]["conversions"] == {
        "tried": 0, "succeeded": 0, "fidelity_failures": 0, "schema_failures": 0}


def test_conversion_can_be_explicitly_disabled_for_a_nonboolean_schema():
    data = {"description": "new content"}
    backend = FakeLLMBackend(["ambiguous", data])
    result = convert(backend, allow_conversion=False)
    assert result.data == data and result.attempts == 2
    assert not result.converted and result.conversions == 0
    assert len(backend.schema_calls) == 2
    assert "REPAIR INSTRUCTIONS" in backend.json_prompts[1]


def test_boolean_property_nested_inside_array_bypasses_conversion():
    schema = object_schema({"items": {"type": "array", "items": object_schema({"flag": {"type": "boolean"}})}})
    data = {"items": [{"flag": False}]}
    backend = FakeLLMBackend(["ambiguous", data])
    result = convert(backend, schema)
    assert result.data == data and result.conversions == 0 and result.attempts == 2
    assert "REPAIR INSTRUCTIONS" in backend.json_prompts[1]


@pytest.mark.parametrize("raw", [None, "", " \n\t"])
def test_empty_source_bypasses_conversion(raw):
    backend = FakeLLMBackend([raw, {"description": "new content"}])
    result = convert(backend)
    assert result.data == {"description": "new content"} and result.attempts == 2
    assert not result.converted and result.conversions == 0
    assert len(backend.schema_calls) == 2 and "REPAIR INSTRUCTIONS" in backend.json_prompts[1]


@pytest.mark.parametrize("raw", [{"description": "visible"}, '```json\n{"description":"visible"}\n```'])
def test_compliant_generation_bypasses_conversion(raw):
    backend = FakeLLMBackend([raw])
    result = convert(backend)
    assert result.data == {"description": "visible"} and result.attempts == 1
    assert not result.converted and result.conversions == 0 and result.violations == [[]]
    assert len(backend.schema_calls) == 1


def test_conversion_uses_existing_fence_parser():
    backend = FakeLLMBackend(["description: visible", '```json\n{"description":"visible"}\n```'])
    result = convert(backend)
    assert result.data == {"description": "visible"} and result.converted


@pytest.mark.parametrize("limit", [0, 1, 3])
def test_conversion_limit_applies_to_each_generation_and_counts_accumulate(limit):
    backend = FakeLLMBackend(["description: visible", *([{}] * limit),
                              "description: second", *([{}] * limit), {"description": "rewritten"}])
    result = convert(backend, max_attempts=3, max_conversions=limit)
    assert result.data == {"description": "rewritten"} and result.attempts == 3
    assert not result.converted and result.conversions == 2 * limit
    assert len(backend.schema_calls) == 3 + 2 * limit
    assert backend._structured_metrics["synthetic"]["conversions"] == {
        "tried": 2 * limit, "succeeded": 0, "fidelity_failures": 0, "schema_failures": 2 * limit}


@pytest.mark.parametrize("invalid", [-1, True, "2", 1.5])
def test_invalid_conversion_limit_is_rejected_before_any_call(invalid):
    backend = FakeLLMBackend({"description": "visible"})
    with pytest.raises(ValueError, match="max_conversions"):
        convert(backend, max_conversions=invalid)
    assert not backend.schema_calls


@pytest.mark.parametrize("forced", [False, True])
def test_constraint_learning_from_conversion_uses_same_client_and_model_key(forced):
    backend = FakeLLMBackend([{}, "invalid JSON", {"description": "rewritten"}, {"description": "again"}, {"description": "other"}])
    backend.schema_always_constrained = forced
    result = convert(backend, max_conversions=1)
    assert result.data == {"description": "rewritten"} and not result.converted
    convert(backend)
    backend.model = "another synthetic model"
    convert(backend)
    assert [c["constrained"] for c in backend.schema_calls] == [True, True, forced, forced, True]
    assert backend._structured_modes == ({} if forced else {("fake", "fake"): False})


def test_conversion_metrics_persist_in_manifest_report_and_resume(tmp_path):
    inner = make_backend()
    converted = 0

    def respond(prompt):
        nonlocal converted
        if prompt.startswith("OUTPUT SCHEMA:\n"):
            converted += 1
            return ({"name": "invented", "extra": 9} if converted == 1 else {"name": "Visible value"})
        if "STEP: name\n" in prompt:
            return "name: Visible value"
        return json.loads(inner.generate_schema(prompt, {}, constrained=True))

    result = run_world_engine(RAW, package_dir=tmp_path, backend=FakeLLMBackend(respond),
                              config=cfg(), budget={"max_iterations": 1})
    assert result.counters["accepted"] == 1
    manifest = json.loads((tmp_path / "run_manifest.json").read_text())
    entry = manifest["structured"]["name"]
    assert entry["conversions"] == {"tried": 2, "succeeded": 1, "fidelity_failures": 1, "schema_failures": 1}
    assert entry["attempts"] == {"1": 1} and entry["failures"] == 0
    report = (tmp_path / "final/world_report.md").read_text()
    assert "Conversions tried | Conversions succeeded | Fidelity failures | Schema failures" in report
    structured_report = report.split("## Structured output\n", 1)[1].split("\n## ", 1)[0]
    row, = [line for line in structured_report.splitlines() if line.startswith("| name |")]
    assert row.endswith("| 2 | 1 | 1 | 1 |")
    assert manifest["structured"]["review"]["conversions"]["tried"] == 0
    run_world_engine(RAW, package_dir=tmp_path, backend=make_backend(), config=cfg(), budget={"max_iterations": 2})
    resumed = json.loads((tmp_path / "run_manifest.json").read_text())["structured"]["name"]
    assert resumed["conversions"] == entry["conversions"] and resumed["calls"] > entry["calls"]


def test_legacy_metrics_gain_conversion_counts_without_losing_previous_counts():
    backend = FakeLLMBackend(["description: visible", {"description": "visible"}])
    backend._structured_metrics = {"synthetic": {"calls": 4, "attempts": {"1": 3},
        "failures": 1, "elapsed": 1.0, "modes": {"constrained": 4}}}
    legacy_report = metrics_markdown(copy.deepcopy(backend._structured_metrics))
    assert "| 0 | 0 | 0 | 0 |" in legacy_report
    result = convert(backend)
    entry = backend._structured_metrics["synthetic"]
    assert result.converted and entry["calls"] == 5 and entry["attempts"] == {"1": 4}
    assert entry["failures"] == 1 and entry["elapsed"] >= 1.0
    assert entry["conversions"] == {"tried": 1, "succeeded": 1, "fidelity_failures": 0, "schema_failures": 0}
