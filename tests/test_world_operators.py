"""Tests for the world generation operators (fake backend only)."""

import re
from pathlib import Path

import pytest

from src.llm.fake import FakeLLMBackend
from src.world.graph import make_entity, new_graph, validate_graph
from src.world.operators import (
    OPERATORS, OperatorConfig, OperatorError, OperatorRunner, expand,
    load_prompts, run_operator, validate_candidate, zoom,
)

CONFIG = Path(__file__).resolve().parent.parent / "config"

BRIEF = {"statements": [{"id": "s1", "text": "alpha rule", "quote": "alpha"},
                        {"id": "s2", "text": "beta supply", "quote": "beta"}]}
AXES = [{"id": "geo", "name": "Geo", "meaning": "land"},
        {"id": "eco", "name": "Eco", "meaning": "trade"}]
PROV = {"statement_ids": ["s1"], "derived_from": [], "reason": ""}


def _graph():
    g = new_graph("xx")

    def mk(i, s, p):
        return make_entity(i, "place", f"Name{i}", s, axes=["geo"], parent=p,
                           summary=f"sum {i}", provenance=PROV)
    g["entities"] = [mk("e1", "world", None), mk("e2", "region", "e1"),
                     mk("e3", "settlement", "e2"), mk("e4", "detail", "e3")]
    return g


def _cand(name="N", **kw):
    c = {
        "type": "concept", "name": name, "axes": ["eco"],
        "summary": "Objective explanation.",
        "facts": [{"kind": "proper_noun", "text": "Harbor Ledger"},
                  {"kind": "number", "text": "42 units"},
                  {"kind": "object", "text": "brass seal"},
                  {"kind": "object", "text": "tin cup"}],
        "statement_ids": ["s1"], "derived_from": [], "reason": "",
    }
    c.update(kw)
    return c


def _backend(*cands):
    return FakeLLMBackend(lambda prompt: {"candidates": list(cands)})


def _run(op, cands, target="e3", n=3, graph=None, **kw):
    g = graph or _graph()
    r = OperatorRunner(_backend(*cands), **kw)
    return g, r.run(op, g, None if op == "premise" else target, n,
                    brief=BRIEF, axes=AXES)


@pytest.mark.parametrize("op", OPERATORS)
def test_each_operator_returns_valid_candidates(op):
    cands = [_cand(f"Name-{i}", type="document" if op == "document" else "event")
             for i in range(3)]
    g, out = _run(op, cands, n=3)
    assert len(out) == 3
    ids = [c["entity"]["id"] for c in out]
    assert len(set(ids)) == 3
    for c in out:
        assert c["operator"] == op
        assert c["entity"]["summary"] and c["entity"]["facts"]
        assert validate_candidate(g, c, AXES, BRIEF) == []
    g["entities"].extend(c["entity"] for c in out)
    assert validate_graph(g, AXES, BRIEF) == []


def test_candidates_are_not_committed():
    g, out = _run("expand", [_cand()])
    assert len(g["entities"]) == 4 and out


def test_candidates_without_provenance_are_dropped():
    g, out = _run("expand", [
        _cand("A", statement_ids=[], derived_from=[]),
        _cand("B", statement_ids=["nope"], derived_from=["e999"]),
        _cand("C", derived_from=["e1"], statement_ids=[], reason=""),
        _cand("D"),
    ])
    assert [c["entity"]["name"] for c in out] == ["D"]


def test_derived_from_with_reason_is_accepted():
    _, out = _run("expand", [
        _cand("A", statement_ids=[], derived_from=["e2"], reason="because")])
    assert out[0]["entity"]["provenance"]["derived_from"] == ["e2"]


def test_model_supplied_ids_scale_parent_are_ignored():
    _, out = _run("zoom", [_cand("A", id="e1", scale="world", parent="e1")])
    e = out[0]["entity"]
    assert e["id"] == "e5" and e["scale"] == "district" and e["parent"] == "e3"


def test_zoom_places_one_scale_below_target():
    _, out = _run("zoom", [_cand("A")], target="e2")
    e = out[0]["entity"]
    assert (e["scale"], e["parent"]) == ("settlement", "e2")


def test_zoom_below_detail_is_an_error():
    with pytest.raises(OperatorError):
        _run("zoom", [_cand()], target="e4")


def test_expand_is_sibling_of_target():
    _, out = _run("expand", [_cand()], target="e3")
    e = out[0]["entity"]
    assert (e["scale"], e["parent"]) == ("settlement", "e2")


def test_relation_operators_link_to_target():
    expect = {"cause": "causes", "perspective": "related_to",
              "history": "affects", "document": "related_to"}
    for op, rel in expect.items():
        _, out = _run(op, [_cand(type="event")])
        assert {"type": rel, "target": "e3"} in out[0]["entity"]["relations"]


def test_document_type_is_forced():
    _, out = _run("document", [_cand(type="event")])
    assert out[0]["entity"]["type"] == "document"


def test_premise_is_world_scale_without_target():
    _, out = _run("premise", [_cand()])
    e = out[0]["entity"]
    assert (e["scale"], e["parent"]) == ("world", None)
    assert out[0]["target"] is None


def test_lower_scales_require_more_concrete_facts():
    few = _cand("A", facts=[{"kind": "proper_noun", "text": "X"},
                            {"kind": "period", "text": "long ago"}])
    _, deep = _run("zoom", [few], target="e3")      # district needs 2
    assert deep == []
    _, shallow = _run("zoom", [few], target="e1")   # region needs 1
    assert len(shallow) == 1


def test_minimum_is_configurable():
    few = _cand("A", facts=[{"kind": "period", "text": "long ago"}])
    _, none = _run("zoom", [few], target="e3")
    assert none == []
    cfg = OperatorConfig(min_concrete_facts={"district": 0})
    _, out = _run("zoom", [few], target="e3", config=cfg)
    assert len(out) == 1


def test_facts_and_summary_are_required():
    _, out = _run("expand", [_cand("A", facts=[]), _cand("B", summary=" "),
                             _cand("C", facts=[{"kind": "bad", "text": "t"}])])
    assert out == []


def test_unknown_axes_and_relations_are_filtered():
    _, out = _run("expand", [_cand(axes=["zzz"], relations=[
        {"type": "causes", "target": "e999"}, {"type": "bad", "target": "e1"},
        {"type": "opposes", "target": "e1"}])])
    e = out[0]["entity"]
    assert e["axes"] == ["geo"]  # inherited from target
    assert e["relations"] == [{"type": "opposes", "target": "e1"}]


def test_duplicate_names_are_dropped_and_n_is_capped():
    _, out = _run("expand", [_cand("Namee1"), _cand("X"), _cand("x"),
                             _cand("Y"), _cand("Z")], n=2)
    assert [c["entity"]["name"] for c in out] == ["X", "Y"]


def test_bad_responses_yield_no_candidates():
    g = _graph()
    for resp in ({}, {"candidates": "x"}, {"candidates": [1, None]}):
        r = OperatorRunner(FakeLLMBackend(lambda p, resp=resp: resp))
        assert r.run("expand", g, "e3", 2, brief=BRIEF, axes=AXES) == []


def test_invalid_requests():
    r = OperatorRunner(_backend())
    with pytest.raises(OperatorError):
        r.run("nope", _graph(), "e3")
    with pytest.raises(OperatorError):
        r.run("expand", _graph(), None)
    with pytest.raises(OperatorError):
        r.run("expand", _graph(), "e999")
    with pytest.raises(OperatorError):
        r.run("expand", _graph(), "e3", 0)


def test_prompt_uses_language_and_bounded_context():
    g = _graph()
    g["meta"]["language"] = "qq-LANG"
    for i in range(5, 60):
        g["entities"].append(make_entity(
            f"e{i}", "place", f"Sib{i}", "settlement", axes=["geo"],
            parent="e2", summary="s" * 500, provenance=PROV))
    backend = _backend(_cand())
    OperatorRunner(backend).run("expand", g, "e3", 1, brief=BRIEF, axes=AXES)
    prompt = backend.json_prompts[0]
    assert 'with code "qq-LANG"' in prompt
    assert "Sib10" in prompt and "Sib59" not in prompt
    assert len(prompt) < 8000


def test_wrappers_and_dispatch():
    g = _graph()
    b = _backend(_cand())
    assert zoom(b, g, "e3", 1, brief=BRIEF, axes=AXES)
    assert expand(b, g, "e3", 1, brief=BRIEF, axes=AXES)
    assert run_operator("premise", b, g, None, 1, brief=BRIEF, axes=AXES)


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


def test_prompts_require_concreteness_consistency_and_language():
    p = load_prompts()["common"]
    text = p["system"] + p["user"]
    assert "{language}" in text
    for needle in ("proper nouns", "numbers", "consistent", "neutral"):
        assert needle in text
