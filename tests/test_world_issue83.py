"""Issue 83: the review verdict meanings and the bracketed-term rule for quoted speech."""

from pathlib import Path

import yaml


CONFIG = Path(__file__).resolve().parent.parent / "config"
REVIEW = yaml.safe_load((CONFIG / "prompts/world/steps.yaml").read_text(encoding="utf-8"))["steps"]["review"]


def verdict_meaning(key):
    return next((line for line in REVIEW.splitlines() if line.startswith(key + ":")), "")


def test_review_instruction_defines_each_verdict():
    for key in ("consistent", "objective", "no_outside_premises"):
        assert verdict_meaning(key), key


def test_newly_named_places_and_institutions_are_not_outside_premises():
    assert "この世界で新しく名付けた場所・制度・組織・人物・物の名前は違反ではない" in verdict_meaning("no_outside_premises")


def test_bracketed_terms_are_not_quoted_speech():
    assert "用語を括弧で示すことは発話ではない" in verdict_meaning("objective")
