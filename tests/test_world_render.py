"""Tests for the world reference renderer (synthetic worlds, no LLM)."""

import json
import re
from pathlib import Path

import pytest
import yaml

from src.world.graph import SCALES, dumps, make_entity, new_graph
from src.world.render import (
    load_labels, render_world_package,
)

CONFIG = Path(__file__).resolve().parent.parent / "config"

BRIEF = {"statements": [
    {"id": "s1", "text": "alpha", "quote": "alpha quoted text"},
    {"id": "s2", "text": "beta", "quote": "beta quoted text"}]}
AXES = [
    {"id": "a1", "name": "Axis One", "meaning": "first", "weight": 0.7,
     "grounds": {"statement_ids": ["s1"], "reason": "stated"},
     "origin": "catalog"},
    {"id": "a2", "name": "Axis | Two", "meaning": "second", "weight": 0.3,
     "grounds": {"statement_ids": [], "reason": "needed"},
     "origin": "added"}]


def _prov(sids=("s1",), src=(), reason=""):
    return {"statement_ids": list(sids), "derived_from": list(src),
            "reason": reason}


def _facts(*pairs):
    return [{"kind": k, "text": t, "provenance": _prov()} for k, t in pairs]


def build_graph(language):
    g = new_graph(language)
    E = make_entity
    g["entities"] = [
        E("e1", "place", "Root [World]", "world", axes=["a1"],
          summary="The whole. It has parts.", provenance=_prov(),
          facts=_facts(("proper_noun", "Root Name")),
          scores={"reward": 0.9, "genericity": 0.8}),
        E("e2", "place", "Region A", "region", axes=["a1"], parent="e1",
          summary="A region.", provenance=_prov(("s2",)),
          facts=_facts(("number", "12 wards")),
          scores={"reward": 0.5, "genericity": 0.6}),
        E("e3", "place", "Settlement B", "settlement", axes=["a2"],
          parent="e2", summary="A settlement.", provenance=_prov(),
          facts=_facts(("proper_noun", "Root Name"), ("object", "a seal"))),
        E("e4", "place", "District C", "district", parent="e3",
          summary="A district.", provenance=_prov(("s1", "s2"))),
        E("e5", "institution", "Site D", "site", parent="e4",
          summary="A site.", provenance=_prov(),
          relations=[{"type": "produces", "target": "e8"}]),
        E("e6", "object", "Detail E", "detail", parent="e5",
          summary="A detail.", provenance=_prov(src=("e5",), reason="why"),
          relations=[{"type": "part_of", "target": "e5"}]),
        E("e7", "event", "Event F", "region", parent="e1",
          summary="An event.", provenance=_prov(),
          facts=_facts(("period", "term 40")),
          relations=[{"type": "affects", "target": "e3"}]),
        E("e8", "document", "Document G", "site", parent="e4",
          summary="A document.", provenance=_prov(),
          facts=_facts(("expression", "wording x"), ("period", "term 41"),
                       ("proper_noun", "Issuer Z")),
          relations=[{"type": "related_to", "target": "e3"}]),
    ]
    return g


PREFS = [
    {"type": "candidate", "id": "i1.r0.c0", "decision": "rejected",
     "candidate": {"name": "Generic One", "summary": "bland text"},
     "result": {"scores": {"genericity": 0.1}, "failed": ["genericity"],
                "deductions": [{"verifier": "genericity", "message": "too bland"}]}},
    {"type": "candidate", "id": "i1.r0.c1", "decision": "accepted",
     "candidate": {"name": "Fine"}, "result": {"scores": {}, "failed": []}},
    {"type": "iteration", "iteration": 1},
]


def make_package(root, language):
    (root / "input").mkdir(parents=True)
    (root / "world").mkdir()
    (root / "input" / "input_brief.json").write_text(json.dumps(BRIEF))
    (root / "world" / "world_axes.json").write_text(json.dumps({"axes": AXES}))
    (root / "world" / "graph.json").write_text(dumps(build_graph(language)))
    (root / "world" / "preferences.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in PREFS))
    (root / "run_manifest.json").write_text(json.dumps({"world_explore": {
        "iteration": 4, "stop_reason": "max_iterations",
        "counters": {"generation_calls": 9, "accepted": 3, "rejected": 1},
        "elapsed_seconds": 1.234}}))
    return root


def snapshot(final):
    return {str(p.relative_to(final)): p.read_bytes()
            for p in sorted(final.rglob("*")) if p.is_file()}


LINK = re.compile(r"(?<!\\)\]\(([^)\s]+)\)")


def slugs(text):
    out = set()
    for line in text.splitlines():
        m = re.match(r"#+\s+(.*)", line)
        if m:
            out.add(re.sub(r"[^\w\- ]", "", m.group(1).lower())
                    .replace(" ", "-"))
    return out


@pytest.mark.parametrize("language", ["ja", "en", "xx"])
def test_all_files_generated_deterministically(tmp_path, language):
    a = make_package(tmp_path / "a", language)
    b = make_package(tmp_path / "b", language)
    render_world_package(a)
    render_world_package(b)
    render_world_package(a)  # re-render over existing output
    snap = snapshot(a / "final")
    assert snap == snapshot(b / "final")
    names = set(snap)
    assert {"world.json", "world_report.md", "world_bible/README.md",
            "world_bible/glossary.md", "world_bible/timeline.md",
            "world_bible/documents.md"} <= names
    assert {f"world_bible/scales/{s}.md" for s in SCALES} <= names
    assert {f"world_bible/entities/e{i}.md" for i in range(1, 9)} <= names


def test_world_json_is_the_model_plus_axes_and_run(tmp_path):
    root = make_package(tmp_path, "en")
    render_world_package(root)
    data = json.loads((root / "final" / "world.json").read_text("utf-8"))
    assert data["meta"]["language"] == "en"
    assert [e["id"] for e in data["entities"]] == [f"e{i}" for i in range(1, 9)]
    assert data["axes"] == AXES
    assert data["run"]["stop_reason"] == "max_iterations"
    assert data["run"]["iterations"] == 4
    assert "elapsed_seconds" not in json.dumps(data)


def test_every_markdown_link_resolves(tmp_path):
    for lang in ("ja", "en"):
        root = make_package(tmp_path / lang, lang)
        render_world_package(root)
        final = root / "final"
        total = 0
        for md in final.rglob("*.md"):
            text = md.read_text("utf-8")
            for target in LINK.findall(text):
                total += 1
                path, _, anchor = target.partition("#")
                dest = (md.parent / path).resolve() if path else md
                assert dest.is_file(), f"{md}: {target}"
                if anchor:
                    assert anchor in slugs(dest.read_text("utf-8")), target
        assert total > 30


def test_content_of_pages(tmp_path):
    root = make_package(tmp_path, "en")
    render_world_package(root)
    bible = root / "final" / "world_bible"
    readme = (bible / "README.md").read_text("utf-8")
    assert "The whole. It has parts." in readme
    assert "Axis One" in readme and "0.70" in readme
    assert "alpha quoted text" in readme
    ent = (bible / "entities" / "e6.md").read_text("utf-8")
    assert "[Site D](e5.md)" in ent  # parent, relation and derived_from
    assert "why" in ent
    e2 = (bible / "entities" / "e2.md").read_text("utf-8")
    assert "beta quoted text" in e2 and "[number] 12 wards" in e2
    assert "[Settlement B](e3.md)" in e2  # children
    root_page = (bible / "entities" / "e1.md").read_text("utf-8")
    assert "Root \\[World\\]" in root_page.replace("# ", "") or "Root [World]" in root_page
    gloss = (bible / "glossary.md").read_text("utf-8")
    assert gloss.count("**Root Name**") == 1
    assert "e1.md" in gloss.split("**Root Name**")[1].splitlines()[0]
    assert "e3.md" in gloss.split("**Root Name**")[1].splitlines()[0]
    assert "**Issuer Z**" in gloss
    tl = (bible / "timeline.md").read_text("utf-8")
    assert "term 40" in tl and "entities/e3.md" in tl.split("Event F")[1]
    docs = (bible / "documents.md").read_text("utf-8")
    assert "wording x" in docs and "Site D" in docs and "term 41" in docs
    scale = (bible / "scales" / "region.md").read_text("utf-8")
    assert "world.md" in scale and "settlement.md" in scale


def test_report_contents(tmp_path):
    root = make_package(tmp_path, "en")
    render_world_package(root)
    rep = (root / "final" / "world_report.md").read_text("utf-8")
    assert "iteration budget reached" in rep
    assert "| Axis \\| Two | 0.30 | 30.0% | 1 | 33.3% |" in rep
    assert "| Region | 2 |" in rep
    assert "reward (total)" in rep and "genericity" in rep
    assert "Generic One" in rep and "too bland" in rep
    assert "Fine" not in rep


def test_labels_fall_back_to_english_and_language_is_used(tmp_path):
    assert load_labels("zz")["scales"]["region"] == "Region"
    assert load_labels("ja-JP")["scales"]["region"] == "地域"
    ja = make_package(tmp_path / "ja", "ja")
    render_world_package(ja)
    text = (ja / "final" / "world_bible" / "README.md").read_text("utf-8")
    assert "世界設定資料" in text and "目次" in text
    en = make_package(tmp_path / "en", "en")
    render_world_package(en)
    assert "Contents" in (en / "final/world_bible/README.md").read_text("utf-8")


def test_invalid_graph_is_rejected(tmp_path):
    root = make_package(tmp_path, "en")
    (root / "world" / "graph.json").write_text("{}")
    with pytest.raises(Exception):
        render_world_package(root)


BANNED_TERMS = [
    "protagonist", "主人公", "plot", "プロット", "chapter", "章", "novel",
    "小説", "story", "物語", "dialogue", "台詞", "character arc", "future",
    "未来", "past", "過去", "fantasy", "ファンタジー", "sci-fi",
    "science fiction", "SF", "medieval", "中世", "magic", "魔法", "kingdom",
    "王国", "city", "都市", "robot", "ロボット", "cyberpunk",
]


def test_labels_have_no_story_or_genre_terms():
    data = yaml.safe_load(
        (CONFIG / "world" / "render_labels.yaml").read_text("utf-8"))
    assert {"ja", "en"} <= set(data)
    raw = (CONFIG / "world" / "render_labels.yaml").read_text("utf-8").lower()
    for t in BANNED_TERMS:
        if t.isascii():
            assert not re.search(r"\b" + re.escape(t.lower()) + r"\b", raw), t
        else:
            assert t not in raw, t
    assert set(data["ja"]) == set(data["en"])


def test_engine_renders_by_default_and_can_be_disabled(tmp_path):
    from tests.test_world_explore import RAW, cfg, make_backend
    from src.world.explore import run_world_engine

    c = cfg(budget={"max_iterations": 3})
    r = run_world_engine(RAW, None, tmp_path / "on", make_backend(),
                         {"max_iterations": 3}, 5, config=c)
    final = tmp_path / "on" / "final"
    assert (final / "world.json").exists()
    assert (final / "world_bible" / "README.md").exists()
    data = json.loads((final / "world.json").read_text("utf-8"))
    assert data["run"]["iterations"] == r.iterations
    run_world_engine(RAW, None, tmp_path / "off", make_backend(),
                     {"max_iterations": 2}, 5, config=c, render=False)
    assert not (tmp_path / "off" / "final").exists()
