"""Tests for deciding world axes from an input brief."""

import json
import re
from pathlib import Path

import yaml
import pytest

from src.llm import FakeLLMBackend
from src.world import WorldAxesBuilder, load_axes, load_catalog
from src.world.axes import NO_INPUT_REASON

CONFIG = Path(__file__).resolve().parent.parent / "config"


def _brief(*texts):
    return {
        "statements": [
            {"id": f"s{i}", "text": t, "quote": t}
            for i, t in enumerate(texts, 1)
        ],
        "open_questions": [{"id": "q1", "text": "unresolved point"}],
        "constraints": [],
    }


def _build(tmp_path, response, brief):
    response = {"axes": [{"name": "", "reason": "", "statement_ids": [], **a} for a in response["axes"]]}
    return WorldAxesBuilder(
        FakeLLMBackend(json_responses=response), tmp_path
    ).build(brief)


def _by_id(result):
    return {a["id"]: a for a in result.axes}


def test_every_axis_has_grounds_and_all_catalog_domains_present(tmp_path):
    brief = _brief("alpha is scarce", "beta is shared")
    result = _build(tmp_path, {"axes": [
        {"domain": "resources_economy", "meaning": "alpha scarcity",
         "weight": 0.9, "statement_ids": ["s1"]},
        {"domain": "kinship_community", "meaning": "beta sharing",
         "weight": 0.7, "statement_ids": ["s2", "s99"]},
    ]}, brief)
    axes = _by_id(result)
    catalog_ids = [d["id"] for d in load_catalog()["domains"]]
    assert set(catalog_ids) <= set(axes)
    floor = load_catalog()["min_weight"]
    for axis in result.axes:
        g = axis["grounds"]
        assert g["statement_ids"] or g["reason"]
        assert floor <= axis["weight"] <= 1
    assert axes["kinship_community"]["grounds"]["statement_ids"] == ["s2"]
    assert axes["history"]["weight"] == floor
    assert axes["history"]["grounds"]["reason"] == NO_INPUT_REASON
    saved = load_axes(result.axes_path)
    assert saved == result.axes


def test_weights_follow_input_and_differ_between_inputs(tmp_path):
    def resp(domain):
        return {"axes": [{"domain": domain, "meaning": "m", "weight": 0.95,
                          "statement_ids": ["s1"]}]}

    a = _build(tmp_path / "a", resp("geography_climate"), _brief("x"))
    b = _build(tmp_path / "b", resp("language_writing"), _brief("y"))
    wa, wb = _by_id(a), _by_id(b)
    assert wa["geography_climate"]["weight"] > wb["geography_climate"]["weight"]
    assert wb["language_writing"]["weight"] > wa["language_writing"]["weight"]
    assert a.to_dict() != b.to_dict()


def test_invalid_output_requires_repair_and_is_never_filled(tmp_path):
    bad = {"axes": [{"domain": "unknown", "weight": "high", "statement_ids": "s1"}]}
    good = {"axes": [{"domain": "history", "name": "", "meaning": "m", "weight": 0.7,
                       "statement_ids": ["s1"], "reason": ""}]}
    backend = FakeLLMBackend([bad, good])
    result = WorldAxesBuilder(backend, tmp_path).build(_brief("one"))
    assert _by_id(result)["history"]["weight"] == 0.7
    assert len(backend.json_prompts) == 2
    assert "REPAIR INSTRUCTIONS" in backend.json_prompts[1]
    assert "enum" in backend.json_prompts[1] and "required" in backend.json_prompts[1]


@pytest.mark.parametrize("response", [{}, {"axes": "x"}, {"statements": []}])
def test_garbage_response_fails_instead_of_yielding_catalog(tmp_path, response):
    from src.world.structured import StructuredFailure
    with pytest.raises(StructuredFailure, match="world_axes"):
        WorldAxesBuilder(FakeLLMBackend(response), tmp_path).build(_brief("a"))
    assert not (tmp_path / "world_axes.json").exists()


def test_input_can_add_domains_with_grounds(tmp_path):
    brief = _brief("something outside the catalog")
    result = _build(tmp_path, {"axes": [
        {"domain": None, "name": "Custom area", "meaning": "specific",
         "weight": 0.8, "statement_ids": ["s1"]},
        {"domain": None, "name": "Needed area", "meaning": "needed",
         "weight": 0.4, "reason": "required for functioning"},
        {"domain": None, "name": "Custom area", "meaning": "dup",
         "weight": 0.2, "statement_ids": ["s1"]},
    ]}, brief)
    added = [a for a in result.axes if a["origin"] == "added"]
    assert [a["name"] for a in added] == [
        "Custom area", "Needed area", "Custom area"
    ]
    ids = [a["id"] for a in result.axes]
    assert len(ids) == len(set(ids))
    assert added[0]["id"] == "x_custom_area"
    assert added[0]["weight"] == 0.8


def test_added_axes_are_capped(tmp_path):
    cap = load_catalog()["max_added_axes"]
    proposals = [
        {"domain": None, "name": f"Area {i}", "meaning": "m",
         "weight": 0.5, "statement_ids": ["s1"]}
        for i in range(cap + 5)
    ]
    result = _build(tmp_path, {"axes": proposals}, _brief("a"))
    assert sum(a["origin"] == "added" for a in result.axes) == cap


def test_prompt_carries_brief_and_catalog_ids_compactly(tmp_path):
    backend = FakeLLMBackend(json_responses={"axes": []})
    brief = _brief("fact one")
    WorldAxesBuilder(backend, tmp_path).build(brief)
    prompt = backend.json_prompts[0]
    assert "s1: fact one" in prompt
    assert "history:" in prompt
    assert len(prompt) < 4000


def test_no_dependence_on_legacy_fixed_schema():
    source = (Path(__file__).resolve().parent.parent
              / "src" / "world" / "axes.py").read_text("utf-8")
    text = source + (CONFIG / "world" / "domains.yaml").read_text("utf-8")
    for term in ("observation", "interpretation", "events", "key_elements"):
        assert term not in text


BANNED_TERMS = [
    "protagonist", "主人公", "plot", "プロット", "chapter", "章",
    "novel", "小説", "story", "物語", "dialogue", "台詞", "character arc",
    "future", "未来", "past", "過去", "fantasy", "ファンタジー",
    "sci-fi", "science fiction", "SF", "medieval", "中世", "magic", "魔法",
    "kingdom", "王国", "city", "都市", "robot", "ロボット", "cyberpunk",
]


def test_axes_prompt_has_no_story_or_genre_terms():
    prompt = (CONFIG / "prompts" / "world_axes.yaml").read_text("utf-8")
    lowered = prompt.lower()
    for term in BANNED_TERMS:
        assert term.lower() not in lowered, term


def test_catalog_has_no_story_or_genre_terms():
    # Whole-word match: "history" is a legitimate domain, not a banned "story".
    catalog = yaml.safe_load(
        (CONFIG / "world" / "domains.yaml").read_text("utf-8")
    )
    for d in catalog["domains"]:
        text = f"{d['name']} {d['description']}".lower()
        for term in BANNED_TERMS:
            pattern = r"\b" + re.escape(term.lower()) + r"\b"
            if term.isascii():
                assert not re.search(pattern, text), term
            else:
                assert term not in text, term
