"""Tests for input loading in example_run.py and isolation of examples/."""

import argparse
import json
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import example_run  # noqa: E402
from example_run import ContextInputError, load_context  # noqa: E402


def make_args(**overrides):
    values = {"context_file": None, "choice": "2", "image": []}
    values.update(overrides)
    return argparse.Namespace(**values)


def no_prompt(_message):
    raise AssertionError("prompt must not be called in non-interactive mode")


def test_there_is_no_builtin_default_input():
    assert not hasattr(example_run, "DEFAULT_CONTEXT")


def test_the_mechanism_paths_cover_the_moved_notebooks():
    names = {p.name for p in MECHANISM_PATHS}
    assert "local-v2.0.ipynb" in names
    assert "20250601-100-TIMES-AI-WORLD-BUILDING-v1.2.ipynb" in names
    assert not list(PROJECT_ROOT.glob("*.ipynb"))  # notebooks live in legacy/


def test_missing_input_is_an_error_in_non_interactive_mode():
    with pytest.raises(ContextInputError, match="--context-file"):
        load_context(make_args(), prompt=no_prompt)


def test_reads_the_supplied_file(tmp_path):
    source = tmp_path / "input.txt"
    source.write_text("自由形式の入力", encoding="utf-8")
    assert load_context(make_args(context_file=str(source)), prompt=no_prompt) == "自由形式の入力"


def test_empty_file_is_rejected(tmp_path):
    source = tmp_path / "empty.yaml"
    source.write_text("  \n", encoding="utf-8")
    with pytest.raises(ContextInputError, match="empty"):
        load_context(make_args(context_file=str(source)), prompt=no_prompt)


def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(ContextInputError, match="not found"):
        load_context(make_args(context_file=str(tmp_path / "nope.yaml")), prompt=no_prompt)


def test_interactive_menu_asks_for_a_path(tmp_path):
    source = tmp_path / "input.yaml"
    source.write_text("theme: x", encoding="utf-8")
    args = make_args(choice=None)
    assert load_context(args, prompt=lambda _m: str(source)) == "theme: x"


def test_interactive_blank_path_is_an_error():
    with pytest.raises(ContextInputError):
        load_context(make_args(choice=None), prompt=lambda _m: "")


def test_images_only_is_allowed_where_images_are_used():
    args = make_args(image=["scene.png"])
    assert load_context(args, prompt=no_prompt, allow_images_only=True) == ""
    with pytest.raises(ContextInputError):
        load_context(args, prompt=no_prompt)


# ---------------------------------------------------------------------------
# examples/ must stay a gallery: nothing in the mechanism may depend on it.
# ---------------------------------------------------------------------------

MECHANISM_PATHS = [
    *PROJECT_ROOT.joinpath("src").rglob("*.py"),
    *PROJECT_ROOT.joinpath("config").rglob("*.yaml"),
    *PROJECT_ROOT.glob("*.py"),
    *PROJECT_ROOT.glob("*.ipynb"),
    *PROJECT_ROOT.joinpath("legacy").glob("*.ipynb"),
    *(p for p in PROJECT_ROOT.joinpath("tests").rglob("*.py") if p.name != Path(__file__).name),
]


def _example_packages():
    root = PROJECT_ROOT / "examples"
    return [p for p in root.iterdir() if p.is_dir()] if root.is_dir() else []


def _example_input_phrases():
    """Distinctive quoted values from example inputs (e.g. a theme string)."""
    phrases = set()
    for package in _example_packages():
        for source in package.joinpath("input").glob("*"):
            if not source.is_file():
                continue
            text = source.read_text(encoding="utf-8", errors="ignore")
            for value in re.findall(r'"([^"\n]{6,})"', text):
                phrases.add(value)
    return phrases


@pytest.mark.parametrize("path", MECHANISM_PATHS, ids=lambda p: str(p.relative_to(PROJECT_ROOT)))
def test_mechanism_does_not_reference_examples(path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    for package in _example_packages():
        assert f"examples/{package.name}" not in text, f"{path} references examples/{package.name}"
    for phrase in _example_input_phrases():
        assert phrase not in text, f"{path} embeds example input: {phrase!r}"


# ---------------------------------------------------------------------------
# End-to-end non-interactive CLI run with the fake backend.
# ---------------------------------------------------------------------------

CONFIG_PATH = str(PROJECT_ROOT / "config" / "ollama_config.yaml")


@pytest.fixture
def quiet_logging(monkeypatch):
    monkeypatch.setattr(example_run, "setup_logging", lambda **kw: None)


def cli(tmp_path, *extra, backend=None):
    from tests.test_world_explore import RAW, make_backend

    source = tmp_path / "your_input.txt"
    source.write_text(RAW, encoding="utf-8")
    argv = ["--context-file", str(source), "--yes", "--config", CONFIG_PATH,
            "--output-dir", str(tmp_path / "out"), "--seed", "3",
            "--max-iterations", "4", *extra]
    return example_run.main(argv, backend=backend or make_backend())


def test_non_interactive_run_produces_the_world_reference(
        tmp_path, quiet_logging, capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", no_prompt)
    assert cli(tmp_path) == 0
    (package,) = (tmp_path / "out").glob("world_*")
    assert (package / "final" / "world.json").is_file()
    assert (package / "final" / "world_bible" / "README.md").is_file()
    assert (package / "final" / "world_report.md").is_file()
    assert (package / "input" / "your_input.txt").is_file()
    manifest = json.loads((package / "run_manifest.json").read_text("utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["run_seed"] == 3
    assert manifest["stop_reason"] == "max_iterations"
    assert manifest["budget"]["requested"] == {"max_iterations": 4}
    out = capsys.readouterr().out
    assert "final/world.json" in out and "max_iterations" in out


def test_budget_arguments_are_mapped_to_the_engine(tmp_path, quiet_logging):
    args = example_run.parse_args(
        ["--max-iterations", "7", "--max-minutes", "2", "--max-calls", "50"])
    assert example_run.budget_from_args(args) == {
        "max_iterations": 7, "max_wall_seconds": 120.0,
        "max_generation_calls": 50}
    assert example_run.budget_from_args(example_run.parse_args([])) == {}


def test_calls_budget_via_cli(tmp_path, quiet_logging):
    assert cli(tmp_path, "--max-iterations", "50", "--max-calls", "6") == 0
    (package,) = (tmp_path / "out").glob("world_*")
    manifest = json.loads((package / "run_manifest.json").read_text("utf-8"))
    assert manifest["stop_reason"] == "max_generation_calls"


def test_runs_greater_than_one_makes_a_batch(tmp_path, quiet_logging, capsys):
    assert cli(tmp_path, "--runs", "2") == 0
    (batch,) = (tmp_path / "out").glob("batch_*")
    assert (batch / "batch_manifest.json").is_file()
    assert len(list((batch / "worlds").glob("world_*"))) == 2
    assert (batch / "comparison.md").is_file()
    assert "Completed: 2" in capsys.readouterr().out


def test_resume_a_previous_run_from_the_cli(tmp_path, quiet_logging, capsys):
    from tests.test_world_explore import make_backend

    assert cli(tmp_path, "--max-iterations", "2") == 0
    (package,) = (tmp_path / "out").glob("world_*")
    run_id = package.name[len("world_"):]
    code = example_run.main(
        ["--choice", "2", "--run-id", run_id, "--config", CONFIG_PATH,
         "--output-dir", str(tmp_path / "out"), "--max-iterations", "5"],
        backend=make_backend())
    assert code == 0
    manifest = json.loads((package / "run_manifest.json").read_text("utf-8"))
    assert manifest["iterations"] == 5
    assert "Resumed run" in capsys.readouterr().out


def test_resume_reports_missing_runs(tmp_path, quiet_logging):
    assert example_run.main(
        ["--choice", "2", "--run-id", "nope", "--config", CONFIG_PATH,
         "--output-dir", str(tmp_path)]) == 1
    assert example_run.main(
        ["--choice", "2", "--config", CONFIG_PATH,
         "--output-dir", str(tmp_path)]) == 1


def test_yes_without_input_is_an_error_and_never_prompts(
        tmp_path, quiet_logging, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", no_prompt)
    assert example_run.main(["--yes"]) == 1
    assert "--context-file" in capsys.readouterr().out


def test_exit_choice_and_no_removed_options(capsys):
    assert example_run.main(["--choice", "3"]) == 0
    for removed in ("--structured-model", "--story-model", "--reference-model",
                    "--extract-context"):
        with pytest.raises(SystemExit):
            example_run.parse_args([removed, "x"])


def test_the_cli_does_not_hardcode_model_names():
    text = (PROJECT_ROOT / "example_run.py").read_text("utf-8")
    assert not hasattr(example_run, "LOCAL_MODELS")
    assert "gpt-oss" not in text and "llava" not in text
