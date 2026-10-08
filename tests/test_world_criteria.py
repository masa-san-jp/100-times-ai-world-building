"""Issue 71: synthetic graphs and fake backends only."""

import copy
import json

import pytest

from src.run_manifest import RunManifest
from src.world.explore import (
    ExplorationLoop, candidate_pairs, evaluate_frontier, load_explore_config,
    pair_prior, read_preference_log,
)
from src.world.graph import SCALES, dumps, make_entity, new_graph
from src.world.render import render_world_package
from src.world.world_criteria import (
    axis_requirements, load_world_criteria_config, scale_chain, world_status,
)
from tests.test_world_explore import make_backend


BRIEF = {"statements": [{"id": "s1", "text": "alpha"},
                         {"id": "s2", "text": "beta"}]}
AXES = [{"id": "a1", "name": "One", "weight": 0.6},
        {"id": "a2", "name": "Two", "weight": 0.3},
        {"id": "a3", "name": "Three", "weight": 0.1}]
PROV = {"statement_ids": ["s1"], "derived_from": [], "reason": ""}


def graph_with_chain():
    graph = new_graph("en")
    graph["entities"] = [make_entity(
        f"e{i + 1}", "place", f"Entity {i + 1}", scale,
        parent=f"e{i}" if i else None, axes=["a1", "a2", "a3"],
        provenance=copy.deepcopy(PROV),
    ) for i, scale in enumerate(SCALES)]
    return graph


def complete_graph():
    graph = graph_with_chain()
    graph["entities"][0]["provenance"]["statement_ids"].append("s2")
    graph["entities"][1]["origin_operator"] = "perspective"
    graph["entities"][2]["origin_operator"] = "history"
    graph["entities"][2]["relations"] = [{"type": "affects", "target": "e2"}]
    return graph


def status(graph, axes=AXES, brief=BRIEF, contract=None):
    return world_status(graph, axes, brief, contract, load_world_criteria_config())


def world_pairs(graph):
    cfg = load_explore_config()
    return [(item, operator) for item, operator in candidate_pairs(
        evaluate_frontier(graph, AXES, cfg), cfg) if item["kind"] == "world_gap"]


def test_faithful_counts_union_of_entity_and_contract_origins_only():
    graph = graph_with_chain()
    graph["entities"][1]["facts"] = [{"provenance": {"statement_ids": ["s2"]}}]
    assert status(graph)["criteria"]["faithful"] == {
        "value": 0.5, "threshold": 1.0, "met": False}
    contract = {"provenance": {"statement_ids": ["s2", "s2", "unknown"]}}
    assert status(graph, contract=contract)["criteria"]["faithful"] == {
        "value": 1.0, "threshold": 1.0, "met": True}
    assert status(new_graph("en"), contract=contract)["criteria"]["faithful"]["value"] == 0.5


def test_faithful_resolves_existing_contract_source_interface():
    graph = graph_with_chain()
    graph["world_contract"] = {"id": "world_contract", "scale": "world",
                               "provenance": {"statement_ids": ["s2"]}}
    contract = {"source_entity": "world_contract"}
    assert status(graph, contract=contract)["criteria"]["faithful"]["met"]
    assert status(graph)["criteria"]["faithful"]["met"]


def test_breadth_uses_raw_weight_ceiling_and_minimum_one():
    cfg = load_world_criteria_config()
    axes = [{"id": "zero", "weight": 0}, {"id": "tiny", "weight": 0.01},
            {"id": "boundary", "weight": 1 / 3},
            {"id": "above", "weight": 0.34}, {"id": "full", "weight": 1}]
    assert axis_requirements(axes, cfg) == {
        "zero": 1, "tiny": 1, "boundary": 1, "above": 2, "full": 3}
    graph = graph_with_chain()
    for entity in graph["entities"]:
        entity["axes"] = []
    graph["entities"][0]["axes"] = ["a1", "a1", "a2"]
    row = status(graph)["criteria"]["breadth.axes"]
    assert row == {"value": 1 / 3, "threshold": 1.0, "met": False}
    graph["entities"][1]["axes"] = ["a1", "a3"]
    assert status(graph)["criteria"]["breadth.axes"]["met"]


def test_operation_counts_require_actual_origin_not_relation_fallbacks():
    graph = graph_with_chain()
    graph["entities"][1]["relations"] = [{"type": "related_to", "target": "e3"}]
    graph["entities"][2]["relations"] = [{"type": "affects", "target": "e2"}]
    rows = status(graph)["criteria"]
    assert rows["breadth.perspective"]["value"] == 0
    assert rows["depth.history"]["value"] == 0
    graph["entities"][1]["origin_operator"] = "perspective"
    graph["entities"][2]["origin_operator"] = "history"
    rows = status(graph)["criteria"]
    assert rows["breadth.perspective"] == {"value": 1, "threshold": 1, "met": True}
    assert rows["depth.history"] == {"value": 1, "threshold": 1, "met": True}


@pytest.mark.parametrize("relation", ["causes", "affects"])
def test_depth_counts_both_endpoints_excluding_world_from_denominator(relation):
    graph = graph_with_chain()
    graph["entities"][0]["relations"] = [{"type": relation, "target": "e2"}]
    assert status(graph)["criteria"]["depth.relations"] == {
        "value": 0.2, "threshold": 0.3, "met": False}
    graph["entities"][2]["relations"] = [
        {"type": relation, "target": "e2"}, {"type": relation, "target": "e2"},
        {"type": "related_to", "target": "e4"}]
    assert status(graph)["criteria"]["depth.relations"] == {
        "value": 0.4, "threshold": 0.3, "met": True}


def test_depth_exact_threshold_is_met():
    graph = graph_with_chain()
    graph["entities"] += [make_entity(f"e{i}", "object", f"Entity {i}", "detail",
        provenance=PROV) for i in range(7, 12)]
    graph["entities"][0]["relations"] = [{"type": "causes", "target": "e2"}]
    graph["entities"][2]["relations"] = [{"type": "affects", "target": "e4"}]
    assert status(graph)["criteria"]["depth.relations"] == {
        "value": 0.3, "threshold": 0.3, "met": True}


@pytest.mark.parametrize("broken_parent", [None, "e1", "e2"])
def test_scale_counts_do_not_replace_uninterrupted_parent_chain(broken_parent):
    graph = complete_graph()
    assert status(graph)["met"]
    assert scale_chain(graph) == [f"e{i}" for i in range(1, 7)]
    graph["entities"][3]["parent"] = broken_parent
    rows = status(graph)["criteria"]
    assert all(rows[f"scale.{scale}"]["met"] for scale in SCALES)
    assert rows["scale.chain"] == {"value": False, "threshold": True, "met": False}
    assert not status(graph)["met"]
    assert scale_chain(graph) == ["e1", "e2", "e3"]


def test_missing_scale_fails_and_world_contract_is_not_an_entity():
    graph = complete_graph()
    graph["entities"].pop()
    rows = status(graph)["criteria"]
    assert rows["scale.detail"] == {"value": 0, "threshold": 1, "met": False}
    graph["entities"] = []
    assert not status(graph, contract={"scale": "world"})["criteria"]["scale.world"]["met"]


def test_status_is_deterministic_and_does_not_mutate_inputs():
    graph = complete_graph()
    before = copy.deepcopy(graph)
    first = status(graph)
    graph["entities"].reverse()
    assert status(graph) == first
    graph["entities"].reverse()
    assert graph == before


def test_axis_gap_deficit_tracks_weight_based_required_entity_count():
    graph = new_graph("en")
    graph["entities"] = graph_with_chain()["entities"][:1]
    graph["entities"][0]["axes"] = ["a1"]
    gaps = {i["axis"]: i for i in evaluate_frontier(graph, AXES, load_explore_config())
            if i["kind"] == "axis_gap"}
    assert gaps["a1"]["deficit"] == 0.5
    assert gaps["a2"]["deficit"] == gaps["a3"]["deficit"] == 1.0


def test_missing_perspective_targets_entity_of_highest_axis_weight():
    graph = complete_graph()
    graph["entities"][1].pop("origin_operator")
    for entity in graph["entities"]:
        entity["axes"] = ["a2"]
    graph["entities"][4]["axes"] = ["a1"]
    pairs = [(item, op) for item, op in world_pairs(graph)
             if item["criterion"] == "breadth.perspective"]
    assert len(pairs) == 1
    item, op = pairs[0]
    assert (op, item["target"], item["deficit"]) == ("perspective", "e5", 1.0)


@pytest.mark.parametrize("multi_id,single_id", [("e10", "e2"), ("e2", "e10")])
def test_multi_axis_perspective_target_uses_max_weight_and_numeric_id_tie(multi_id, single_id):
    graph = new_graph("en")
    # Sum and average would favour different entities; maximum weights tie.
    graph["entities"] = [
        make_entity(multi_id, "place", "Multiple", "world",
                    axes=["a1", "a2", "a3"], provenance=PROV),
        make_entity(single_id, "place", "Single", "world", axes=["a1"], provenance=PROV)]
    pairs = [(item, op) for item, op in world_pairs(graph)
             if item["criterion"] == "breadth.perspective"]
    assert len(pairs) == 1
    item, op = pairs[0]
    assert (op, item["target"], item["deficit"]) == ("perspective", "e2", 1.0)
    graph["entities"].reverse()
    assert [(item, op) for item, op in world_pairs(graph)
            if item["criterion"] == "breadth.perspective"] == pairs
    # The pre-existing perspective frontier remains available.
    cfg = load_explore_config()
    assert any(op == "perspective" for item, op in candidate_pairs(
        evaluate_frontier(graph, AXES, cfg), cfg))


def test_empty_denominators_are_zero_and_unmet():
    rows = status(new_graph("en"), axes=[], brief={})["criteria"]
    for metric in ("faithful", "breadth.axes", "depth.relations"):
        assert rows[metric]["value"] == 0.0
        assert isinstance(rows[metric]["value"], float)
        assert not rows[metric]["met"]
    assert "null" not in json.dumps(rows)


def test_empty_denominators_are_unmet_even_with_zero_threshold():
    cfg = load_world_criteria_config()
    cfg["faithful"]["threshold"] = 0.0
    cfg["breadth"]["axes"] = 0.0
    cfg["depth"]["relations"] = 0.0
    rows = world_status(new_graph("en"), [], {}, None, cfg)["criteria"]
    for metric in ("faithful", "breadth.axes", "depth.relations"):
        assert rows[metric] == {"value": 0.0, "threshold": 0.0, "met": False}


def test_world_only_depth_adds_cause_with_full_deficit():
    graph = graph_with_chain()
    graph["entities"] = graph["entities"][:1]
    row = status(graph)["criteria"]["depth.relations"]
    assert row == {"value": 0.0, "threshold": 0.3, "met": False}
    pairs = [(item, op) for item, op in world_pairs(graph)
             if item["criterion"] == "depth.relations"]
    assert len(pairs) == 1
    item, op = pairs[0]
    assert (op, item["target"], item["deficit"]) == ("cause", "e1", 1.0)


@pytest.mark.parametrize("axes", [AXES, []])
def test_perspective_with_no_entity_axes_uses_zero_weight_and_numeric_id(axes):
    graph = new_graph("en")
    graph["entities"] = [make_entity(
        entity_id, "place", entity_id, "world", provenance=PROV,
    ) for entity_id in ("e10", "e2")]
    cfg = load_explore_config()
    pairs = [(item, op) for item, op in candidate_pairs(
        evaluate_frontier(graph, axes, cfg), cfg)
        if item.get("criterion") == "breadth.perspective"]
    assert len(pairs) == 1
    item, op = pairs[0]
    assert (op, item["target"], item["deficit"]) == ("perspective", "e2", 1.0)


def test_perspective_zero_weight_axes_and_no_axes_are_tied():
    graph = new_graph("en")
    graph["entities"] = [
        make_entity("e10", "place", "Entity 10", "world", axes=["a1"], provenance=PROV),
        make_entity("e2", "place", "Entity 2", "world", provenance=PROV)]
    cfg = load_explore_config()
    pairs = [(item, op) for item, op in candidate_pairs(
        evaluate_frontier(graph, [{"id": "a1", "weight": 0.0}], cfg), cfg)
        if item.get("criterion") == "breadth.perspective"]
    assert len(pairs) == 1
    assert pairs[0][0]["target"] == "e2"


def test_depth_and_history_target_highest_scale_without_either_relation():
    graph = graph_with_chain()
    graph["entities"][0]["relations"] = [{"type": "affects", "target": "e2"}]
    pairs = {item["criterion"]: (item, op) for item, op in world_pairs(graph)}
    cause, cause_op = pairs["depth.relations"]
    history, history_op = pairs["depth.history"]
    assert (cause_op, cause["target"]) == ("cause", "e3")
    assert cause["deficit"] == pytest.approx(1 - 0.2 / 0.3, abs=1e-6)
    assert (history_op, history["target"], history["deficit"]) == ("history", "e3", 1.0)


def test_scale_gap_zooms_deepest_continuous_chain_even_when_scale_counts_met():
    graph = complete_graph()
    graph["entities"][3]["parent"] = "e1"
    pairs = world_pairs(graph)
    assert len(pairs) == 1
    item, op = pairs[0]
    assert (item["criterion"], item["target"], op, item["deficit"]) == (
        "scale.chain", "e3", "zoom", 1.0)
    cfg = load_explore_config()
    assert pair_prior(item, op, cfg) > pair_prior({**item, "deficit": 0.0}, op, cfg)
    graph["entities"].reverse()
    assert world_pairs(graph) == pairs


def test_met_criteria_add_no_world_gaps_and_never_zoom_detail():
    graph = complete_graph()
    assert not world_pairs(graph)
    pairs = candidate_pairs(evaluate_frontier(graph, AXES, load_explore_config()),
                            load_explore_config())
    assert all(not (op == "zoom" and item["target_scale"] == "detail") for item, op in pairs)


def test_all_met_stops_before_generation_regardless_of_reward_or_zero_budget(tmp_path):
    backend = make_backend()
    manifest = RunManifest(tmp_path / "run_manifest.json", {"run_seed": 0})
    lp = ExplorationLoop(backend, tmp_path, BRIEF, AXES, config=load_explore_config(),
                         manifest=manifest)
    graph = complete_graph()
    for entity in graph["entities"]:
        entity["scores"]["reward"] = 0.0
    lp.store.save(graph)
    result = lp.run(max_iterations=0, max_generation_calls=0)
    assert result.stop_reason == "coverage_met"
    assert result.iterations == result.counters["generation_calls"] == 0
    assert backend.calls["n"] == 0
    assert result.coverage == status(graph)
    saved = json.loads(manifest.path.read_text())
    assert saved["world_explore"]["world_status"] == status(graph)
    assert saved["world_explore"]["stop_reason"] == "coverage_met"


def test_unmet_world_stops_on_budget_and_every_iteration_records_status(tmp_path):
    cfg = load_explore_config()
    cfg["budget"]["max_iterations"] = 3
    manifest = RunManifest(tmp_path / "run_manifest.json", {"run_seed": 0})
    lp = ExplorationLoop(make_backend(), tmp_path, BRIEF, AXES, config=cfg,
                         manifest=manifest)
    result = lp.run()
    assert result.stop_reason == "max_iterations"
    rows = [r for r in read_preference_log(result.preferences_path)
            if r["type"] == "iteration"]
    assert len(rows) == 3
    assert all(set(r["world_status"]) == {"criteria", "met"} for r in rows)
    assert all(row["value"] is not None for r in rows
               for row in r["world_status"]["criteria"].values())
    assert rows[0]["world_status"]["criteria"]["depth.relations"] == {
        "value": 0.0, "threshold": 0.3, "met": False}
    assert rows[-1]["world_status"] == status(result.graph) == result.coverage
    assert result.state["world_status"] == result.coverage
    assert json.loads(manifest.path.read_text())["world_explore"]["world_status"] == result.coverage


@pytest.mark.parametrize("language,heading", [("en", "Purpose achievement"),
                                                ("ja", "目的の達成状況")])
def test_report_exposes_all_values_provisional_thresholds_and_achievement(tmp_path, language, heading):
    graph = complete_graph()
    graph["meta"]["language"] = language
    (tmp_path / "world").mkdir()
    (tmp_path / "input").mkdir()
    (tmp_path / "world/graph.json").write_text(dumps(graph))
    (tmp_path / "world/world_axes.json").write_text(json.dumps({"axes": AXES}))
    (tmp_path / "input/input_brief.json").write_text(json.dumps(BRIEF))
    files = render_world_package(tmp_path, run_summary={"stop_reason": "coverage_met"})
    report = files["report"].read_text()
    assert heading in report
    assert "faithful /" in report and "breadth /" in report and "depth /" in report
    assert report.count("scale /") == 7
    assert "| 1.0 | 1.0 |" in report
    assert "| 0.4 | 0.3 |" in report
    assert "| True | True |" in report
    assert "world criteria met" in report if language == "en" else "世界の基準を満たした" in report
    exported = json.loads(files["world_json"].read_text())
    assert exported["run"]["coverage"] == status(graph)
