"""Tests for input loading in example_run.py and isolation of examples/."""

import argparse
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
