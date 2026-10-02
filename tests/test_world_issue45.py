"""Acceptance tests for long-run quality improvements in issue #45.

All inputs and outputs here are synthetic. The backend is deterministic and
never contacts a real model.
"""

from src.world.explore import (
    ExplorationLoop, candidate_pairs, evaluate_frontier, load_explore_config,
    operator_consumption, read_preference_log,
)
from src.world.graph import make_entity, new_graph
from src.world.reward import load_reward_config
from src.world.verify import (
    load_language_rules, verify_consistency, verify_novelty,
    verify_specificity,
)
from tests.test_world_explore import AXES, BRIEF, make_backend


PROV = {"statement_ids": ["s1"], "derived_from": [], "reason": ""}
RULES = load_language_rules()
REWARD = load_reward_config()


def _candidate(entity, operator="expand", target="e1"):
    return {"operator": operator, "target": target, "entity": entity}


def test_long_run_allocates_breadth_operators_with_fake_backend(tmp_path):
    cfg = load_explore_config()
    cfg["budget"]["max_iterations"] = 20
    cfg["coverage"]["enabled"] = False
    result = ExplorationLoop(
        make_backend(), tmp_path, BRIEF, AXES, seed=3, language="en",
        config=cfg,
    ).run()

    records = read_preference_log(tmp_path / "world" / "preferences.jsonl")
    operators = [r["operator"] for r in records if r.get("type") == "iteration"]
    breadth = {"expand", "perspective", "cause", "history", "document"}
    assert breadth <= set(operators)
    assert "zoom" in operators
    assert all(operator_consumption(result.graph)[op] >= 1 for op in breadth)

    # Breadth frontier items only expose their own operation to the bandit;
    # they cannot silently turn a history/document request into another zoom.
    seed_graph = new_graph("en")
    seed_graph["entities"] = [make_entity(
        "e1", "place", "Root", "world", axes=["a1"],
        summary="root", provenance=PROV,
    )]
    frontier = evaluate_frontier(seed_graph, AXES, cfg)
    pairs = candidate_pairs(frontier, cfg)
    assert all(
        op == item["operator"]
        for item, op in pairs
        if item["kind"] == "breadth_gap"
    )


def test_specificity_rejects_ungrounded_number_and_evaluation():
    bad = _candidate(make_entity(
        "e9", "institution", "Regional Ledger", "region", parent=None,
        summary="The regional economy receives a 5% contribution and is "
                "important to the surrounding area.",
        facts=[
            {"kind": "proper_noun", "text": "Regional Ledger"},
            {"kind": "number", "text": "5% contribution"},
            {"kind": "object", "text": "brass register"},
        ], provenance=PROV,
    ))
    bad_result = verify_specificity(
        bad, "en", RULES, REWARD["specificity"], reference="")
    bad_codes = {d.code for d in bad_result.deductions}
    assert {"ungrounded_measure", "unsupported_evaluation"} <= bad_codes

    good = _candidate(make_entity(
        "e10", "institution", "Rainfall Register", "region", parent=None,
        summary="The register records rainfall for the measuring station.",
        facts=[
            {"kind": "proper_noun", "text": "Rainfall Register"},
            {"kind": "number", "text": "rainfall 41 mm"},
            {"kind": "object", "text": "calibrated gauge"},
        ], provenance=PROV,
    ))
    good_result = verify_specificity(
        good, "en", RULES, REWARD["specificity"], reference="")
    assert good_result.score > 0.9
    assert not {"ungrounded_measure", "unsupported_evaluation"} & {
        d.code for d in good_result.deductions
    }


def test_consistency_rejects_broad_place_child_of_institution():
    graph = new_graph("en")
    graph["entities"] = [make_entity(
        "e1", "institution", "Water Registry", "world", summary="registry",
        provenance=PROV,
    )]
    bad = _candidate(make_entity(
        "e9", "place", "Registry District", "district", parent="e1",
        summary="A district-shaped location.",
        facts=[{"kind": "proper_noun", "text": "Registry District",
                "provenance": PROV}],
        provenance=PROV,
    ))
    result = verify_consistency(
        bad, graph, params=REWARD["consistency"])
    assert "parent_type" in {d.code for d in result.deductions}
    assert result.score < 1.0

    allowed = _candidate(make_entity(
        "e10", "place", "Registry Yard", "site", parent="e1",
        summary="The institution's physical yard.",
        facts=[{"kind": "proper_noun", "text": "Registry Yard",
                "provenance": PROV}],
        provenance=PROV,
    ))
    assert verify_consistency(
        allowed, graph, params=REWARD["consistency"]).score == 1.0


def test_novelty_detects_repeated_measurement_and_phrase():
    graph = new_graph("en")
    graph["entities"] = [make_entity(
        "e1", "institution", "Output Registry", "region",
        summary="The registry records output at the north station and "
                "keeps the signed daily sheet.",
        facts=[
            {"kind": "number", "text": "daily output 3,000 tons"},
            {"kind": "object", "text": "signed daily sheet"},
        ], provenance=PROV,
    )]
    candidate = _candidate(make_entity(
        "e9", "institution", "South Depot", "region",
        summary="The depot records output at the south station and keeps "
                "the signed daily sheet for inspection.",
        facts=[
            {"kind": "number", "text": "processed load 3,000 tons"},
            {"kind": "object", "text": "inspection seal"},
        ], provenance=PROV,
    ))
    result = verify_novelty(candidate, graph, params=REWARD["novelty"])
    codes = {d.code for d in result.deductions}
    assert {"duplicate_measure", "duplicate_phrase"} <= codes
    assert result.score < 1.0
