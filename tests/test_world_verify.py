"""Tests for the world verifiers and composite reward (fake backend only)."""

import re
from pathlib import Path

import pytest

from src.llm.fake import FakeLLMBackend
from src.world.graph import make_entity, new_graph
from src.world.operators import OperatorRunner
from src.world.reward import RewardVerifier, VERIFIERS, load_reward_config
from src.world.verify import (
    ContrastProvider, LLMJudge, embedding_similarity, load_language_rules,
    ngram_similarity, verify_consistency, verify_genericity, verify_novelty,
    verify_objectivity, verify_provenance, verify_specificity,
)

CONFIG = Path(__file__).resolve().parent.parent / "config"
RULES = load_language_rules()
CFG = load_reward_config()
PROV = {"statement_ids": ["s1"], "derived_from": [], "reason": ""}
BRIEF = {"statements": [{"id": "s1", "text": "alpha"}]}


def graph(lang="en"):
    g = new_graph(lang)
    g["entities"] = [
        make_entity("e1", "place", "Root", "world", summary="root",
                    provenance=PROV),
        make_entity("e2", "place", "Mid", "region", parent="e1",
                    summary="mid", provenance=PROV,
                    facts=[{"kind": "period", "text": "founded in year 300"},
                           {"kind": "number", "text": "Population: 4200"}]),
    ]
    return g


def cand(name="Harbor Ledger Office", summary=None, facts=None, prov=None,
         rels=None, parent="e1", scale="region", op="expand", target="e2"):
    entity = make_entity(
        "e9", "institution", name, scale, parent=parent,
        relations=rels or [],
        summary=summary or "The office records tonnage at pier 7 and sets "
                           "the berth fee at 12 marks.",
        facts=[{**f, "provenance": dict(PROV)} for f in (
            facts if facts is not None else [
                {"kind": "proper_noun", "text": "Tern Pier"},
                {"kind": "number", "text": "berth fee 12 marks"},
                {"kind": "object", "text": "brass tally board"}])],
        provenance=prov or dict(PROV))
    return {"operator": op, "target": target, "entity": entity}


# ---------------------------------------------------------------- genericity

CONTRAST = {"name": "Central Guild", "summary":
            "The guild is an important organization that supports various "
            "activities of the community in many ways.",
            "facts": ["Founded long ago", "Leader is wise"]}


def test_similarity_is_deterministic_and_handles_cjk():
    assert ngram_similarity("同じ文章です。", "同じ文章です。") == 1.0
    assert ngram_similarity("港の帳簿を管理する役所", "山脈を越える鉄索の保守") < 0.1
    assert ngram_similarity("abc", "abc") == ngram_similarity("abc", "abc")


def test_genericity_penalizes_near_copy_of_contrast_and_not_distinct():
    copy_ = cand(name="Central Guild", summary=CONTRAST["summary"],
                 facts=[{"kind": "other", "text": t} for t in CONTRAST["facts"]])
    r = verify_genericity(copy_, [CONTRAST])
    assert r.score < 0.1
    assert r.deductions and r.deductions[0].code == "resembles_prior"
    distinct = verify_genericity(cand(), [CONTRAST])
    assert distinct.score > 0.9 and not distinct.deductions


def test_genericity_japanese_and_skip_without_contrast():
    c = {"name": "中央組合", "summary": "様々な活動を支える重要な組織である。", "facts": []}
    same = cand(name="中央組合", summary=c["summary"], facts=[])
    assert verify_genericity(same, [c]).score < 0.2
    other = cand(name="潮見台帳所", summary="入港した船の積荷量を台帳に記し、係留料を定める。")
    assert verify_genericity(other, [c]).score > 0.9
    assert verify_genericity(same, []).skipped


def test_embedding_similarity_is_pluggable():
    sim = embedding_similarity(lambda t: [1.0, 0.0] if "a" in t else [0.0, 1.0])
    assert sim("a", "ab") == 1.0 and sim("a", "b") == 0.0
    r = verify_genericity(cand(), [CONTRAST], similarity=lambda a, b: 1.0)
    assert r.score == 0.0


def contrast_runner(counter):
    def respond(prompt):
        counter.append(prompt)
        return {"candidates": [{
            "type": "institution", "name": "Central Guild", "axes": [],
            "summary": CONTRAST["summary"],
            "facts": [{"kind": "proper_noun", "text": "Guild Hall"},
                      {"kind": "number", "text": "50 members"},
                      {"kind": "object", "text": "oak table"}],
            "statement_ids": ["x"], "derived_from": [], "reason": ""}]}
    return OperatorRunner(FakeLLMBackend(respond))


def test_contrast_provider_strips_input_and_caches(tmp_path):
    calls = []
    g = graph()
    g["entities"][1]["summary"] = "UNIQUE-WORLD-MARKER"
    cp = ContrastProvider(contrast_runner(calls), tmp_path, n=1)
    first = cp.get("expand", g, "e2")
    assert first and len(calls) == 1
    assert "UNIQUE-WORLD-MARKER" not in calls[0] and "alpha" not in calls[0]
    cp.get("expand", g, "e2")
    assert len(calls) == 1  # memory cache
    cp2 = ContrastProvider(contrast_runner(calls), tmp_path, n=1)
    assert cp2.get("expand", g, "e2") == first and len(calls) == 1  # file cache
    assert (tmp_path / "world" / "contrasts.json").exists()
    cp2.get("zoom", g, "e2")
    assert len(calls) == 2  # other slot


def test_reward_genericity_uses_contrast_provider():
    calls = []
    rv = RewardVerifier(contrasts=ContrastProvider(contrast_runner(calls), n=1))
    g = graph()
    dull = cand(name="Central Guild", summary=CONTRAST["summary"],
                facts=[{"kind": "proper_noun", "text": "Guild Hall"},
                       {"kind": "number", "text": "50 members"},
                       {"kind": "object", "text": "oak table"}])
    good = rv.verify(g, cand())
    bad = rv.verify(g, dull)
    assert good.scores["genericity"] > 0.9
    assert bad.scores["genericity"] < 0.2
    assert "genericity" in bad.failed


# --------------------------------------------------------------- provenance

def test_provenance_good_and_bad():
    g = graph()
    assert verify_provenance(cand(), g, BRIEF).score == 1.0
    ok = cand(prov={"statement_ids": [], "derived_from": ["e2"], "reason": "because"})
    assert verify_provenance(ok, g, BRIEF).score == 1.0
    none = cand(prov={"statement_ids": [], "derived_from": [], "reason": ""})
    assert verify_provenance(none, g, BRIEF).score == 0.0
    noreason = cand(prov={"statement_ids": ["s1"], "derived_from": ["e2"], "reason": ""})
    r = verify_provenance(noreason, g, BRIEF)
    assert r.score < 1 and r.deductions[0].code == "missing_reason"
    bad = cand(prov={"statement_ids": ["zz"], "derived_from": ["e77"], "reason": "x"})
    codes = {d.field for d in verify_provenance(bad, g, BRIEF).deductions}
    assert codes == {"provenance.statement_ids", "provenance.derived_from"}


# -------------------------------------------------------------- specificity

def test_specificity_english_good_vs_vague():
    vague = cand(summary="A rich and complex place with various important "
                         "and diverse traditions.",
                 facts=[{"kind": "other", "text": "many unique things"}])
    good = verify_specificity(cand(), "en", RULES, CFG["specificity"])
    bad = verify_specificity(vague, "en", RULES, CFG["specificity"])
    assert good.score > 0.9 and bad.score < 0.5
    assert {"abstract_density", "kind_coverage"} <= {d.code for d in bad.deductions}


def test_specificity_japanese_good_vs_vague():
    vague = cand(summary="様々な伝統を持つ、重要で複雑で豊かな場所である。",
                 facts=[{"kind": "other", "text": "多様な文化"}])
    good = cand(summary="潮見台帳所は入港船の積荷量を記録し、係留料を12マルクと定める。",
                facts=[{"kind": "proper_noun", "text": "潮見台帳所"},
                       {"kind": "number", "text": "係留料12マルク"},
                       {"kind": "object", "text": "真鍮の計量板"}])
    assert verify_specificity(good, "ja", RULES, CFG["specificity"]).score > 0.9
    assert verify_specificity(vague, "ja", RULES, CFG["specificity"]).score < 0.5


def test_specificity_unknown_language_uses_structure_only():
    vague_words = cand(summary="rich complex various important")
    r = verify_specificity(vague_words, "zz", RULES, CFG["specificity"])
    assert all(d.code != "abstract_density" for d in r.deductions)
    empty = cand(facts=[], summary="no detail")
    assert verify_specificity(empty, "zz", RULES, CFG["specificity"]).score < 0.5


# -------------------------------------------------------------- consistency

def test_consistency_good_and_bad():
    g = graph()
    p = CFG["consistency"]
    assert verify_consistency(cand(), g, params=p).score == 1.0
    # effect before cause: candidate causes e2 (year 300) but starts at 900
    late = cand(facts=[{"kind": "period", "text": "from year 900"},
                       {"kind": "proper_noun", "text": "X"}],
                rels=[{"type": "causes", "target": "e2"}])
    r = verify_consistency(late, g, params=p)
    assert r.score < 1 and r.deductions[0].code == "temporal_order"
    early = cand(facts=[{"kind": "period", "text": "from year 100"},
                        {"kind": "proper_noun", "text": "X"}],
                 rels=[{"type": "causes", "target": "e2"}])
    assert verify_consistency(early, g, params=p).score == 1.0
    # same label, two values, in one entity
    twice = cand(facts=[{"kind": "number", "text": "Berths: 12"},
                        {"kind": "number", "text": "Berths: 20"}])
    assert verify_consistency(twice, g, params=p).deductions[0].code == "number_conflict"
    # same name as existing entity with a different value of a label
    same = cand(name="Mid", facts=[{"kind": "number", "text": "Population: 9000"}])
    assert any(d.code == "number_conflict"
               for d in verify_consistency(same, g, params=p).deductions)
    # contradictory relations
    rel = cand(rels=[{"type": "opposes", "target": "e2"},
                     {"type": "part_of", "target": "e2"}])
    assert any(d.code == "relation_conflict"
               for d in verify_consistency(rel, g, params=p).deductions)
    # structural error: parent does not exist
    broken = cand(parent="e404")
    assert any(d.code == "graph_invalid"
               for d in verify_consistency(broken, g, params=p).deductions)


def test_consistency_location_conflict():
    g = graph()
    g["entities"].append(make_entity("e3", "place", "Far", "region", parent="e1",
                                     provenance=PROV))
    g["entities"].append(make_entity("e4", "place", "Deep", "settlement",
                                     parent="e3", provenance=PROV))
    c = cand(parent="e2", scale="settlement",
             rels=[{"type": "located_in", "target": "e4"}])
    r = verify_consistency(c, g, params=CFG["consistency"])
    assert any(d.code == "location_conflict" for d in r.deductions)
    ok = cand(parent="e2", scale="settlement",
              rels=[{"type": "located_in", "target": "e1"}])
    assert verify_consistency(ok, g, params=CFG["consistency"]).score == 1.0


# -------------------------------------------------------------- objectivity

def test_objectivity_english():
    p = CFG["objectivity"]
    good = cand(summary="The office records tonnage and sets the berth fee.")
    bad = cand(summary='"Welcome!" said the clerk. I think you will love the '
                       "unforgettable harbor. Isn't it grand?")
    assert verify_objectivity(good, "en", RULES, p).score == 1.0
    r = verify_objectivity(bad, "en", RULES, p)
    assert r.score < 0.3
    assert {"quotation", "first_person", "second_person", "flourish",
            "exclamation", "question"} <= {d.code for d in r.deductions}


def test_objectivity_japanese_and_unknown_language():
    p = CFG["objectivity"]
    good = cand(summary="台帳所は入港船の積荷量を記録し、係留料を定める。")
    bad = cand(summary="「ようこそ！」と書記は言った。私はあなたにまさに壮大な港を見せたい。")
    assert verify_objectivity(good, "ja", RULES, p).score == 1.0
    assert verify_objectivity(bad, "ja", RULES, p).score < 0.3
    # unknown language: only script-independent markers apply
    r = verify_objectivity(bad, "zz", RULES, p)
    assert {d.code for d in r.deductions} == {"quotation", "exclamation"}


def _codes(summary, lang):
    return {d.code for d in verify_objectivity(
        cand(summary=summary), lang, RULES, CFG["objectivity"]).deductions}


@pytest.mark.parametrize("text", [
    "私有地は個人が所有する土地であり、私立の施設も含む。",
    "君主制では君主が最終的な決定権を持つ。諸君という呼称は用いない。",
    "公僕は役所に勤める者を指し、下僕とは区別される。",
    "暴君は失政を重ね、名君は税を軽くした。",
])
def test_japanese_compounds_do_not_trigger_person_markers(text):
    assert not _codes(text, "ja") & {"first_person", "second_person"}


def test_japanese_person_voice_still_detected():
    assert "first_person" in _codes("私はこの制度を好ましいと考える。", "ja")
    assert "first_person" in _codes("僕たちの町は広い。", "ja")
    assert "second_person" in _codes("君は港を見たことがあるか。", "ja")
    assert "second_person" in _codes("あなたはこの規則に従う。", "ja")


@pytest.mark.parametrize("text,lang", [
    ("「水税」と呼ばれる制度が水の使用量に応じて課される。", "ja"),
    ("「潮見台帳」は港の記録簿の名称である。", "ja"),
    ("\u201cTidegate\u201d is the name of the lock office.", "en"),
    ('The "Ledger" is kept at the pier.', "en"),
])
def test_quoted_terms_are_not_speech(text, lang):
    assert "quotation" not in _codes(text, lang)


@pytest.mark.parametrize("text,lang", [
    ("「来るな！」と叫んだ。", "ja"),
    ("「来るな」と叫んだ。", "ja"),
    ("「これは規則である。」", "ja"),
    ('"Leave now," she said.', "en"),
    ('She said, "Leave now".', "en"),
    ('"Leave now!"', "en"),
])
def test_quoted_utterances_are_speech(text, lang):
    assert "quotation" in _codes(text, lang)


def test_concrete_senses_are_not_abstract_words():
    s = "The valley is deep, a rich seam runs through a complex of 4 halls."
    r = verify_specificity(cand(summary=s), "en", RULES, CFG["specificity"])
    assert all(d.code != "abstract_density" for d in r.deductions)
    j = cand(summary="深い井戸は豊かな水脈に達する。")
    assert all(d.code != "abstract_density" for d in verify_specificity(
        j, "ja", RULES, CFG["specificity"]).deductions)


# ------------------------------------------------------------------ novelty

def test_novelty_good_and_bad():
    g = graph()
    g["entities"].append(make_entity(
        "e5", "institution", "Harbor Ledger Office", "region", parent="e1",
        summary=cand()["entity"]["summary"], provenance=PROV,
        facts=cand()["entity"]["facts"]))
    dup = cand(name="Harbor Ledger Office 2")
    r = verify_novelty(dup, g, params=CFG["novelty"])
    assert r.score < 0.3 and r.deductions[0].detail["entity"] == "e5"
    fresh = cand(name="Kiln Registry",
                 summary="Registers kiln firings and allots clay quotas.")
    assert verify_novelty(fresh, g, params=CFG["novelty"]).score > 0.9
    jp = g
    jp["entities"].append(make_entity("e6", "place", "潮見台帳所", "region",
                                      parent="e1", summary="港の帳簿を管理する役所である。",
                                      provenance=PROV))
    c = cand(name="別名", summary="港の帳簿を管理する役所である。", facts=[])
    assert verify_novelty(c, jp, params=CFG["novelty"]).score < 0.5


# ------------------------------------------------------------------- reward

def test_reward_structure_weights_and_storage():
    g = graph()
    rv = RewardVerifier()
    c = cand()
    res = rv.verify(g, c, brief=BRIEF)
    assert res.skipped == ["genericity"]
    assert set(res.scores) == set(VERIFIERS) - {"genericity"}
    assert 0.0 <= res.reward <= 1.0 and res.passed and not res.failed
    assert c["entity"]["scores"]["reward"] == round(res.reward, 4)
    assert c["entity"]["scores"]["novelty"] == round(res.scores["novelty"], 4)

    bad = cand(summary='"Wow!" I said, you rich various complex thing.',
               facts=[{"kind": "other", "text": "stuff"}],
               prov={"statement_ids": [], "derived_from": [], "reason": ""})
    r2 = rv.verify(g, bad, brief=BRIEF, store=False)
    assert not r2.passed and r2.reward < res.reward
    assert {"provenance", "specificity", "objectivity"} <= set(r2.failed)
    assert bad["entity"]["scores"] == {}
    for d in r2.to_dict()["deductions"]:
        assert set(d) == {"verifier", "field", "code", "message", "penalty", "detail"}
        assert d["verifier"] in VERIFIERS and d["field"] and d["message"]
    assert r2.deductions_for("provenance")


def test_reward_weights_are_configurable():
    g = graph()
    c = cand(summary='"Wow!" I said.')  # only objectivity is hurt
    base = RewardVerifier().verify(g, c, brief=BRIEF, store=False)
    only_obj = RewardVerifier(load_reward_config(overrides={
        "weights": {n: (1.0 if n == "objectivity" else 0.0) for n in VERIFIERS}}))
    r = only_obj.verify(g, c, brief=BRIEF, store=False)
    assert r.reward == pytest.approx(base.scores["objectivity"])
    assert r.reward < base.reward
    assert not base.passed and base.failed == ["objectivity"]
    lenient = RewardVerifier(load_reward_config(overrides={
        "thresholds": {"objectivity": 0.0, "total": 0.0}}))
    assert lenient.verify(g, c, brief=BRIEF, store=False).passed
    strict = RewardVerifier(load_reward_config(overrides={
        "thresholds": {"objectivity": 0.0, "total": 0.99}}))
    assert not strict.verify(g, c, brief=BRIEF, store=False).passed


def test_llm_judges_off_by_default_and_pluggable():
    g = graph()
    backend = FakeLLMBackend({"score": 0.2, "issues": [
        {"field": "summary", "why": "contradicts e2"}]})
    rv = RewardVerifier(judge=LLMJudge(backend))
    rv.verify(g, cand(), brief=BRIEF)
    assert backend.json_prompts == []  # not enabled by config
    on = RewardVerifier(
        load_reward_config(overrides={"llm_judges": ["consistency"]}),
        judge=LLMJudge(backend))
    res = on.verify(g, cand(), brief=BRIEF, store=False)
    assert len(backend.json_prompts) == 1
    assert res.scores["consistency"] == pytest.approx(0.2)
    d = res.deductions_for("consistency")[0]
    assert d.code == "llm_judge" and d.field == "summary"


# ------------------------------------------------------------- prompt/config

BANNED_TERMS = [
    "protagonist", "主人公", "plot", "プロット", "chapter", "章", "novel",
    "小説", "story", "物語", "dialogue", "台詞", "character arc", "future",
    "未来", "past", "過去", "fantasy", "ファンタジー", "sci-fi",
    "science fiction", "SF", "medieval", "中世", "magic", "魔法", "kingdom",
    "王国", "city", "都市", "robot", "ロボット", "cyberpunk",
]


@pytest.mark.parametrize("rel", [
    "prompts/world/verifiers.yaml", "world/reward.yaml"])
def test_verifier_prompts_and_config_have_no_story_or_genre_terms(rel):
    raw = (CONFIG / rel).read_text("utf-8").lower()
    for t in BANNED_TERMS:
        if t.isascii():
            assert not re.search(r"\b" + re.escape(t.lower()) + r"\b", raw), t
        else:
            assert t not in raw, t


def test_language_rules_are_keyed_by_language_with_default():
    assert "default" in RULES and {"ja", "en"} <= set(RULES)
    for lang in ("ja", "en"):
        assert RULES[lang]["abstract_words"]
