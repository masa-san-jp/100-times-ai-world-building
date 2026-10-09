"""The judging tasks run on their own backend/model; everything else does not."""

import json
from pathlib import Path

import pytest
import yaml

from example_run import parse_args
from src.pipeline import Pipeline
from src.world.explore import run_world_engine
from tests.test_world_builder import cfg
from tests.test_world_explore import RAW, make_backend

JUDGE_STEPS = ("real_world_check", "review")
CONFIG = Path(__file__).resolve().parent.parent / "config" / "ollama_config.yaml"


def steps(backend):
    found = []
    for call in backend.schema_calls:
        line = next((l for l in call["prompt"].splitlines() if l.startswith("STEP: ")), "")
        found.append(line[len("STEP: "):])
    return found


def run(tmp_path, backend, judge=None, **kw):
    return run_world_engine(RAW, package_dir=tmp_path, backend=backend, judge_backend=judge,
                            config=cfg(), budget={"max_iterations": 2}, **kw)


def test_judge_backend_receives_only_judging_tasks(tmp_path):
    generation, judge = make_backend(), make_backend()
    run(tmp_path, generation, judge)
    judged, generated = steps(judge), steps(generation)
    assert judged and set(judged) <= set(JUDGE_STEPS)
    assert "real_world_check" in judged
    assert generated and not set(generated) & set(JUDGE_STEPS)


def test_without_judge_backend_everything_uses_the_generation_backend(tmp_path):
    generation = make_backend()
    run(tmp_path, generation)
    assert set(JUDGE_STEPS) <= set(steps(generation))


def test_judge_calls_share_the_generation_call_budget(tmp_path):
    generation, judge = make_backend(), make_backend()
    result = run_world_engine(RAW, package_dir=tmp_path, backend=generation, judge_backend=judge,
                              config=cfg(), budget={"max_iterations": 2})
    assert result.counters["generation_calls"] >= len(steps(judge))


def pipeline(tmp_path, tmp_cfg=None, **kw):
    kw.setdefault("config_path", str(tmp_cfg or CONFIG))
    return Pipeline(output_dir=tmp_path, backend=make_backend(), seed=5,
                    budget={"max_iterations": 2}, **kw)


def test_manifest_and_report_show_both_models(tmp_path):
    p = pipeline(tmp_path, run_id="j", model="gen-m", judge_model="judge-m")
    p.run(RAW)
    root = tmp_path / "world_j"
    manifest = json.loads((root / "run_manifest.json").read_text("utf-8"))
    assert manifest["model"] == "gen-m" and manifest["judge_model"] == "judge-m"
    report = (root / "final" / "world_report.md").read_text("utf-8")
    assert "gen-m" in report and "judge-m" in report
    summary = report.split("## Structured output", 1)[0]
    assert "gen-m" in summary and "judge-m" in summary


def test_task_metrics_name_the_model_that_ran_each_task(tmp_path):
    generation, judge = make_backend(), make_backend()
    generation.model, judge.model = "gen-m", "judge-m"
    run(tmp_path, generation, judge)
    metrics = json.loads((tmp_path / "run_manifest.json").read_text("utf-8"))["structured"]
    assert metrics["real_world_check"]["model"] == "judge-m"
    assert metrics["review"]["model"] == "judge-m"
    assert metrics["name"]["model"] == "gen-m"


def test_judge_model_defaults_to_the_generation_model(tmp_path):
    p = pipeline(tmp_path, run_id="d", model="gen-m")
    assert p.judge_client is None and p.judge_model == "gen-m"
    p.run(RAW)
    manifest = json.loads((tmp_path / "world_d" / "run_manifest.json").read_text("utf-8"))
    assert manifest["judge_model"] == "gen-m"


def test_config_sets_the_judge_model_and_the_argument_wins(tmp_path):
    config = yaml.safe_load(CONFIG.read_text("utf-8"))
    config["engine"]["judge_model"] = "cfg-judge"
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    assert pipeline(tmp_path, path, run_id="a", model="gen-m").judge_model == "cfg-judge"
    assert pipeline(tmp_path, path, run_id="b", model="gen-m",
                    judge_model="cli-judge").judge_model == "cli-judge"


def test_resume_keeps_the_stored_judge_model(tmp_path):
    pipeline(tmp_path, run_id="r", model="gen-m", judge_model="judge-m")
    assert pipeline(tmp_path, run_id="r").judge_model == "judge-m"


def test_cli_accepts_judge_model():
    assert parse_args(["--judge-model", "j"]).judge_model == "j"
    assert parse_args([]).judge_model is None


def test_default_config_judge_model_is_empty():
    assert yaml.safe_load(CONFIG.read_text("utf-8"))["engine"]["judge_model"] in ("", None)
