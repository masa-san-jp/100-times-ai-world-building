"""Tests for the thin Pipeline wrapper around the world engine (fake backend)."""

import json
from pathlib import Path

import pytest
import yaml

from src.pipeline import ConfiguredBackend, Pipeline
from tests.test_world_explore import RAW, make_backend

CONFIG = Path(__file__).resolve().parent.parent / "config" / "ollama_config.yaml"


def write_config(tmp_path, **over):
    cfg = yaml.safe_load(CONFIG.read_text("utf-8"))
    cfg.update(over)
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return str(path)


def make(tmp_path, **kw):
    kw.setdefault("config_path", str(CONFIG))
    kw.setdefault("output_dir", tmp_path)
    kw.setdefault("backend", make_backend())
    kw.setdefault("seed", 11)
    kw.setdefault("budget", {"max_iterations": 4})
    return Pipeline(**kw)


def test_run_produces_world_package_and_records_the_manifest(tmp_path):
    p = make(tmp_path, run_id="r1", model="my-model")
    result = p.run(RAW, source_name="notes.txt")
    root = tmp_path / "world_r1"
    for rel in ("final/world.json", "final/world_bible/README.md",
                "final/world_report.md", "quality_report.json",
                "world/preferences.jsonl", "input/notes.txt",
                "input/input_brief.json", "world/world_axes.json"):
        assert (root / rel).exists(), rel
    m = json.loads((root / "run_manifest.json").read_text("utf-8"))
    assert m["status"] == "completed"
    assert m["run_seed"] == 11 and m["seed_source"] == "argument"
    assert m["backend"] == "fake" and m["model"] == "my-model"
    assert m["stop_reason"] == result.stop_reason == "max_iterations"
    assert m["iterations"] == 4
    assert m["budget"]["requested"] == {"max_iterations": 4}
    assert m["budget"]["effective"]["max_iterations"] == 4
    assert "selection" in m["engine_config"]["explore"]
    assert m["input"]["raw_file"] == "notes.txt"
    assert m["counters"]["generation_calls"] > 0
    assert m["quality_report"]["json"] == "quality_report.json"


def test_budget_keys_are_validated_and_defaults_come_from_config(tmp_path):
    with pytest.raises(ValueError, match="Unknown budget"):
        make(tmp_path, budget={"max_everything": 1})
    p = make(tmp_path, budget=None)
    assert p.budget["max_iterations"] == 200  # config/world/explore.yaml
    assert p.budget_requested == {}


def test_generation_calls_budget_stops_the_run(tmp_path):
    p = make(tmp_path, budget={"max_generation_calls": 6})
    assert p.run(RAW).stop_reason == "max_generation_calls"


def test_model_comes_from_config_and_cli_override(tmp_path):
    cfg = write_config(tmp_path, model={"name": "configured-model"},
                       models={"vision": "configured-vision"})
    from unittest.mock import patch
    with patch("src.llm.factory.build_backend_clients") as build:
        pass  # factory is exercised below with an injected backend
    p = Pipeline(config_path=cfg, output_dir=tmp_path / "a",
                 backend="ollama")
    assert p.model_names == {"generation": "configured-model",
                             "vision": "configured-vision"}
    assert p.client.model == "configured-model"
    p = Pipeline(config_path=cfg, output_dir=tmp_path / "b", model="cli",
                 vision_model="cli-v", backend="ollama")
    assert p.model_names == {"generation": "cli", "vision": "cli-v"}


def test_missing_model_is_an_error(tmp_path):
    cfg = write_config(tmp_path, model={})
    with pytest.raises(ValueError, match="No model configured"):
        Pipeline(config_path=cfg, output_dir=tmp_path, backend="ollama")
    cfg = write_config(tmp_path, anthropic={})
    with pytest.raises(ValueError, match="Anthropic backend requires"):
        Pipeline(config_path=cfg, output_dir=tmp_path, backend="anthropic")


@pytest.mark.parametrize("mode", ["auto", "prompt", "format"])
def test_ollama_json_mode_is_loaded_from_config(tmp_path, mode):
    cfg = write_config(tmp_path, server={"json_mode": mode})
    p = Pipeline(config_path=cfg, output_dir=tmp_path, backend="ollama")
    assert p.client.json_mode == mode
    assert p.vision_client.json_mode == mode


def test_ollama_json_mode_defaults_to_auto_for_older_configs(tmp_path):
    cfg = write_config(tmp_path, server={})
    p = Pipeline(config_path=cfg, output_dir=tmp_path, backend="ollama")
    assert p.client.json_mode == p.vision_client.json_mode == "auto"


def test_invalid_ollama_json_mode_in_config_is_rejected(tmp_path):
    cfg = write_config(tmp_path, server={"json_mode": "invalid"})
    with pytest.raises(ValueError, match="json_mode"):
        Pipeline(config_path=cfg, output_dir=tmp_path, backend="ollama")


def test_unsupported_backend_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="Unsupported"):
        Pipeline(config_path=str(CONFIG), output_dir=tmp_path,
                 backend="nonsense")


def test_resume_keeps_seed_and_environment(tmp_path):
    first = make(tmp_path, run_id="r2", model="orig", budget={"max_iterations": 2})
    first.run(RAW)
    again = Pipeline(config_path=str(CONFIG), output_dir=tmp_path,
                     run_id="r2", backend=make_backend(),
                     budget={"max_iterations": 5})
    assert again.run_seed == 11
    assert again.model == "orig"  # stored environment, no override
    result = again.resume()
    assert result.iterations == 5
    m = json.loads((tmp_path / "world_r2" / "run_manifest.json").read_text("utf-8"))
    assert m["status"] == "completed" and m["iterations"] == 5


def test_seed_mismatch_on_existing_run_is_rejected(tmp_path):
    make(tmp_path, run_id="r3", budget={"max_iterations": 1}).run(RAW)
    with pytest.raises(ValueError, match="does not match"):
        make(tmp_path, run_id="r3", seed=99)


def test_different_input_for_existing_run_is_rejected(tmp_path):
    p = make(tmp_path, run_id="r4", budget={"max_iterations": 1})
    p.run(RAW)
    with pytest.raises(ValueError, match="differs"):
        make(tmp_path, run_id="r4").run(RAW + " more")


def test_resume_without_stored_input_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="no stored input"):
        make(tmp_path, run_id="r5").resume()


def test_interrupted_run_is_recorded_and_can_be_resumed(tmp_path):
    p = make(tmp_path, run_id="r6", backend=make_backend(fail_after=6))
    with pytest.raises(KeyboardInterrupt, match="interrupted"):
        p.run(RAW)
    m = json.loads((tmp_path / "world_r6" / "run_manifest.json").read_text("utf-8"))
    assert m["status"] == "cancelled"
    ok = make(tmp_path, run_id="r6").resume()
    assert ok.stop_reason == "max_iterations"


def test_each_new_run_gets_its_own_package(tmp_path):
    a, b = make(tmp_path), make(tmp_path)
    assert a.run_id != b.run_id
    assert a.package_dir != b.package_dir


def test_configured_backend_applies_defaults_without_overriding_calls():
    seen = []

    class Inner:
        model = "m"

        def generate_json(self, prompt, **kw):
            seen.append(kw)
            return {}

    b = ConfiguredBackend(Inner(), {"max_tokens": 10, "think": None, "num_ctx": 5})
    b.generate_json("p")
    b.generate_json("p", max_tokens=99)
    assert seen[0] == {"max_tokens": 10, "num_ctx": 5}
    assert seen[1] == {"max_tokens": 99, "num_ctx": 5}
    assert b.model == "m"


def test_check_prerequisites_uses_the_backend(tmp_path):
    assert make(tmp_path).check_prerequisites(include_vision=True)
