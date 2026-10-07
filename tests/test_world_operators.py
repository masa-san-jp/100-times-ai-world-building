"""Operation placement, validation and genre-neutral task descriptions."""
from pathlib import Path
import re
import pytest
from src.world.builder import ALLOWED_TYPES, EntityBuilder
from src.world.operators import OPERATORS, OperatorError, load_prompts
from src.world.graph import new_graph, make_entity, validate_graph
from tests.test_world_explore import BRIEF, AXES, make_backend
CONFIG = Path(__file__).resolve().parents[1] / "config"
PROV = {"statement_ids": ["s1"], "derived_from": [], "reason": ""}

@pytest.mark.parametrize("op", OPERATORS)
def test_each_operator_builds_a_valid_entity_without_committing(op):
    graph = new_graph("en")
    graph["entities"] = [make_entity("e1", "place", "Root", "world", provenance=PROV)]
    original = list(graph["entities"])
    result = EntityBuilder(make_backend()).build(graph, op, None if op == "premise" else "e1",
        brief=BRIEF, axes=AXES, contract={}, frontier_axis=None)
    assert result.entity, result.failure
    assert graph["entities"] == original
    e = result.entity
    assert e["type"] in ALLOWED_TYPES[op]
    assert e["scale"] == ("region" if op == "zoom" else "world")
    assert e["parent"] == ("e1" if op == "zoom" else None)
    if op in {"cause", "perspective", "history", "document"}:
        assert "e1" in e["provenance"]["derived_from"]
        relation = {"cause": "causes", "history": "affects"}.get(op, "related_to")
        assert {"type": relation, "target": "e1"} in e["relations"]
    if op == "document":
        assert e["type"] == "document"
        assert not any(s.step == "type" for s in result.steps)
    graph["entities"].append(e)
    assert validate_graph(graph, AXES, BRIEF) == []

@pytest.mark.parametrize("op,target", [("unknown", None), ("zoom", None), ("expand", "absent")])
def test_invalid_requests(op, target):
    with pytest.raises(OperatorError):
        EntityBuilder(make_backend()).build(new_graph("en"), op, target,
            brief=BRIEF, axes=AXES, contract={}, frontier_axis=None)

def test_zoom_below_detail_is_an_error():
    graph = new_graph("en")
    graph["entities"] = [make_entity("e1", "place", "Root", "detail", provenance=PROV)]
    with pytest.raises(OperatorError):
        EntityBuilder(make_backend()).build(graph, "zoom", "e1", brief=BRIEF,
                                          axes=AXES, contract={}, frontier_axis=None)

BANNED_TERMS = [
    "protagonist", "主人公", "plot", "プロット", "chapter", "章", "novel",
    "小説", "story", "物語", "dialogue", "台詞", "character arc", "future",
    "未来", "past", "過去", "fantasy", "ファンタジー", "sci-fi",
    "science fiction", "SF", "medieval", "中世", "magic", "魔法", "kingdom",
    "王国", "city", "都市", "robot", "ロボット", "cyberpunk",
]


def test_operator_prompts_have_no_story_or_genre_terms():
    prompts = load_prompts()
    assert set(prompts["operators"]) == set(OPERATORS)
    raw = (CONFIG / "prompts" / "world" / "operators.yaml").read_text("utf-8").lower()
    for t in BANNED_TERMS:
        if t.isascii():
            assert not re.search(r"\b" + re.escape(t.lower()) + r"\b", raw), t
        else:
            assert t not in raw, t
