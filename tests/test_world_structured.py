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
from src.world.operators import OperatorRunner
from src.world.reward import RewardVerifier, load_reward_config
from src.world.schemas import candidates_schema, judge_schema, load_schema, world_axes_schema
from src.world.structured import StructuredFailure, generate_structured
from src.world.verify import LLMJudge
from tests.test_world_explore import AXES, BRIEF, RAW, cfg, make_backend
from tests.test_world_operators import _cand

SCHEMA = load_schema("image_description")


def test_every_task_calls_only_structured_harness():
    root = Path(__file__).resolve().parents[1]
    for name in ("input", "axes", "contract", "operators", "verify"):
        tree = ast.parse((root / f"src/world/{name}.py").read_text())
        assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == "generate_structured" for n in ast.walk(tree))
    for path in (root / "src").rglob("*.py"):
        tree = ast.parse(path.read_text())
        assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                       and n.func.attr == "generate_json" for n in ast.walk(tree)), path


@pytest.mark.parametrize("schema", [
    *(load_schema(name) for name in ("input_brief", "image_description", "world_contract")),
    world_axes_schema(load_catalog()), candidates_schema(3), candidates_schema(1),
    judge_schema(["specificity", "consistency"]),
    judge_schema(["consistency"], {"units": ["qx"], "capabilities": ["method"]})])
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


def test_dynamic_schema_values_and_approval_presence():
    from src.world.graph import ENTITY_TYPES, RELATION_TYPES, FACT_KINDS
    items = candidates_schema(2)["properties"]["candidates"]
    assert items["minItems"] == items["maxItems"] == 2
    props = items["items"]["properties"]
    assert props["type"]["enum"] == list(ENTITY_TYPES)
    assert props["facts"]["items"]["properties"]["kind"]["enum"] == list(FACT_KINDS)
    assert props["relations"]["items"]["properties"]["type"]["enum"] == list(RELATION_TYPES)
    assert world_axes_schema({"domains": [{"id": "x"}]})["properties"]["axes"]["items"]["properties"]["domain"]["enum"] == ["x", None]
    assert "premise_extension_approvals" not in judge_schema(["consistency"])["properties"]["consistency"]["properties"]


def test_every_violation_is_enumerated_and_repaired_from_original_prompt():
    backend = FakeLLMBackend([{"description": 1, "extra": 2}, {"description": "visible"}])
    result = generate_structured(backend, "original", SCHEMA, task="image_description", max_attempts=3)
    assert result.data == {"description": "visible"} and result.attempts == 2
    assert len(result.violations[0]) == 2 and result.violations[1] == []
    repair = backend.json_prompts[1]
    assert repair.startswith(backend.json_prompts[0])
    for violation in result.violations[0]:
        assert all(key in violation for key in ("path", "expected", "actual"))
        assert violation["message"] in repair
    assert "PREVIOUS OUTPUT" in repair and "OUTPUT SCHEMA:" in repair
    assert result.elapsed >= 0 and result.mode == "constrained"


@pytest.mark.parametrize("bad", [None, "", "not JSON", '```json\n{}\n```'])
def test_empty_or_unparseable_constrained_output_switches_once_and_is_remembered(bad):
    backend = FakeLLMBackend([bad, {"description": "ok"}, {"description": "again"}])
    messages = []
    sink = logger.add(lambda message: messages.append(str(message)), level="INFO")
    try:
        result = generate_structured(backend, "p", SCHEMA, task="image_description", max_attempts=3)
        again = generate_structured(backend, "p", SCHEMA, task="image_description", max_attempts=3)
    finally:
        logger.remove(sink)
    assert result.data and again.data
    assert [c["constrained"] for c in backend.schema_calls] == [True, False, False]
    assert result.mode == again.mode == "unconstrained"
    assert len([m for m in messages if "switched" in m]) == 1


def test_schema_violation_keeps_constraint_and_modes_are_per_client_and_model():
    backend = FakeLLMBackend([{}, {"description": "ok"}, "", {"description": "ok"}, {"description": "ok"}])
    generate_structured(backend, "p", SCHEMA, task="image_description", max_attempts=2)
    generate_structured(backend, "p", SCHEMA, task="image_description", max_attempts=2)
    backend.model = "other"
    generate_structured(backend, "p", SCHEMA, task="image_description", max_attempts=2)
    assert [c["constrained"] for c in backend.schema_calls] == [True, True, True, False, True]
    fresh = FakeLLMBackend({"description": "ok"})
    generate_structured(fresh, "p", SCHEMA, task="image_description", max_attempts=1)
    assert fresh.schema_calls[0]["constrained"] is True


@pytest.mark.parametrize("task", ["input_brief", "world_axes", "world_contract"])
def test_required_stage_failure_stops_engine_and_records_last_violations(tmp_path, task):
    inner = make_backend()
    def respond(prompt):
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


def test_operator_failure_is_discarded_with_attempts_and_violations(tmp_path):
    loop = ExplorationLoop(FakeLLMBackend({"candidates": []}), tmp_path, BRIEF, AXES,
                           config=cfg(), structured_max_attempts=2)
    result = loop.run(max_iterations=1)
    record = read_preference_log(result.preferences_path)[-1]
    assert record["outcome"] == "discarded"
    failure = record["structured_failure"][0]
    assert failure["task"] == "candidates" and failure["attempts"] == 2
    assert failure["violations"] and not result.graph["entities"]


def test_revision_failure_is_discarded_and_recorded(tmp_path):
    from types import SimpleNamespace
    from tests.test_world_explore import _generic
    backend = FakeLLMBackend([{"candidates": [_generic(0, ["s1"])]}, {}, {}])
    config = cfg(generation={"candidates": 1})
    loop = ExplorationLoop(backend, tmp_path, BRIEF, AXES, config=config,
        structured_max_attempts=2, verifier=RewardVerifier(contrasts=SimpleNamespace(get=lambda *args: [])))
    result = loop.run(max_iterations=1)
    record = read_preference_log(result.preferences_path)[-1]
    assert record["outcome"] == "discarded"
    assert record["structured_failure"][0]["task"] == "revision"
    assert record["structured_failure"][0]["attempts"] == 2


def test_judge_failure_rejects_even_with_zero_thresholds_and_records_reason():
    backend = FakeLLMBackend({})
    graph = new_graph("en")
    candidate = OperatorRunner(FakeLLMBackend({"candidates": [_cand()]})).run("premise", graph, n=1, brief=BRIEF)[0]
    config = load_reward_config(overrides={"llm_judges": ["specificity"],
        "thresholds": {"total": 0, **{k: 0 for k in ("genericity", "provenance", "specificity", "consistency", "objectivity", "novelty")}}})
    result = RewardVerifier(config, judge=LLMJudge(backend, max_attempts=2)).verify(graph, candidate, brief=BRIEF)
    assert not result.passed and "specificity" in result.failed
    assert result.premise_review["structured_failure"]["attempts"] == 2
    assert any(d.code == "structured_failure" for d in result.deductions)


def test_image_description_failure_preserves_original_and_does_not_generate_brief(tmp_path):
    backend = FakeLLMBackend({})
    with pytest.raises(StructuredFailure, match="image_description"):
        InputBriefBuilder(backend, tmp_path, max_attempts=2).build("raw", images=[b"original"])
    assert (tmp_path / "images/image_1.bin").read_bytes() == b"original"
    assert len(backend.schema_calls) == 2


def test_successful_run_metrics_are_in_manifest_and_report(tmp_path):
    run_world_engine(RAW, package_dir=tmp_path, backend=make_backend(), config=cfg(), budget={"max_iterations": 1})
    manifest = json.loads((tmp_path / "run_manifest.json").read_text())
    for task in ("input_brief", "world_axes", "world_contract", "candidates"):
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
    backend = FakeLLMBackend(["", {"description": "ok"}, {}, {}])
    success = generate_structured(backend, "p", SCHEMA, task="image_description", max_attempts=2)
    failure = generate_structured(backend, "p", SCHEMA, task="image_description", max_attempts=2)
    entry = backend._structured_metrics["image_description"]
    assert success.attempts == failure.attempts == 2
    assert entry["calls"] == 2 and entry["failures"] == 1 and entry["attempts"] == {"2": 1}
    assert entry["modes"] == {"constrained": 1, "unconstrained": 3}
    run_world_engine(RAW, package_dir=tmp_path, backend=make_backend(), config=cfg(), budget={"max_iterations": 1})
    original = json.loads((tmp_path / "run_manifest.json").read_text())["structured"]
    run_world_engine(RAW, package_dir=tmp_path, backend=make_backend(), config=cfg(), budget={"max_iterations": 2})
    resumed = json.loads((tmp_path / "run_manifest.json").read_text())["structured"]
    assert resumed["input_brief"] == original["input_brief"]
    assert resumed["world_axes"] == original["world_axes"]
    assert resumed["world_contract"] == original["world_contract"]
    assert resumed["candidates"]["calls"] > original["candidates"]["calls"]
