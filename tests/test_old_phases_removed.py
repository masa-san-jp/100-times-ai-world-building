"""The story-oriented phases of the old pipeline must stay removed."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# "novelty" is a verifier of the new engine, hence the lookahead.
FORBIDDEN = re.compile(
    r"protagonist|plot_?type|chapter|novel(?!ty)|future_scenario|"
    r"desire_list|ability_list|role_list|people_list|context_extraction|"
    r"social_groups|phase[0-9]",
    re.IGNORECASE,
)

SCANNED = [
    *ROOT.joinpath("src").rglob("*.py"),
    *ROOT.joinpath("config").rglob("*.yaml"),
    ROOT / "example_run.py",
    ROOT / "setup_check.py",
]


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_old_phase_terms(path):
    match = FORBIDDEN.search(path.read_text(encoding="utf-8"))
    assert match is None, f"{path.relative_to(ROOT)} mentions {match.group(0)!r}"


def test_scan_covers_the_code_and_config():
    names = {p.name for p in SCANNED}
    assert {"pipeline.py", "explore.yaml", "ollama_config.yaml",
            "example_run.py", "setup_check.py"} <= names


@pytest.mark.parametrize("relative", [
    "config/prompts/expansion.yaml",
    "config/prompts/plot_generation.yaml",
    "config/prompts/story_generation.yaml",
    "config/prompts/world_building.yaml",
])
def test_old_prompt_files_are_gone(relative):
    assert not (ROOT / relative).exists()


def test_old_pipeline_api_is_gone():
    from src.pipeline import Pipeline

    for name in ("run_full_pipeline", "run_phase1_expansion",
                 "run_phase2_characters", "run_phase3_world_building",
                 "run_phase4_plot_generation", "run_phase5_novel_generation",
                 "run_phase6_reference_generation",
                 "run_phase0_context_extraction"):
        assert not hasattr(Pipeline, name)
    assert hasattr(Pipeline, "run") and hasattr(Pipeline, "resume")


@pytest.mark.parametrize("path", [p for p in SCANNED if p.suffix == ".py"],
                         ids=lambda p: str(p.relative_to(ROOT)))
def test_no_model_names_in_code(path):
    text = path.read_text(encoding="utf-8")
    assert not re.search(r"gpt-oss|llava|claude-[a-z0-9]|llama3|mistral:", text)
