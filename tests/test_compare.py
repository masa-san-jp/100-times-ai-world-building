"""Tests for the cross-world comparison report (synthetic packages)."""

import json

import pytest

from src.compare import (
    create_comparison_report, generate_comparison_report, main, render_markdown,
    resolve_batch_worlds,
)
from tests.helpers_world import deep_entities, write_package


def _two_worlds(tmp_path, same=False):
    a = write_package(tmp_path / "world_a", deep_entities("alpha"))
    other = deep_entities("alpha" if same else "zorblax quintessence")
    if not same:
        for i, e in enumerate(other):
            e["summary"] = f"unrelated text number {i} about quite other things"
            e["facts"][0]["text"] = f"Wholly Other Thing {i * 7}"
    b = write_package(tmp_path / "world_b", other, manifest={
        "run_id": "b", "run_seed": 2, "backend": "fake", "model": "fake",
        "status": "completed", "stop_reason": "coverage_met", "iterations": 9})
    return a, b


def test_report_summarises_each_world(tmp_path):
    a, b = _two_worlds(tmp_path)
    report = generate_comparison_report([a, b])
    w = {x["label"]: x for x in report["worlds"]}
    assert w["world_a"]["entity_count"] == 6
    assert w["world_a"]["deepest_scale"] == "detail"
    assert w["world_a"]["axes_covered"] == 2
    assert w["world_a"]["mean_reward"] == 0.85
    assert w["world_b"]["stop_reason"] == "coverage_met"
    assert w["world_b"]["quality_status"] in {"pass", "warn", "fail"}


def test_different_worlds_have_low_overlap(tmp_path):
    a, b = _two_worlds(tmp_path)
    pair = generate_comparison_report([a, b])["divergence"]["pairs"][0]
    assert pair["near_duplicate_rate"] == 0.0
    assert pair["shared_proper_noun_rate"] == 0.0
    assert not pair["warning"]


def test_identical_worlds_are_flagged_as_repeating(tmp_path):
    a, b = _two_worlds(tmp_path, same=True)
    div = generate_comparison_report([a, b])["divergence"]
    pair = div["pairs"][0]
    assert pair["same_name_rate"] == 1.0
    assert pair["near_duplicate_rate"] == 1.0
    assert pair["warning"] is True
    assert div["max_overlap"] == 1.0
    assert "REPEATS" in render_markdown(generate_comparison_report([a, b]))


def test_markdown_has_all_sections(tmp_path):
    a, b = _two_worlds(tmp_path)
    text = render_markdown(generate_comparison_report([a, b]))
    for heading in ("## Runs", "## Coverage and depth",
                    "## Scores and quality", "## Cross-world overlap",
                    "### Axis similarity"):
        assert heading in text
    path = tmp_path / "out" / "comparison.md"
    report, written = create_comparison_report([a, b], path)
    assert written.read_text("utf-8") == render_markdown(report)


def test_single_world_has_nothing_to_compare(tmp_path):
    a, _ = _two_worlds(tmp_path)
    report = generate_comparison_report([a])
    assert report["divergence"]["pairs"] == []
    assert "nothing to compare" in render_markdown(report)


def test_duplicate_labels_are_disambiguated(tmp_path):
    a = write_package(tmp_path / "x" / "w", deep_entities())
    b = write_package(tmp_path / "y" / "w", deep_entities("other"))
    labels = [w["label"] for w in generate_comparison_report([a, b])["worlds"]]
    assert labels == ["w", "w (2)"]


def test_invalid_inputs(tmp_path):
    with pytest.raises(ValueError, match="at least one"):
        generate_comparison_report([])
    with pytest.raises(ValueError, match="does not exist"):
        generate_comparison_report([tmp_path / "nope"])
    with pytest.raises(ValueError, match="Not a world package"):
        generate_comparison_report([tmp_path])


def test_resolve_batch_worlds_and_cli(tmp_path, capsys):
    batch = tmp_path / "batch_1"
    a = write_package(batch / "worlds" / "world_r1", deep_entities("one"))
    b = write_package(batch / "worlds" / "world_r2", deep_entities("two"))
    (batch / "batch_manifest.json").write_text(json.dumps({
        "worlds_dir": str(batch / "worlds"),
        "runs": [
            {"status": "completed", "run_id": "r1", "output_dir": str(a)},
            {"status": "failed", "run_id": "bad"},
            {"status": "completed", "run_id": "r2"}]}), encoding="utf-8")
    assert resolve_batch_worlds(batch) == [a.resolve(), b.resolve()]
    assert main(["--batch", str(batch)]) == 0
    assert (batch / "comparison.md").is_file()
    assert main([str(a), str(b)]) == 0
    assert "# World Comparison" in capsys.readouterr().out
    with pytest.raises(ValueError, match="batch manifest"):
        resolve_batch_worlds(tmp_path)
