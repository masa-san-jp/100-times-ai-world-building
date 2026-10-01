"""Tests for the entity graph: validation, local context, persistence."""

import copy
import json

import pytest

from src.checkpoint_manager import CheckpointManager
from src.validation import validate_artifact
from src.world.graph import (
    GraphError, GraphStore, SCALES, canonical, dumps, guess_language,
    local_context, make_entity, new_graph, next_entity_id, validate_graph,
)

BRIEF = {"statements": [{"id": "s1", "text": "t", "quote": "t"},
                        {"id": "s2", "text": "u", "quote": "u"}]}
AXES = [{"id": "geography"}, {"id": "economy"}]
PROV = {"statement_ids": ["s1"], "derived_from": [], "reason": ""}


def _ent(eid, scale="world", parent=None, **kw):
    kw.setdefault("provenance", PROV)
    kw.setdefault("axes", ["geography"])
    kw.setdefault("summary", f"summary {eid}")
    return make_entity(eid, "place", f"name {eid}", scale,
                       parent=parent, **kw)


def _graph():
    g = new_graph("en")
    g["entities"] = [
        _ent("e1"),
        _ent("e2", "region", "e1"),
        _ent("e3", "settlement", "e2"),
        _ent("e4", "settlement", "e2", relations=[
            {"type": "opposes", "target": "e3"}]),
    ]
    return g


def _errors(g):
    return validate_graph(g, AXES, BRIEF)


def test_valid_graph_has_no_errors():
    assert _errors(_graph()) == []
    assert validate_artifact("entity_graph", _graph()) == []


def test_entity_shape_is_canonical():
    e = _ent("e1")
    assert set(e) == {
        "id", "type", "name", "axes", "scale", "parent", "relations",
        "summary", "facts", "provenance", "scores"}
    assert list(new_graph("ja")["meta"]) == ["schema_version", "language"]


def _mutate(fn):
    g = _graph()
    fn(g)
    return _errors(g)


@pytest.mark.parametrize("fn,needle", [
    (lambda g: g["entities"][1].update(parent="nope"), "does not exist"),
    (lambda g: g["entities"][1].update(scale="world"), "above child"),
    (lambda g: g["entities"][2].update(scale="region"), "above child"),
    (lambda g: g["entities"][1].update(parent=None), "omit parent"),
    (lambda g: g["entities"][3]["relations"].append(
        {"type": "causes", "target": "zz"}), "relation target"),
    (lambda g: g["entities"][3]["relations"].append(
        {"type": "bogus", "target": "e1"}), "relation type"),
    (lambda g: g["entities"][0].update(axes=["nope"]), "unknown axis"),
    (lambda g: g["entities"][0]["provenance"].update(statement_ids=["s9"]),
     "unknown statement"),
    (lambda g: g["entities"][0].update(type="story"), "invalid type"),
    (lambda g: g["entities"][0].update(scale="galaxy"), "invalid scale"),
    (lambda g: g["entities"][0].update(name=""), "name is required"),
    (lambda g: g["entities"][1].update(id="e1"), "duplicate"),
    (lambda g: g["entities"][0].update(
        provenance={"statement_ids": [], "derived_from": [], "reason": ""}),
     "needs statement_ids"),
    (lambda g: g["entities"][1].update(provenance={
        "statement_ids": [], "derived_from": ["e1"], "reason": ""}),
     "requires a reason"),
    (lambda g: g["entities"][1].update(provenance={
        "statement_ids": [], "derived_from": ["zz"], "reason": "A so B"}),
     "unknown source"),
    (lambda g: g["entities"][0]["facts"].append(
        {"text": "x", "kind": "weird", "provenance": PROV}), "invalid kind"),
    (lambda g: g["entities"][0]["facts"].append(
        {"text": "x", "kind": "number",
         "provenance": {"statement_ids": ["s9"], "derived_from": [],
                        "reason": ""}}), "unknown statement"),
    (lambda g: g["meta"].update(language=""), "language"),
    (lambda g: g.update(entities="x"), "entities must be a list"),
])
def test_violations_are_detected(fn, needle):
    assert any(needle in e for e in _mutate(fn)), _mutate(fn)


def test_derived_entity_with_reason_is_valid():
    g = _graph()
    g["entities"].append(_ent("e5", "site", "e3", provenance={
        "statement_ids": [], "derived_from": ["e3"], "reason": "A so B"}))
    assert _errors(g) == []


def test_artifact_validator_reports_violations():
    g = _graph()
    g["entities"][1]["parent"] = "nope"
    assert validate_artifact("entity_graph", g)


def _big_graph(n):
    g = new_graph("en")
    g["entities"] = [_ent("e0")]
    for i in range(1, n + 1):
        g["entities"].append(_ent(
            f"e{i}", "region", "e0",
            summary="x" * 5000,
            relations=[{"type": "affects", "target": "e1"}] if i > 1 else [],
            facts=[{"text": "y" * 1000, "kind": "number",
                    "provenance": PROV} for _ in range(50)]))
    g["entities"][1]["relations"] = [
        {"type": "affects", "target": f"e{i}"} for i in range(2, n + 1)]
    return g


def test_local_context_is_bounded_independent_of_graph_size():
    sizes = []
    for n in (30, 600):
        ctx = local_context(_big_graph(n), "e1")
        sizes.append(len(json.dumps(ctx, ensure_ascii=False)))
        assert len(ctx["siblings"]) <= 6 and len(ctx["related"]) <= 10
        assert ctx["omitted"]["siblings"] == n - 1 - len(ctx["siblings"])
        for item in [ctx["entity"], ctx["parent"], *ctx["siblings"]]:
            assert len(item["summary"]) <= 240
            assert len(item["facts"]) <= 4
            assert all(len(f["text"]) <= 120 for f in item["facts"])
    assert abs(sizes[0] - sizes[1]) < 200  # only the omitted counts differ
    assert sizes[1] < 10000


def test_local_context_content_and_determinism():
    g = _graph()
    ctx = local_context(g, "e3")
    assert ctx["entity"]["id"] == "e3"
    assert ctx["parent"]["id"] == "e2"
    assert [s["id"] for s in ctx["siblings"]] == ["e4"]
    assert ctx["related"] == []  # e4 is already a sibling
    assert ctx["language"] == "en"
    assert ctx == local_context(copy.deepcopy(g), "e3")
    assert local_context(g, "e1")["parent"] is None
    with pytest.raises(KeyError):
        local_context(g, "missing")


def test_local_context_includes_incoming_and_outgoing_relations():
    g = _graph()
    g["entities"].append(_ent("e5", "region", "e1", relations=[
        {"type": "causes", "target": "e3"}]))
    ids = [r["id"] for r in local_context(g, "e3")["related"]]
    assert ids == ["e5"]
    ids = [r["id"] for r in local_context(g, "e5")["related"]]
    assert ids == ["e3"]


def test_serialization_is_deterministic():
    a = _graph()
    b = copy.deepcopy(a)
    b["entities"].reverse()
    b["entities"][0]["axes"] = ["geography"]
    assert dumps(a) == dumps(b)
    assert [e["id"] for e in canonical(b)["entities"]] == ["e1", "e2", "e3", "e4"]


def test_save_load_roundtrip(tmp_path):
    store = GraphStore(tmp_path, axes=AXES, brief=BRIEF)
    store.save(_graph())
    assert (tmp_path / "world" / "graph.json").exists()
    assert not list((tmp_path / "world").glob("*.tmp"))
    assert store.load() == canonical(_graph())


def test_save_refuses_invalid_graph_and_keeps_old_file(tmp_path):
    store = GraphStore(tmp_path)
    store.save(_graph())
    before = store.path.read_text(encoding="utf-8")
    bad = _graph()
    bad["entities"][1]["parent"] = "nope"
    with pytest.raises(GraphError):
        store.save(bad)
    assert store.path.read_text(encoding="utf-8") == before


def test_transaction_commits_and_rolls_back(tmp_path):
    store = GraphStore(tmp_path, axes=AXES, brief=BRIEF)
    with store.transaction("en") as g:
        g["entities"].append(_ent("e1"))
    assert [e["id"] for e in store.load()["entities"]] == ["e1"]

    with pytest.raises(RuntimeError):
        with store.transaction() as g:
            g["entities"].append(_ent("e2", "region", "e1"))
            raise RuntimeError("boom")
    assert [e["id"] for e in store.load()["entities"]] == ["e1"]

    with pytest.raises(GraphError):
        with store.transaction() as g:
            g["entities"].append(_ent("e2", "region", "missing"))
    assert [e["id"] for e in store.load()["entities"]] == ["e1"]


def test_resume_from_graph_file_and_checkpoint(tmp_path):
    cm = CheckpointManager(str(tmp_path / "checkpoints"))
    store = GraphStore(tmp_path, checkpoints=cm)
    with store.transaction("ja") as g:
        g["entities"].append(_ent("e1"))
    with store.transaction() as g:
        g["entities"].append(_ent("e2", "region", "e1"))

    # a fresh process resumes from graph.json
    resumed = GraphStore(tmp_path, checkpoints=CheckpointManager(
        str(tmp_path / "checkpoints"))).load_or_create("en")
    assert [e["id"] for e in resumed["entities"]] == ["e1", "e2"]
    assert resumed["meta"]["language"] == "ja"  # existing language kept
    assert next_entity_id(resumed) == "e3"

    # graph.json lost or corrupt: the checkpoint restores it
    store.path.write_text("{broken", encoding="utf-8")
    again = GraphStore(tmp_path, checkpoints=CheckpointManager(
        str(tmp_path / "checkpoints"))).load()
    assert [e["id"] for e in again["entities"]] == ["e1", "e2"]


def test_load_or_create_starts_empty(tmp_path):
    g = GraphStore(tmp_path).load_or_create("en")
    assert g["entities"] == [] and g["meta"]["language"] == "en"


@pytest.mark.parametrize("text,lang", [
    ("これは世界の説明です。", "ja"),
    ("A plain English sentence.", "en"),
    ("这是一个世界的描述。", "zh"),
    ("이것은 세계에 대한 설명입니다.", "ko"),
    ("Это описание мира.", "ru"),
    ("1234 ...", "und"),
])
def test_guess_language(text, lang):
    assert guess_language(text) == lang


def test_scale_order_constant():
    assert SCALES == ("world", "region", "settlement", "district", "site", "detail")
