"""Tests for the world-package quality report (synthetic packages)."""

import json

import pytest

from src.quality import (
    analyze_duplicates, create_quality_reports, generate_quality_report,
    main, render_markdown,
)
from tests.helpers_world import GOOD, deep_entities, entity, write_package


def test_healthy_deep_world_passes(tmp_path):
    root = write_package(tmp_path / "w", deep_entities())
    report = generate_quality_report(root)
    checks = report["checks"]
    assert report["status"] == "pass", {
        k: v["status"] for k, v in checks.items()}
    assert checks["scale_depth"]["deepest_scale"] == "detail"
    assert checks["axis_coverage"]["uncovered_axes"] == []
    assert checks["reward_distribution"]["reward"]["mean"] == 0.85


def test_uncovered_axis_and_shallow_world_warn(tmp_path):
    ents = [entity("e1", "world", "Root", axes=("a1",)),
            entity("e2", "region", "Part", parent="e1", axes=("a1",))]
    report = generate_quality_report(write_package(tmp_path / "w", ents))
    assert report["checks"]["axis_coverage"]["uncovered_axes"] == ["a2"]
    assert report["checks"]["axis_coverage"]["status"] == "warn"
    scale = report["checks"]["scale_depth"]
    assert scale["status"] == "warn"
    assert scale["deepest_scale"] == "region"
    assert "detail" in scale["missing_scales"]


def test_low_reward_and_generic_entities_are_flagged(tmp_path):
    bad = dict(GOOD, genericity=0.1, reward=0.2)
    ents = deep_entities()[:3] + [
        entity("e7", "detail", "Bland thing", "e5", scores=bad)]
    ents[3]["parent"] = "e3"
    ents[3]["scale"] = "district"
    report = generate_quality_report(
        write_package(tmp_path / "w", ents),
        config={"max_low_reward_share": 0.1, "max_generic_share": 0.1})
    rd = report["checks"]["reward_distribution"]
    assert rd["low_reward_entities"] == ["e7"]
    assert rd["status"] == "warn"
    gen = report["checks"]["genericity"]
    assert gen["generic_entities"] == ["e7"]
    assert gen["status"] == "warn"


def test_unscored_ungrounded_and_duplicate_entities_warn(tmp_path):
    empty_prov = {"statement_ids": [], "derived_from": [], "reason": ""}
    ents = deep_entities()
    ents[1]["scores"] = {}
    ents[2]["provenance"] = empty_prov
    ents.append(entity("e7", "detail", ents[5]["name"], "e5",
                       summary=ents[5]["summary"], facts=ents[5]["facts"]))
    report = generate_quality_report(write_package(tmp_path / "w", ents))
    c = report["checks"]
    assert c["reward_distribution"]["unscored_entities"] == ["e2"]
    assert c["provenance"]["ungrounded_entities"] == ["e3"]
    assert c["duplicates"]["status"] == "warn"


def test_candidates_rejected_as_generic_are_counted(tmp_path):
    prefs = [
        {"type": "candidate", "decision": "rejected",
         "result": {"failed": ["genericity"]}},
        {"type": "candidate", "decision": "accepted",
         "result": {"failed": []}},
        {"type": "iteration", "outcome": "accepted"},
        {"type": "iteration", "outcome": "discarded"}]
    report = generate_quality_report(
        write_package(tmp_path / "w", deep_entities(), prefs=prefs))
    assert report["checks"]["genericity"]["candidates_rejected_as_generic"] == 1
    ex = report["checks"]["exploration"]
    assert (ex["logged_iterations"], ex["accepted_iterations"]) == (2, 1)
    assert ex["stop_reason"] == "max_iterations"


def test_failed_run_and_invalid_graph_fail(tmp_path):
    ents = deep_entities()
    ents[3]["parent"] = "missing"
    root = write_package(tmp_path / "w", ents, manifest={
        "status": "failed", "error": "boom"})
    report = generate_quality_report(root)
    assert report["checks"]["graph"]["status"] == "fail"
    assert report["checks"]["exploration"]["status"] == "fail"
    assert report["status"] == "fail"


def test_empty_world_fails(tmp_path):
    report = generate_quality_report(write_package(tmp_path / "w", []))
    assert report["status"] == "fail"


def test_not_a_world_package_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="Not a world package"):
        generate_quality_report(tmp_path)
    with pytest.raises(ValueError, match="does not exist"):
        generate_quality_report(tmp_path / "nope")


def test_invalid_threshold_is_rejected(tmp_path):
    root = write_package(tmp_path / "w", deep_entities())
    with pytest.raises(ValueError):
        generate_quality_report(root, config={"near_duplicate_threshold": 2})
    with pytest.raises(ValueError):
        generate_quality_report(root, config={"min_depth_scale": "galaxy"})


def test_reports_are_written_and_cli_works(tmp_path, capsys):
    root = write_package(tmp_path / "w", deep_entities())
    report, jp, mp = create_quality_reports(root)
    assert json.loads(jp.read_text("utf-8"))["status"] == report["status"]
    text = mp.read_text("utf-8")
    assert text == render_markdown(report)
    for heading in ("Axis coverage", "Scale depth", "Reward distribution",
                    "Genericity", "Provenance", "Exploration"):
        assert heading in text
    assert main([str(root), "--strict"]) == 0
    assert "Quality: PASS" in capsys.readouterr().out
    bad = write_package(tmp_path / "bad", [])
    assert main([str(bad), "--strict"]) == 1


def test_analyze_duplicates_counts():
    m = analyze_duplicates(["alpha beta gamma", "alpha beta gamma",
                            "completely different words"])
    assert m["exact_duplicate_count"] == 1
    assert m["item_count"] == 3
