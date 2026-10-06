"""Issue #55: small contract stage, fallback and visible operator rejections."""

import json
import random
from types import SimpleNamespace

import pytest
from loguru import logger

from src.llm.fake import FakeLLMBackend
from src.world.contract import establish_contract
from src.world.explore import ExplorationLoop, read_preference_log, run_world_engine
from src.world.graph import GraphStore, local_context, new_graph, validate_graph
from src.world.operators import OperatorRunner
from src.world.premises import CONTRACT_ID, premise_extensions, world_premises
from src.world.render import render_world_package
from src.world.reward import RewardVerifier, load_reward_config
from src.world.verify import LLMJudge, verify_consistency
from tests.test_world_explore import (
    AXES, BRIEF, RAW, SYNTHETIC_PREMISES, _generic, _specific, cfg, make_backend,
)


def backend_without_candidate_contracts(contract_responses):
    inner = make_backend()
    responses = iter(contract_responses)

    def respond(prompt):
        if prompt.startswith("WORLD CONTRACT"):
            response = next(responses)
            if isinstance(response, Exception):
                raise response
            return response
        response = json.loads(inner.generate_schema(prompt, {}, constrained=True))
        for item in response.get("candidates", []):
            item.pop("world_premises", None)
        return response

    return FakeLLMBackend(respond)


@pytest.mark.parametrize("invalid", [{}, {"calendar": {}},
    {k: v for k, v in SYNTHETIC_PREMISES.items() if k != "society"}])
def test_contract_repairs_missing_sections_before_exploring_and_persists(tmp_path, invalid):
    backend = backend_without_candidate_contracts([invalid, SYNTHETIC_PREMISES])
    result = run_world_engine(RAW, package_dir=tmp_path, backend=backend,
                              budget={"max_iterations": 2}, config=cfg())
    assert result.counters["accepted"] >= 1
    assert result.graph["entities"]
    assert all("world_premises" not in e for e in result.graph["entities"])
    assert world_premises(result.graph)["calendar"] == SYNTHETIC_PREMISES["calendar"]
    assert world_premises(result.graph)["source_entity"] == CONTRACT_ID
    assert not validate_graph(result.graph, brief=BRIEF)
    stage = result.graph["contract_stage"]
    assert stage["status"] == "success" and stage["attempts"] == 2
    prompts = [p for p in backend.json_prompts if p.startswith("WORLD CONTRACT")]
    assert len(prompts) == 2
    assert prompts[0] in backend.json_prompts[:3]
    assert backend.json_prompts.index(prompts[1]) < next(
        i for i, p in enumerate(backend.json_prompts) if "TASK: Propose" in p)
    assert all(e in prompts[1] for e in stage["errors"][0]["errors"])
    assert "candidates\":[" not in prompts[0] and "existing entities" not in prompts[0]
    manifest = json.loads((tmp_path / "run_manifest.json").read_text())
    assert manifest["world_contract"] == stage
    final = json.loads((tmp_path / "final/world.json").read_text())
    assert final["world_contract"] == result.graph["world_contract"]
    assert final["contract_stage"] == stage
    assert "World contract generation" in (tmp_path / "final/world_report.md").read_text()

    resumed = backend_without_candidate_contracts([])
    again = run_world_engine(RAW, package_dir=tmp_path, backend=resumed,
                             budget={"max_iterations": 3}, config=cfg())
    assert again.iterations == 3
    assert not any(p.startswith("WORLD CONTRACT") for p in resumed.json_prompts)
    assert again.graph["contract_stage"] == stage


@pytest.mark.parametrize("failure", [{}, {"calendar": {}}])
def test_k_failed_contract_attempts_stop_execution_and_remain_failed_on_resume(tmp_path, failure):
    from src.world.structured import StructuredFailure
    backend = backend_without_candidate_contracts([failure] * 2)
    with pytest.raises(StructuredFailure, match="world_contract"):
        run_world_engine(RAW, package_dir=tmp_path, backend=backend,
                         budget={"max_iterations": 3}, config=cfg(), structured_max_attempts=2)
    loaded = GraphStore(tmp_path).load()
    stage = loaded["contract_stage"]
    assert stage["status"] == "failed" and stage["attempts"] == 2
    assert not loaded["entities"] and not world_premises(loaded)
    assert len([p for p in backend.json_prompts if p.startswith("WORLD CONTRACT")]) == 2
    manifest = json.loads((tmp_path / "run_manifest.json").read_text())
    assert manifest["status"] == "failed" and manifest["world_contract"] == stage
    assert "world_contract" in (tmp_path / "final/world_report.md").read_text()
    resumed = backend_without_candidate_contracts([])
    with pytest.raises(StructuredFailure, match="world_contract"):
        run_world_engine(RAW, package_dir=tmp_path, backend=resumed,
                         budget={"max_iterations": 4}, config=cfg())
    assert not resumed.json_prompts


def test_failed_contract_never_enables_exploration_fallback():
    from src.world.structured import StructuredFailure
    graph = new_graph("en")
    with pytest.raises(StructuredFailure):
        establish_contract(FakeLLMBackend({}), graph, BRIEF, AXES, max_attempts=1)
    assert graph["contract_stage"]["status"] == "failed"
    assert graph["contract_stage"]["structured_failure"]["attempts"] == 1
    assert not graph["entities"]


def test_discard_reasons_aggregate_to_info_and_iteration_log(tmp_path):
    good = _specific(random.Random(17), ["s1"], ["a1"])
    no_provenance = {**good, "statement_ids": [], "derived_from": []}
    thin = {**good, "facts": []}
    invalid_contract = {**good, "world_premises": {}}
    rows = [no_provenance, thin, good, good]
    config = cfg(generation={"candidates": 4, "max_rewrites": 0})
    backend = FakeLLMBackend({"candidates": rows})
    messages = []
    sink = logger.add(lambda message: messages.append(str(message)), level="INFO")
    try:
        result = ExplorationLoop(backend, tmp_path, BRIEF, AXES,
                                 config=config).run(max_iterations=1)
    finally:
        logger.remove(sink)
    iteration = next(r for r in read_preference_log(result.preferences_path)
                     if r["type"] == "iteration")
    assert iteration["discard_reasons"] == {"no_provenance": 1, "insufficient_facts": 1, "duplicate_name": 1}
    assert all(reason in "\n".join(messages) for reason in iteration["discard_reasons"])
    assert any("iteration 1" in m and "discard reasons" in m for m in messages)


def test_new_contract_source_supports_reviewed_extensions_and_rollback(tmp_path):
    from tests.test_world_issue48 import BRIEF as brief, graph, raw, score, batch_judge, assessment

    g = graph()
    original = g["entities"][0].pop("world_premises")
    g["world_contract"] = {"id": CONTRACT_ID, "scale": "world",
                           "world_premises": original, "provenance": g["entities"][0]["provenance"]}
    item = raw("照合所の札束の重さは2kg。", "number", premise_usage={"units": ["kg"]})
    candidate = OperatorRunner(FakeLLMBackend({"candidates": [item]})).run(
        "expand", g, "e2", 1, brief=brief)[0]
    judge = LLMJudge(batch_judge(specificity=assessment(), consistency=assessment(approve=True)))
    result = score(g, candidate, judge, ["specificity", "consistency"])
    assert result.passed and result.premise_extension["source_entity"] == CONTRACT_ID
    candidate["entity"]["premise_extension"] = result.premise_extension
    g["entities"].append(candidate["entity"])
    assert not validate_graph(g, brief=brief)
    store = GraphStore(tmp_path, brief=brief)
    store.save(g)
    loaded = store.load()
    assert "kg" in world_premises(loaded)["technology"]["units"]
    assert "kg" not in loaded["world_contract"]["world_premises"]["technology"]["units"]
    assert premise_extensions(loaded)[0]["source_entity"] == CONTRACT_ID
    assert local_context(loaded, "e2")["world_premises"]["source_entity"] == CONTRACT_ID
    final = json.loads(render_world_package(tmp_path)["world_json"].read_text())
    assert final["premise_extensions"] == premise_extensions(loaded)
    loaded["entities"].pop()
    assert "kg" not in world_premises(loaded)["technology"]["units"]
    assert not premise_extensions(loaded)


def test_legacy_graph_contract_is_reused_without_generation():
    from tests.test_world_issue48 import graph

    g = graph()
    backend = FakeLLMBackend({})
    before = world_premises(g)
    stage = establish_contract(backend, g, BRIEF, AXES)
    assert stage["status"] == "success" and stage["attempts"] == 0
    assert stage["reused"] and world_premises(g) == before
    assert not backend.json_prompts and not validate_graph(g)


@pytest.mark.parametrize("value", [0, -1, True, "3"])
def test_invalid_contract_attempt_setting_is_rejected(value):
    with pytest.raises(ValueError, match="max_attempts"):
        establish_contract(FakeLLMBackend({}), new_graph("en"), BRIEF, AXES,
                           max_attempts=value)


def test_contract_context_is_bounded_and_interrupts_propagate():
    backend = FakeLLMBackend(SYNTHETIC_PREMISES)
    brief = {"statements": [{"id": f"s{i}", "text": "x" * 500} for i in range(40)]}
    axes = [{"name": "n" * 500, "meaning": "m" * 500} for _ in range(40)]
    establish_contract(backend, new_graph("en"), brief, axes)
    prompt = backend.json_prompts[0]
    assert '"id":"s11"' in prompt and '"id":"s12"' not in prompt
    assert "x" * 160 in prompt and "x" * 161 not in prompt
    assert prompt.count('"meaning":') == 16
    assert len(prompt) < 11000

    def interrupt(_prompt):
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        establish_contract(FakeLLMBackend(interrupt), new_graph("en"), BRIEF, AXES)


def test_graph_inconsistency_and_contract_conflicts_have_distinct_reasons():
    from tests.test_world_issue48 import graph, raw

    g = graph()
    conflict = json.loads(json.dumps(g["entities"][0]["world_premises"]))
    conflict["calendar"]["origin"] = "another origin"
    runner = OperatorRunner(FakeLLMBackend({"candidates": [raw(world_premises=conflict)]}))
    assert not runner.run("premise", g, n=1)
    assert runner.last_discard_reasons == {"structured_failure": 1}
    # Pre-existing errors are ignored; an inherited invalid parent is a new error.
    g["entities"][1]["parent"] = "missing-parent"
    runner = OperatorRunner(FakeLLMBackend({"candidates": [raw()]}))
    assert not runner.run("expand", g, "e2", n=1)
    assert runner.last_discard_reasons == {"graph_inconsistent": 1}


def test_rewrite_discard_reasons_are_in_the_same_iteration(tmp_path):
    backend = FakeLLMBackend([
        {"candidates": [_generic(0, ["s1"])]},
        {"candidates": [{**_generic(1, ["s1"]), "statement_ids": []}]},
    ])
    verifier = RewardVerifier(contrasts=SimpleNamespace(get=lambda *args: []))
    result = ExplorationLoop(backend, tmp_path, BRIEF, AXES, verifier=verifier,
                             config=cfg(generation={"candidates": 1})).run(max_iterations=1)
    iteration = next(r for r in read_preference_log(result.preferences_path)
                     if r["type"] == "iteration")
    assert result.counters["rewrites"] == 1
    assert iteration["outcome"] == "discarded"
    assert iteration["discard_reasons"] == {"no_provenance": 1}
