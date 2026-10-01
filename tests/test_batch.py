"""Tests for batch execution: N independent worlds from the same input."""

import json
from pathlib import Path

from src.batch import BatchRunner, run_batch
from tests.test_world_explore import RAW, make_backend

CONFIG = str(Path(__file__).resolve().parent.parent / "config" / "ollama_config.yaml")


def kwargs(tmp_path, backend=None):
    return {"config_path": CONFIG, "output_dir": str(tmp_path),
            "backend": backend or make_backend()}


def test_batch_creates_independent_packages_and_a_manifest(tmp_path):
    summary = run_batch(RAW, runs=3, seed=123,
                        pipeline_kwargs=kwargs(tmp_path),
                        budget={"max_iterations": 3})
    assert summary["status"] == "completed"
    assert summary["completed_runs"] == 3 and summary["failed_runs"] == 0
    seeds = [r["run_seed"] for r in summary["runs"]]
    assert len(set(seeds)) == 3
    dirs = [Path(r["output_dir"]) for r in summary["runs"]]
    assert len({d for d in dirs}) == 3
    for r, d in zip(summary["runs"], dirs):
        assert d.parent == Path(summary["worlds_dir"])
        assert (d / "final" / "world.json").is_file()
        assert (d / "final" / "world_bible" / "README.md").is_file()
        assert r["stop_reason"] == "max_iterations"
        assert r["entities"] > 0
        manifest = json.loads((d / "run_manifest.json").read_text("utf-8"))
        assert manifest["run_seed"] == r["run_seed"]
    saved = json.loads(Path(summary["summary_path"]).read_text("utf-8"))
    assert saved["batch_seed"] == 123
    assert saved["budget"] == {"max_iterations": 3}
    assert summary["summary_path"].endswith("batch_manifest.json")


def test_batch_writes_a_comparison_for_two_or_more_worlds(tmp_path):
    summary = run_batch(RAW, runs=2, seed=5, pipeline_kwargs=kwargs(tmp_path),
                        budget={"max_iterations": 3})
    comparison = Path(summary["comparison_path"])
    text = comparison.read_text("utf-8")
    assert "# World Comparison" in text and "Cross-world overlap" in text
    single = run_batch(RAW, runs=1, seed=5, pipeline_kwargs=kwargs(tmp_path),
                       budget={"max_iterations": 2})
    assert "comparison_path" not in single


def test_same_batch_seed_gives_same_run_seeds(tmp_path):
    a = run_batch(RAW, runs=2, seed=9, pipeline_kwargs=kwargs(tmp_path / "a"),
                  budget={"max_iterations": 1})
    b = run_batch(RAW, runs=2, seed=9, pipeline_kwargs=kwargs(tmp_path / "b"),
                  budget={"max_iterations": 1})
    assert [r["run_seed"] for r in a["runs"]] == [r["run_seed"] for r in b["runs"]]


def test_batch_continues_after_one_failure(tmp_path):
    from src.llm.fake import FakeLLMBackend

    inner = make_backend()
    state = {"n": 0}

    def respond(prompt):
        # Fail every call of the second world's input stage.
        if prompt.startswith("SOURCE MATERIAL"):
            state["n"] += 1
            if state["n"] == 2:
                raise RuntimeError("intentional failure")
        return inner._json_source(prompt)

    summary = BatchRunner(kwargs(tmp_path, FakeLLMBackend(respond))).run(
        RAW, runs=3, seed=456, budget={"max_iterations": 1})
    assert summary["status"] == "completed_with_errors"
    assert (summary["completed_runs"], summary["failed_runs"]) == (2, 1)
    failed = [r for r in summary["runs"] if r["status"] == "failed"][0]
    assert "intentional failure" in failed["error"]
    assert Path(summary["comparison_path"]).is_file()


def test_batch_rejects_zero_runs(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        run_batch(RAW, runs=0, pipeline_kwargs=kwargs(tmp_path))
