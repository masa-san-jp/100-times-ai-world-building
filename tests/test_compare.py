import json
from pathlib import Path

import pytest
import yaml

import src.batch as batch_module
from src.batch import BatchRunner
from src.compare import (
    generate_comparison_report,
    render_markdown,
    resolve_batch_worlds,
)


def _write_world(root: Path, name: str, variant: str) -> Path:
    world = root / name
    intermediate = world / "intermediate"
    intermediate.mkdir(parents=True)

    (world / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": name,
                "run_seed": 100 + len(name),
                "models": {"structured": "test-model"},
                "user_context_sha256": f"hash-{variant}",
            }
        ),
        encoding="utf-8",
    )
    yaml_data = {
        "05_plottype": {"selected_plottype": {"plot_type": f"plot-{variant}"}},
        "06_characters_list": {
            "characters": [{"name": f"Alice-{variant}", "role": "protagonist"}]
        },
        "15_social_structure": {
            "social_structure": {"system": f"system-{variant}"}
        },
        "16_living_environment": {
            "living_environment": {"community": f"community-{variant}"}
        },
        "19_future_scenarios": {
            "scenarios": [
                {
                    "scenario_type": "optimistic",
                    "timeline": f"future-{variant}",
                }
            ]
        },
        "20_plot": {
            "plot": {
                "chapters": [
                    {"chapter": 1, "title": f"Opening-{variant}"},
                    {"chapter": 2, "title": f"Ending-{variant}"},
                ]
            }
        },
    }
    for filename, data in yaml_data.items():
        (intermediate / f"{filename}.yaml").write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    for filename, key, prefix in (
        ("01_desire_list", "desires", "desire"),
        ("02_ability_list", "abilities", "ability"),
        ("03_role_list", "roles", "role"),
    ):
        items = [f"{prefix}-{index:03d}" for index in range(100)]
        if variant == "different":
            items = [f"other-{prefix}-{index:03d}" for index in range(100)]
        (intermediate / f"{filename}.yaml").write_text(
            yaml.safe_dump({key: items}, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    return world


def test_three_world_comparison_reports_expected_overlap_matrix(tmp_path):
    first = _write_world(tmp_path, "world_a", "same")
    second = _write_world(tmp_path, "world_b", "same")
    third = _write_world(tmp_path, "world_c", "different")

    report = generate_comparison_report([first, second, third])
    exact = report["divergence"]["normalized_exact_matrix"]

    assert exact[0][0] == 1.0
    assert exact[0][1] == 1.0
    assert exact[1][0] == 1.0
    assert exact[0][2] == 0.0
    assert exact[1][2] == 0.0
    assert "plot-same" in report["worlds"][0]["plot_type"]
    assert "Alice-same" in report["worlds"][0]["characters"]
    assert "Opening-same" in report["worlds"][0]["chapters"]
    assert "一貫性: WARN（プロット未登場1/本文未登場1）" in (
        report["worlds"][0]["quality"]
    )
    assert not (first / "quality_report.json").exists()
    assert not (first / "quality_report.md").exists()
    assert "同じ入力から生成された世界" in render_markdown(report)


def test_approximate_matrix_uses_thresholded_near_matches(tmp_path):
    first = _write_world(tmp_path, "world_exact", "same")
    second = _write_world(tmp_path, "world_near", "same")
    for filename, key, prefix in (
        ("01_desire_list", "desires", "desire"),
        ("02_ability_list", "abilities", "ability"),
        ("03_role_list", "roles", "role"),
    ):
        first_path = first / "intermediate" / f"{filename}.yaml"
        second_path = second / "intermediate" / f"{filename}.yaml"
        first_data = yaml.safe_load(first_path.read_text(encoding="utf-8"))
        second_data = yaml.safe_load(second_path.read_text(encoding="utf-8"))
        first_data[key][0] = f"{prefix}-000-aaaaaaaaaa"
        second_data[key][0] = f"{prefix}-000-aaaaaaaab"
        first_path.write_text(
            yaml.safe_dump(first_data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        second_path.write_text(
            yaml.safe_dump(second_data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    report = generate_comparison_report(
        [first, second], config={"quality": {"near_duplicate_threshold": 0.8}}
    )
    exact = report["divergence"]["normalized_exact_matrix"][0][1]
    approximate = report["divergence"]["approximate_matrix"][0][1]

    assert exact == pytest.approx(0.99)
    assert approximate == pytest.approx(1.0)
    assert approximate != exact
    assert report["divergence"]["near_duplicate_threshold"] == 0.8
    assert "Jaccard ≥ 0.80" in render_markdown(report)

    strict_report = generate_comparison_report(
        [first, second], config={"quality": {"near_duplicate_threshold": 0.95}}
    )
    assert strict_report["divergence"]["approximate_matrix"][0][1] == (
        pytest.approx(0.99)
    )


def test_batch_resolution_uses_manifest_and_worlds_directory(tmp_path):
    batch = tmp_path / "batch_001"
    worlds = batch / "worlds"
    first = _write_world(worlds, "world_one", "one")
    second = _write_world(worlds, "world_two", "two")
    (batch / "batch_manifest.json").write_text(
        json.dumps(
            {
                "worlds_dir": "worlds",
                "runs": [
                    {"status": "completed", "output_dir": "worlds/world_one"},
                    {"status": "failed", "output_dir": "worlds/world_two"},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert resolve_batch_worlds(batch) == [first.resolve()]
    assert second.is_dir()


def test_batch_runner_writes_comparison_without_ollama(monkeypatch, tmp_path):
    class FakePipeline:
        def __init__(self, **kwargs):
            output_dir = Path(kwargs["output_dir"])
            self.run_id = f"run_{kwargs['seed']}"
            self.base_dir = str(output_dir / f"world_{kwargs['seed']}")
            Path(self.base_dir).mkdir(parents=True)
            self.manifest = type(
                "Manifest",
                (),
                {
                    "data": {"status": "completed"},
                    "path": Path(self.base_dir) / "run_manifest.json",
                },
            )()

        def run_full_pipeline(self, *args, **kwargs):
            return {"ok": True}

    monkeypatch.setattr(batch_module, "Pipeline", FakePipeline)
    monkeypatch.setattr(
        batch_module,
        "load_config",
        lambda _path: {"output": {"base_dir": str(tmp_path)}},
    )

    summary = BatchRunner({"config_path": "unused.yaml"}).run(
        user_context="context", runs=2, seed=123
    )

    comparison_path = Path(summary["comparison_path"])
    assert comparison_path.is_file()
    assert comparison_path.name == "comparison.md"
    assert "# World Comparison" in comparison_path.read_text(encoding="utf-8")
