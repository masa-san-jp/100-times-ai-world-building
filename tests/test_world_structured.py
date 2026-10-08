"""Issue #57 output contracts; all generation is synthetic and offline."""

import ast
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from loguru import logger

from src.llm.fake import FakeLLMBackend
from src.world.axes import load_catalog
from src.world.explore import ExplorationLoop, read_preference_log, run_world_engine
from src.world.graph import new_graph
from src.world.input import InputBriefBuilder
from src.world.schemas import step_schema, load_schema, world_axes_schema
from src.world.structured import StructuredFailure, generate_structured
from tests.test_world_explore import AXES, BRIEF, RAW, cfg, make_backend

SCHEMA = load_schema("image_description")


def test_every_task_calls_only_structured_harness():
    root = Path(__file__).resolve().parents[1]
    for name in ("input", "axes", "contract", "builder"):
        tree = ast.parse((root / f"src/world/{name}.py").read_text())
        assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == "generate_structured" for n in ast.walk(tree))
    for path in (root / "src").rglob("*.py"):
        tree = ast.parse(path.read_text())
        assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                       and n.func.attr == "generate_json" for n in ast.walk(tree)), path


@pytest.mark.parametrize("schema", [
    *(load_schema(name) for name in ("input_brief", "image_description", "world_contract")),
    world_axes_schema(load_catalog()),
    *(step_schema(step, types=["place"], statement_ids=["s1"], entity_ids=["e1"],
                  axis_ids=["a1"], fact_count=3) for step in
      ("type", "grounding", "name", "axes", "summary", "fact", "relations", "review", "real_world_check"))])
def test_all_assembled_schemas_are_valid_and_every_object_is_closed(schema):
    Draft202012Validator.check_schema(schema)
    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for item in node:
                check(item)
    check(schema)




def test_every_violation_is_enumerated_and_repaired_from_original_prompt():
    backend = FakeLLMBackend([{"description": 1, "extra": 2}, {}, {}, {"description": "visible"}])
    result = generate_structured(backend, "original", SCHEMA, task="image_description", max_attempts=3)
    assert result.data == {"description": "visible"} and result.attempts == 2
    assert len(result.violations[0]) == 4 and result.violations[1] == []
    repair = backend.json_prompts[3]
    assert repair.startswith(backend.json_prompts[0])
    for violation in result.violations[0]:
        assert all(key in violation for key in ("path", "expected", "actual"))
        assert violation["message"] in repair
    assert "PREVIOUS OUTPUT" in repair and "OUTPUT SCHEMA:" in repair
    assert result.elapsed >= 0 and result.mode == "constrained"
    assert result.conversions == 2 and not result.converted
    assert result.violations[0][2]["message"] in backend.json_prompts[2]


@pytest.mark.parametrize("bad", [None, "", "not JSON", '```json\n{"description":\n```'])
def test_empty_or_unparseable_constrained_output_switches_once_and_is_remembered(bad):
    conversion_responses = [{}, {}] if bad else []
    backend = FakeLLMBackend([bad, *conversion_responses, {"description": "ok"}, {"description": "again"}])
    messages = []
    sink = logger.add(lambda message: messages.append(str(message)), level="INFO")
    try:
        result = generate_structured(backend, "p", SCHEMA, task="image_description", max_attempts=3)
        again = generate_structured(backend, "p", SCHEMA, task="image_description", max_attempts=3)
    finally:
        logger.remove(sink)
    assert result.data and again.data
    assert [c["constrained"] for c in backend.schema_calls] == [True, *([False] * (2 + len(conversion_responses)))]
    assert result.conversions == len(conversion_responses)
    assert result.mode == again.mode == "unconstrained"
    assert len([m for m in messages if "switched" in m]) == 1


@pytest.mark.parametrize("language", ["json", ""])
@pytest.mark.parametrize("surrounding_whitespace", ["", " \n\t"])
def test_fenced_compliant_output_succeeds_first_time_and_keeps_constraint(language, surrounding_whitespace):
    raw = surrounding_whitespace + f'```{language}\n{{"description": "ok"}}\n```' + surrounding_whitespace
    backend = FakeLLMBackend([raw, {"description": "again"}])
    result = generate_structured(backend, "p", SCHEMA, task="image_description", max_attempts=3)
    assert result.data == {"description": "ok"}
    assert result.attempts == 1 and result.violations == [[]]
    assert result.mode == "constrained"
    assert len(backend.schema_calls) == 1
    assert backend._structured_modes == {}
    again = generate_structured(backend, "p", SCHEMA, task="image_description", max_attempts=3)
    assert again.data == {"description": "again"} and again.attempts == 1
    assert [c["constrained"] for c in backend.schema_calls] == [True, True]


@pytest.mark.parametrize("language", ["json", ""])
@pytest.mark.parametrize("prefix,suffix", [
    ("Here is the JSON:\n", ""),
    ("", "\nThis is the result."),
    ("Here is the JSON:\n", "\nThis is the result."),
])
def test_prose_outside_code_block_remains_invalid_and_is_repaired(language, prefix, suffix):
    raw = prefix + f'```{language}\n{{"description": "ok"}}\n```' + suffix
    backend = FakeLLMBackend([raw, {}, {}, {"description": "repaired"}])
    result = generate_structured(backend, "p", SCHEMA, task="image_description", max_attempts=3)
    assert result.data == {"description": "repaired"} and result.attempts == 2
    assert result.violations[0][0]["expected"] == "valid JSON object"
    assert result.violations[0][0]["actual"] == raw
    assert result.violations[1] == []
    assert "REPAIR INSTRUCTIONS:" in backend.json_prompts[3]
    assert "PREVIOUS OUTPUT:\n" + raw in backend.json_prompts[3]
    assert [c["constrained"] for c in backend.schema_calls] == [True, False, False, False]
    assert result.conversions == 2


@pytest.mark.parametrize("language", ["json", ""])
def test_fenced_schema_violation_is_repaired_without_switching_constraint(language):
    backend = FakeLLMBackend([f"```{language}\n{{}}\n```", {}, {}, {"description": "ok"}])
    result = generate_structured(backend, "p", SCHEMA, task="image_description", max_attempts=2)
    assert result.data == {"description": "ok"} and result.attempts == 2
    assert result.violations[0][0]["expected"] == {"required": ["description"]}
    assert result.violations[1] == []
    assert [c["constrained"] for c in backend.schema_calls] == [True, True, True, True]
    assert result.conversions == 2
    assert backend._structured_modes == {}


def test_schema_violation_keeps_constraint_and_modes_are_per_client_and_model():
    backend = FakeLLMBackend([{}, {}, {}, {"description": "ok"}, "", {"description": "ok"}, {"description": "ok"}])
    generate_structured(backend, "p", SCHEMA, task="image_description", max_attempts=2)
    generate_structured(backend, "p", SCHEMA, task="image_description", max_attempts=2)
    backend.model = "other"
    generate_structured(backend, "p", SCHEMA, task="image_description", max_attempts=2)
    assert [c["constrained"] for c in backend.schema_calls] == [True, True, True, True, True, False, True]
    fresh = FakeLLMBackend({"description": "ok"})
    generate_structured(fresh, "p", SCHEMA, task="image_description", max_attempts=1)
    assert fresh.schema_calls[0]["constrained"] is True


@pytest.mark.parametrize("task", ["input_brief", "world_axes", "world_contract"])
def test_required_stage_failure_stops_engine_and_records_last_violations(tmp_path, task):
    inner = make_backend()
    def respond(prompt):
        if prompt.startswith("OUTPUT SCHEMA:\n"):
            return {}
        selected = (prompt.startswith("SOURCE MATERIAL") if task == "input_brief"
                    else "DOMAIN CATALOG" in prompt if task == "world_axes"
                    else prompt.startswith("WORLD CONTRACT"))
        return {} if selected else json.loads(inner.generate_schema(prompt, {}, constrained=True))
    backend = FakeLLMBackend(respond)
    with pytest.raises(StructuredFailure) as caught:
        run_world_engine(RAW, package_dir=tmp_path, backend=backend,
                         config=cfg(), structured_max_attempts=2)
    assert caught.value.task == task
    manifest = json.loads((tmp_path / "run_manifest.json").read_text())
    assert manifest["status"] == "failed" and task in manifest["error"]
    assert manifest["structured_failure"]["attempts"] == 2
    assert manifest["structured"][task]["failures"] == 1
    assert "Structured output" in (tmp_path / "final/world_report.md").read_text()
    assert not any("TASK: Propose" in p for p in backend.json_prompts)








def test_image_description_failure_preserves_original_and_does_not_generate_brief(tmp_path):
    backend = FakeLLMBackend({})
    with pytest.raises(StructuredFailure, match="image_description"):
        InputBriefBuilder(backend, tmp_path, max_attempts=2).build("raw", images=[b"original"])
    assert (tmp_path / "images/image_1.bin").read_bytes() == b"original"
    assert len(backend.schema_calls) == 6
    assert backend._structured_metrics["image_description"]["conversions"]["tried"] == 4


def test_successful_run_metrics_are_in_manifest_and_report(tmp_path):
    run_world_engine(RAW, package_dir=tmp_path, backend=make_backend(), config=cfg(), budget={"max_iterations": 1})
    manifest = json.loads((tmp_path / "run_manifest.json").read_text())
    for task in ("input_brief", "world_axes", "world_contract", "type", "grounding", "name", "axes", "summary", "fact", "real_world_check", "review"):
        entry = manifest["structured"][task]
        assert entry["calls"] >= 1 and entry["attempts"]["1"] >= 1
        assert entry["failures"] == 0 and entry["elapsed"] >= 0
        assert entry["modes"]["constrained"] >= 1
        assert task in (tmp_path / "final/world_report.md").read_text()


@pytest.mark.parametrize("task", ["input_brief", "world_axes", "world_contract"])
def test_structured_stage_failure_returns_nonzero_from_cli(tmp_path, monkeypatch, task):
    import example_run
    inner = make_backend()
    def respond(prompt):
        if prompt.startswith("OUTPUT SCHEMA:\n"):
            return {}
        selected = (prompt.startswith("SOURCE MATERIAL") if task == "input_brief"
                    else "DOMAIN CATALOG" in prompt if task == "world_axes"
                    else prompt.startswith("WORLD CONTRACT"))
        return {} if selected else json.loads(inner.generate_schema(prompt, {}, constrained=True))
    source = tmp_path / "source.txt"
    source.write_text(RAW)
    monkeypatch.setattr(example_run, "setup_logging", lambda **kwargs: None)
    result = example_run.main(["--context-file", str(source), "--yes",
        "--config", str(Path(__file__).resolve().parents[1] / "config/ollama_config.yaml"),
        "--output-dir", str(tmp_path / "output"), "--max-iterations", "1"],
        backend=FakeLLMBackend(respond))
    assert result != 0
    manifest_path, = (tmp_path / "output").glob("world_*/run_manifest.json")
    manifest = json.loads(manifest_path.read_text())
    assert manifest["status"] == "failed" and task in manifest["error"]


def test_metrics_include_repair_failure_modes_and_resume_cumulative_counts(tmp_path):
    backend = FakeLLMBackend(["", {"description": "ok"}, *([{}] * 6)])
    success = generate_structured(backend, "p", SCHEMA, task="image_description", max_attempts=2)
    failure = generate_structured(backend, "p", SCHEMA, task="image_description", max_attempts=2)
    entry = backend._structured_metrics["image_description"]
    assert success.attempts == failure.attempts == 2
    assert entry["calls"] == 2 and entry["failures"] == 1 and entry["attempts"] == {"2": 1}
    assert entry["modes"] == {"constrained": 1, "unconstrained": 7}
    assert entry["conversions"] == {"tried": 4, "succeeded": 0, "fidelity_failures": 0, "schema_failures": 4}
    run_world_engine(RAW, package_dir=tmp_path, backend=make_backend(), config=cfg(), budget={"max_iterations": 1})
    original = json.loads((tmp_path / "run_manifest.json").read_text())["structured"]
    run_world_engine(RAW, package_dir=tmp_path, backend=make_backend(), config=cfg(), budget={"max_iterations": 2})
    resumed = json.loads((tmp_path / "run_manifest.json").read_text())["structured"]
    assert resumed["input_brief"] == original["input_brief"]
    assert resumed["world_axes"] == original["world_axes"]
    assert resumed["world_contract"] == original["world_contract"]
    assert resumed["fact"]["calls"] > original["fact"]["calls"]
