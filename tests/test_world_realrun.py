"""Regression tests for the problems seen in the first real-model run (#43).

The synthetic Japanese input and candidates below only copy the *shape* of
what a real model produced (names that echo the input, facts that satisfy a
kind label without substance); no real content is stored in src/ or config/.
Fake backends only.
"""

import json

import pytest

from src.llm.fake import FakeLLMBackend
from src.world.axes import WorldAxesBuilder, load_catalog
from src.world.explore import (
    ExplorationLoop, candidate_pairs, evaluate_frontier, load_explore_config,
    pair_prior, scale_needs,
)
from src.world.graph import make_entity, new_graph
from src.world.input import InputBriefBuilder
from src.world.language import language_name, localized
from src.world.render import render_world_package
from src.world.reward import RewardVerifier
from src.world.textsim import echo_coverage
from src.world.verify import (
    LLMJudge, reference_text, verify_genericity, verify_specificity,
    load_language_rules,
)
from tests.test_world_explore import make_backend

RAW_JA = (
    "この塩の盆地では塩鉱業で暮らしが成り立っている。"
    "雨はほとんど降らず、水は古い地下水道から引いている。"
    "鉱夫組合と水守の家系が、地下水道の管理権をめぐって長く争っている。"
)
BRIEF_JA = {"statements": [
    {"id": "s1", "text": "この塩の盆地では塩鉱業で暮らしが成り立っている。",
     "quote": "この塩の盆地では塩鉱業で暮らしが成り立っている。"},
    {"id": "s2", "text": "雨はほとんど降らず、水は古い地下水道から引いている。",
     "quote": "雨はほとんど降らず、水は古い地下水道から引いている。"},
    {"id": "s3", "text": "鉱夫組合と水守の家系が、地下水道の管理権をめぐって長く争っている。",
     "quote": "鉱夫組合と水守の家系が、地下水道の管理権をめぐって長く争っている。"},
]}
PROV = {"statement_ids": ["s1"], "derived_from": [], "reason": ""}
RULES = load_language_rules()


def candidate(name, etype, summary, facts, operator="premise", target=None,
              scale="world", parent=None):
    entity = make_entity(
        "e1", etype, name, scale, parent=parent, summary=summary,
        facts=[{"kind": k, "text": t, "provenance": dict(PROV)}
               for k, t in facts],
        provenance=dict(PROV))
    return {"operator": operator, "target": target, "entity": entity}


# Thin candidates of the shape seen in the real run: every verifier used to
# give them a perfect score.
THIN = [
    candidate("塩の盆地", "place",
              "内陸にある塩の盆地で、塩鉱業が営まれている。雨はほとんど降らず、"
              "水は古い地下水道から引かれている。",
              [("proper_noun", "塩の盆地"), ("number", "約500平方キロメートル"),
               ("object", "古代地下水道"), ("expression", "塩鉱業")]),
    candidate("塩の盆地水道管理協議会", "institution",
              "塩の盆地の水道を管理する協議会であり、鉱夫組合と水守の家系が関わっている。",
              [("proper_noun", "水道管理協議会"), ("number", "3部門"),
               ("object", "古代地下水道")]),
    candidate("塩の盆地地下水道改修委員会", "institution",
              "地下水道の改修を担当する委員会で、管理権をめぐる対立の調整にあたる。",
              [("proper_noun", "地下水道改修委員会"), ("number", "3人委員"),
               ("object", "古代地下水道")]),
    candidate("塩の盆地砂漠", "place",
              "塩の盆地の周囲に広がる砂漠で、雨はほとんど降らない。",
              [("proper_noun", "砂漠"), ("number", "200平方キロメートル"),
               ("object", "塩鉱山")]),
]

# Candidates that bring their own names, quantities and mechanisms.
SPECIFIC = [
    candidate(
        "ハルメ堰守会", "institution",
        "二十七本の導水路に設けた堰の開閉を、堰守会が楡材の札の順番で割り当てる。"
        "札は毎年の暮れに焼き印を押し直し、順番への不服は三人の古老が最初の雨量記録と"
        "照合して裁く。",
        [("proper_noun", "ハルメ堰守会"),
         ("number", "年間降水量は平均41ミリ、札は一枚につき焼き印が三つ"),
         ("object", "楡材の開閉札"),
         ("period", "初代の札は第二期採掘許可の年に作られた")]),
    candidate(
        "ブラウ岩層採掘帳", "document",
        "坑口ごとの搬出量を、塩の純度の等級別に記した帳簿。一等塩一荷につき銅貨六枚の"
        "水利負担金が差し引かれ、帳簿は坑口の石櫃に二部ずつ保管される。",
        [("proper_noun", "ブラウ岩層採掘帳"),
         ("number", "水利負担金は一荷あたり銅貨6枚、搬出は日量約38トン"),
         ("object", "坑口の石櫃"),
         ("procedure", "月末に二部を突き合わせ、差異が2荷を超えれば封印する")]),
    candidate(
        "夜明け前の水量札", "institution",
        "夜明け前の一刻、導水路の分岐点で水量を測る慣行。測定の結果は黒板に白墨で書かれ、"
        "正午までに消される。測り手は水守の家系から一人、鉱夫組合から一人が立ち会う。",
        [("proper_noun", "ホルン分岐"), ("number", "分岐点は全部で14か所、水深は0.4メートル以下で渇水"),
         ("object", "白墨と黒板"), ("expression", "「札が立てば掘れ」")]),
]


def verifier(**over):
    from src.world.reward import load_reward_config
    return RewardVerifier(load_reward_config(overrides=over))


def verify(c, siblings=None, graph=None, rv=None):
    g = graph or new_graph("ja")
    return (rv or verifier()).verify(
        g, c, brief=BRIEF_JA, store=False, siblings=siblings)


# ------------------------------------------------------------- A: genericity

@pytest.mark.parametrize("i", range(len(THIN)))
def test_real_run_shaped_thin_candidates_fall_below_a_threshold(i):
    res = verify(THIN[i], siblings=THIN)
    assert not res.passed
    assert {"genericity", "specificity"} & set(res.failed), res.to_dict()
    assert res.reward < 0.8


def test_specific_candidates_pass():
    for c in SPECIFIC:
        res = verify(c, siblings=SPECIFIC)
        assert res.passed, res.to_dict()
        assert res.scores["genericity"] > 0.9
        assert res.scores["specificity"] > 0.9


def test_name_that_only_concatenates_input_words_is_detected():
    ref = reference_text(new_graph("ja"), None, BRIEF_JA)
    assert echo_coverage("塩の盆地地下水道改修委員会", ref) > 0.5
    assert echo_coverage("ハルメ堰守会", ref) < 0.2
    res = verify_genericity(THIN[2], [], reference=ref)
    assert "name_echoes_input" in {d.code for d in res.deductions}
    own = verify_genericity(SPECIFIC[0], [], reference=ref)
    assert own.score == 1.0 and not own.deductions


def test_restating_the_input_summary_is_penalized():
    ref = reference_text(new_graph("ja"), None, BRIEF_JA)
    res = verify_genericity(THIN[0], [], reference=ref)
    assert "restates_input" in {d.code for d in res.deductions}
    assert res.score < 0.5


def test_convergence_between_samples_of_one_slot_is_penalized():
    ref = reference_text(new_graph("en"), None, {"statements": []})
    shared = ("The office assigns every request to a clerk in the order it "
              "arrived and files a duplicate in the archive hall each season.")
    same = [candidate(f"Registry {n}", "institution", shared,
                      [("proper_noun", f"Registry {n}")]) for n in "ABC"]
    res = verify_genericity(same[0], [], siblings=same, reference=ref)
    assert res.score < 0.2
    assert res.deductions[0].code == "converges_with_samples"
    distinct = [
        candidate("Tern Pier Office", "institution",
                  "Berth fees at pier seven are set by the harbour clerk at "
                  "twelve marks per tide and posted on a brass board.",
                  [("proper_noun", "Tern Pier")]),
        candidate("Quarry Lamp Guild", "institution",
                  "Lamp oil for the quarry galleries is rationed by the "
                  "guild stewards, one flask for each shift of nine hours.",
                  [("proper_noun", "Quarry Lamp")]),
        candidate("Ninth Sluice", "place",
                  "A sluice gate that diverts spring melt into the lower "
                  "terraces, opened by the first frost warden of autumn.",
                  [("proper_noun", "Ninth Sluice")])]
    assert verify_genericity(
        distinct[0], [], siblings=distinct, reference=ref).score > 0.9


def test_wording_already_in_the_input_is_not_counted_as_convergence():
    # Samples that share only the input's own words converge on nothing new.
    ref = reference_text(new_graph("ja"), None, BRIEF_JA)
    res = verify_genericity(SPECIFIC[0], [], siblings=SPECIFIC, reference=ref)
    assert res.score == 1.0


def test_no_input_contrast_is_demoted_and_unrelated_topics_do_not_fire():
    contrast = [{"name": "星間連合委員会",
                 "summary": "銀河の諸勢力を調整する評議機関である。",
                 "facts": ["議席は九つ"]}]
    plain = verify_genericity(THIN[1], contrast)
    assert plain.score == 1.0  # a different topic: the prior cannot see it
    copy_ = {"entity": {"name": "中央組合", "summary": "様々な活動を支える重要な組織である。",
                        "facts": []}}
    c0 = [{"name": "中央組合", "summary": "様々な活動を支える重要な組織である。",
           "facts": []}]
    half = verify_genericity(copy_, c0, params={"contrast_weight": 0.5})
    full = verify_genericity(copy_, c0, params={"contrast_weight": 1.0})
    assert full.score < half.score <= 0.55


# ---------------------------------------------------------- B: fact substance

def spec(facts, reference=""):
    c = candidate("X", "institution", "要約", facts)
    return verify_specificity(c, "ja", RULES, {}, reference=reference)


def test_proper_noun_that_is_a_common_noun_or_input_words_is_hollow():
    ref = reference_text(new_graph("ja"), None, BRIEF_JA)
    codes = lambda r: {d.code for d in r.deductions}  # noqa: E731
    assert "generic_name" in codes(spec([("proper_noun", "砂漠")], ref))
    assert "echoes_input" in codes(spec([("proper_noun", "塩の盆地")], ref))
    assert "echoes_input" in codes(spec([("object", "地下水道")], ref))
    ok = spec([("proper_noun", "ハルメ堰守会"), ("number", "41ミリ"),
               ("object", "楡材の札")], ref)
    assert not {"generic_name", "echoes_input"} & codes(ok)


def test_english_proper_noun_needs_a_capital_and_not_input_words():
    rules = RULES
    ref = "The salt basin depends on an old conduit."
    c = candidate("X", "place", "s", [("proper_noun", "salt basin"),
                                      ("proper_noun", "Tern Pier"),
                                      ("proper_noun", "Conduit Salt Basin")])
    res = verify_specificity(c, "en", rules, {}, reference=ref)
    flagged = {d.field: d.code for d in res.deductions
               if d.code in ("generic_name", "echoes_input")}
    assert flagged == {"facts[0]": "echoes_input",
                       "facts[2]": "echoes_input"}  # Tern Pier is fine
    lower = candidate("X", "place", "s", [("proper_noun", "harbour")])
    assert "generic_name" in {d.code for d in verify_specificity(
        lower, "en", rules, {}).deductions}


def test_number_must_be_a_measurement_not_a_bare_count():
    def bare(text, lang="ja"):
        c = candidate("X", "place", "s", [("number", text)])
        return "bare_count" in {d.code for d in verify_specificity(
            c, lang, RULES, {}).deductions}
    assert bare("3部門") and bare("3人委員") and bare("50 members", "en")
    assert not bare("約500平方キロメートル") and not bare("年間降水量41ミリ")
    assert not bare("上流と下流の取水比は3:2") and not bare("占有率は12%")
    assert not bare("berth fee 12 marks", "en")


def test_hollow_facts_do_not_count_toward_kind_coverage():
    ref = reference_text(new_graph("ja"), None, BRIEF_JA)
    res = spec([("proper_noun", "砂漠"), ("number", "3部門"),
                ("object", "地下水道")], ref)
    assert res.score < 0.5
    kinds = [d for d in res.deductions if d.code == "kind_coverage"]
    assert kinds and kinds[0].detail["kinds"] == []


def test_llm_judge_sees_input_statements_and_is_pluggable():
    backend = FakeLLMBackend({"score": 0.3, "issues": [
        {"field": "facts[0]", "why": "hollow proper noun"}]})
    rv = verifier(llm_judges=["specificity"])
    rv.judge = LLMJudge(backend)
    res = rv.verify(new_graph("ja"), SPECIFIC[0], brief=BRIEF_JA, store=False)
    assert len(backend.json_prompts) == 1
    assert "塩の盆地" in backend.json_prompts[0]  # the input statements
    assert "hollow" in backend.json_prompts[0]
    assert any(d.code == "llm_judge" for d in res.deductions_for("specificity"))
    off = verifier()
    off.judge = LLMJudge(backend)
    off.verify(new_graph("ja"), SPECIFIC[0], brief=BRIEF_JA, store=False)
    assert len(backend.json_prompts) == 1  # off by default


def test_pipeline_enables_the_judge_for_real_backends_only(tmp_path):
    from src.pipeline import Pipeline
    p = Pipeline(output_dir=tmp_path, backend=make_backend(), seed=1,
                 budget={"max_iterations": 1})
    assert not p.judge_enabled() and p._build_verifier() is None  # fake
    p.backend_name = "ollama"
    assert p.judge_enabled()
    v = p._build_verifier()
    assert v.judge is not None and v.config["llm_judges"] == ["specificity"]
    p.judge_config = {"enabled": False}
    assert p._build_verifier() is None
    p.backend_name = "fake"
    p.judge_config = {"enabled": True, "criteria": ["objectivity"]}
    assert p._build_verifier().config["llm_judges"] == ["objectivity"]


# ---------------------------------------------------------------- C: depth

AXES = [{"id": "a1", "name": "One", "meaning": "first", "weight": 0.6},
        {"id": "a2", "name": "Two", "meaning": "second", "weight": 0.3},
        {"id": "a3", "name": "Three", "meaning": "third", "weight": 0.1}]
PROV_E = {"statement_ids": ["s1"], "derived_from": [], "reason": ""}


def world_only_graph():
    g = new_graph("en")
    g["entities"] = [make_entity("e1", "place", "Root", "world", axes=["a1"],
                                 summary="r", provenance=PROV_E)]
    return g


def test_zoom_outranks_other_operators_while_lower_scales_are_empty():
    cfg = load_explore_config()
    g = world_only_graph()
    needs = scale_needs(g, cfg)
    assert needs["region"] == 1.0 and needs["world"] == 0.5
    items = evaluate_frontier(g, AXES, cfg)
    pairs = candidate_pairs(items, cfg)
    priors = {(i["kind"], op): pair_prior(i, op, cfg) for i, op in pairs}
    assert priors[("unexpanded", "zoom")] > priors[("unexpanded", "expand")]
    gap_zoom = max(v for (k, op), v in priors.items()
                   if k == "axis_gap" and op == "zoom")
    gap_other = max(v for (k, op), v in priors.items()
                    if k == "axis_gap" and op != "zoom")
    assert gap_zoom > gap_other


def test_axis_gaps_are_filled_below_existing_entities_not_beside_the_root():
    cfg = load_explore_config()
    assert "expand" not in cfg["operators"]["axis_gap"]
    assert cfg["operators"]["axis_gap"][0] == "zoom"
    g = world_only_graph()
    g["entities"].append(make_entity(
        "e2", "place", "Mid", "region", axes=["a1"], parent="e1",
        summary="m", provenance=PROV_E))
    gaps = [i for i in evaluate_frontier(g, AXES, cfg)
            if i["kind"] == "axis_gap"]
    assert gaps and {i["target"] for i in gaps} == {"e2"}  # deepest, emptiest below


def test_no_zoom_below_the_finest_scale():
    cfg = load_explore_config()
    g = world_only_graph()
    g["entities"].append(make_entity(
        "e2", "place", "Leaf", "detail", axes=["a2"], parent="e1",
        summary="m", provenance=PROV_E))
    pairs = candidate_pairs(evaluate_frontier(g, AXES, cfg), cfg)
    assert not [1 for i, op in pairs if op == "zoom" and i["target"] == "e2"]


def test_loop_descends_below_world_scale_right_after_the_premise(tmp_path):
    from tests.test_world_explore import BRIEF as EBRIEF, AXES as EAXES
    c = load_explore_config()
    c["budget"]["max_iterations"] = 4
    c["coverage"]["enabled"] = False
    result = ExplorationLoop(
        make_backend(), tmp_path, EBRIEF, EAXES, seed=3, language="en",
        config=c).run()
    scales = [e["scale"] for e in result.graph["entities"]]
    assert scales[0] == "world"
    # premise, then the following iterations go down, not across
    assert any(s not in ("world", "region") for s in scales), scales
    assert scales.count("world") <= 2, scales
    log = [json.loads(l) for l in
           (tmp_path / "world" / "preferences.jsonl").read_text("utf-8").splitlines()]
    ops = [r["operator"] for r in log if r["type"] == "iteration"]
    assert ops[0] == "premise" and ops[1] == "zoom", ops


# -------------------------------------------------------------- D: language

def ja_backend():
    def respond(prompt):
        if prompt.startswith("SOURCE MATERIAL"):
            return {"statements": [
                {"text": "塩鉱業で暮らしが成り立っている",
                 "quote": "塩鉱業で暮らしが成り立っている"}],
                "open_questions": ["管理権の帰属は未定"], "constraints": []}
        return {"axes": [{"domain": "resources_economy",
                          "meaning": "塩と水の配分", "weight": 0.9,
                          "statement_ids": ["s1"]}]}
    return FakeLLMBackend(respond)


def test_prompts_ask_for_the_input_language_and_keep_quotes_verbatim(tmp_path):
    backend = ja_backend()
    built = InputBriefBuilder(backend, tmp_path / "in").build(RAW_JA)
    prompt = backend.json_prompts[0]
    assert prompt.startswith("SOURCE MATERIAL")
    assert 'Japanese (language code "ja")' in prompt
    assert "quote" in prompt and "never translated" in prompt
    assert built.brief["statements"][0]["text"].startswith("塩鉱業")
    axes_backend = ja_backend()
    WorldAxesBuilder(axes_backend, tmp_path / "w").build(built.brief)
    ap = axes_backend.json_prompts[0]
    assert "Japanese" in ap and 'code "ja"' in ap
    assert "resources_economy: 資源と経済" in ap  # localized catalog names
    explicit = InputBriefBuilder(ja_backend(), tmp_path / "in2", language="en")
    explicit.backend.json_responses = None
    explicit.build(RAW_JA)
    assert 'English (language code "en")' in explicit.backend.json_prompts[0]


def test_japanese_input_gives_japanese_axes_and_report(tmp_path):
    backend = ja_backend()
    result = None
    from src.world.explore import run_world_engine
    cfg = load_explore_config()
    cfg["budget"]["max_iterations"] = 0
    cfg["coverage"]["enabled"] = False
    result = run_world_engine(RAW_JA, None, tmp_path, backend,
                              {"max_iterations": 0}, 1, config=cfg)
    axes = json.loads(
        (tmp_path / "world" / "world_axes.json").read_text("utf-8"))["axes"]
    by = {a["id"]: a for a in axes}
    assert by["resources_economy"]["name"] == "資源と経済"
    assert by["resources_economy"]["meaning"] == "塩と水の配分"
    assert by["geography_climate"]["name"] == "地理と気候"
    assert by["geography_climate"]["meaning"] == "地形、場所、距離、天候、季節。"
    assert by["history"]["grounds"]["reason"].startswith("入力では触れられていない")
    for a in axes:
        assert not a["name"].isascii(), a
    assert result.graph["meta"]["language"] == "ja"
    # an entity so the report has content, then render
    g = json.loads((tmp_path / "world" / "graph.json").read_text("utf-8"))
    g["entities"] = [make_entity(
        "e1", "place", "ハルメ堰", "world", axes=["resources_economy"],
        summary="堰である。", provenance=PROV_E)]
    (tmp_path / "world" / "graph.json").write_text(
        json.dumps(g, ensure_ascii=False), encoding="utf-8")
    render_world_package(tmp_path)
    report = (tmp_path / "final" / "world_report.md").read_text("utf-8")
    readme = (tmp_path / "final" / "world_bible" / "README.md").read_text("utf-8")
    assert "資源と経済" in report and "資源と経済" in readme
    assert "Resources and economy" not in report + readme


def test_catalog_is_language_keyed_with_en_fallback():
    catalog = load_catalog()
    for d in catalog["domains"]:
        for key in ("name", "description"):
            assert {"en", "ja"} <= set(d[key]), d["id"]
    assert localized({"en": "Rain", "ja": "雨"}, "ja") == "雨"
    assert localized({"en": "Rain", "ja": "雨"}, "ko") == "Rain"  # fallback
    assert localized({"en": "Rain"}, None) == "Rain"
    assert localized("plain", "ja") == "plain"
    assert language_name("ja") == "Japanese" and language_name("xx") == "xx"


def test_english_input_keeps_english_catalog_names(tmp_path):
    brief = {"statements": [{"id": "s1", "text": "a salt basin"}],
             "open_questions": [], "constraints": []}
    res = WorldAxesBuilder(FakeLLMBackend({"axes": []}), tmp_path).build(brief)
    names = {a["id"]: a["name"] for a in res.axes}
    assert names["geography_climate"] == "Geography and climate"


# ------------------------------------------- malformed model output (#43 fix)

from src.world.coerce import fact_items, id_list, relation_items, text_of  # noqa: E402
from src.world.explore import STOP_REASONS, read_preference_log  # noqa: E402
from src.world.graph import FACT_KINDS, RELATION_TYPES  # noqa: E402
from src.world.operators import OperatorRunner  # noqa: E402


def test_id_lists_are_coerced_from_every_shape():
    assert id_list(["e1", "e2"]) == ["e1", "e2"]
    assert id_list([{"id": "e1"}, {"target": "e2"}, {"entity_id": "e3"}]) \
        == ["e1", "e2", "e3"]
    assert id_list("s1, s2;s3") == ["s1", "s2", "s3"]
    assert id_list([["s1", ["s2"]], 3, None, True, {"x": 1}]) == ["s1", "s2", "3"]
    assert id_list("s1") == ["s1"] and id_list(None) == [] and id_list({}) == []
    assert id_list("[s1, s1]") == ["s1"]


def test_facts_and_relations_are_coerced_or_dropped():
    facts = fact_items(["plain text", {"kind": "Proper Noun", "value": "Name"},
                        {"type": "weird", "description": "d"}, {"kind": "number"},
                        7, None, [1]], FACT_KINDS)
    assert facts == [{"kind": "other", "text": "plain text"},
                     {"kind": "proper_noun", "text": "Name"},
                     {"kind": "other", "text": "d"},
                     {"kind": "other", "text": "7"}]
    rels = relation_items([{"type": "causes", "entity_id": "e1"},
                           {"relation": "related-to", "target": {"id": "e2"}},
                           {"type": "causes"}, "bad", {"type": "nope", "target": "e1"}],
                          RELATION_TYPES)
    assert rels == [{"type": "causes", "target": "e1"},
                    {"type": "related_to", "target": "e2"}]
    assert text_of({"text": {"value": "deep"}}) == "deep"


def _runner_result(item, **kw):
    g = world_only_graph()
    brief = {"statements": [{"id": "s1", "text": "a"}, {"id": "s2", "text": "b"}]}
    base = {"type": "concept", "name": "N", "summary": "S",
            "facts": [{"kind": "proper_noun", "text": "Nn"}],
            "statement_ids": ["s1"]}
    base.update(item)
    backend = FakeLLMBackend({"candidates": base if kw.get("single") else [base]})
    return OperatorRunner(backend).run(
        "expand", g, "e1", 1, brief=brief, axes=AXES)


@pytest.mark.parametrize("derived", [
    [{"id": "e1"}], [{"target": "e1"}], [{"entity_id": "e1"}], "e1", ["e1"],
    [["e1"]], [None, 5, {"x": 1}, "e1"]])
def test_derived_from_shapes_do_not_crash(derived):
    out = _runner_result({"derived_from": derived, "reason": "because"})
    assert len(out) == 1
    assert out[0]["entity"]["provenance"]["derived_from"] == ["e1"]


def test_other_malformed_fields_never_raise():
    out = _runner_result({"statement_ids": "s1, s2", "axes": [{"id": "a1"}, 4],
                          "relations": [{"type": "causes", "target": {"id": "e1"}},
                                        {"type": "causes"}, "x"],
                          "facts": ["bare string", {"kind": "number", "value": 3},
                                    {"kind": ["x"], "text": ["y"]}, None],
                          "reason": {"text": "why"}})
    e = out[0]["entity"]
    assert e["provenance"]["statement_ids"] == ["s1", "s2"]
    assert e["axes"] == ["a1"]
    assert [f["text"] for f in e["facts"]] == ["bare string", "3"]
    assert {"type": "causes", "target": "e1"} in e["relations"]
    for junk in ({"name": {"x": 1}}, {"summary": None}, {"type": ["concept"]},
                 {"statement_ids": {"a": 1}}, {"facts": "one string"},
                 {"derived_from": 5, "statement_ids": None}):
        _runner_result(junk)  # dropped or coerced, never an exception
    assert len(_runner_result({}, single=True)) == 1  # one object, not a list


def test_axes_input_and_judge_parsing_survive_bad_shapes(tmp_path):
    brief = {"statements": [{"id": "s1", "text": "t"}], "open_questions": [],
             "constraints": []}
    bad = {"axes": [{"domain": "history", "weight": 0.5, "meaning": ["x"],
                     "statement_ids": [{"id": "s1"}, [["s9"]], None]},
                    {"domain": {"a": 1}, "name": 3}, "junk"]}
    res = WorldAxesBuilder(FakeLLMBackend(bad), tmp_path).build(brief)
    hist = [a for a in res.axes if a["id"] == "history"][0]
    assert hist["grounds"]["statement_ids"] == ["s1"]
    built = InputBriefBuilder(FakeLLMBackend({
        "statements": ["塩鉱業", {"text": 5, "quote": ["x"]}, None],
        "open_questions": [None, {"text": "q"}, 3], "constraints": "c"}),
        tmp_path / "i").build("塩鉱業で暮らす")
    assert [s["text"] for s in built.brief["statements"]] == ["塩鉱業"]
    judge = LLMJudge(FakeLLMBackend({"score": 0.5, "issues": 3}))
    out = judge.judge("specificity", SPECIFIC[0], new_graph("ja"))
    assert out and out[0].code == "llm_judge"
    judge = LLMJudge(FakeLLMBackend({"score": [1], "issues": {"a": 1}}))
    assert judge.judge("specificity", SPECIFIC[0], new_graph("ja")) is None


# ----------------------------------------------- resilient loop (#43 fix)

def flaky_backend(bad_calls, exc=lambda: TimeoutError("backend timed out")):
    inner = make_backend()
    calls = {"n": 0}

    def respond(prompt):
        calls["n"] += 1
        if calls["n"] in bad_calls:
            raise exc()
        return inner.json_source(prompt) if hasattr(inner, "json_source") \
            else inner.generate_json(prompt)
    return FakeLLMBackend(respond)


def run_loop(tmp_path, backend, iterations=8, **budget):
    from tests.test_world_explore import BRIEF as EB, AXES as EA
    c = load_explore_config()
    c["budget"].update({"max_iterations": iterations, **budget})
    c["coverage"]["enabled"] = False
    return ExplorationLoop(backend, tmp_path, EB, EA, seed=3, language="en",
                           config=c).run()


def test_backend_errors_on_some_calls_do_not_stop_the_run(tmp_path):
    result = run_loop(tmp_path, flaky_backend({3, 9, 10}))
    assert result.stop_reason == "max_iterations" and result.iterations == 8
    assert result.counters["errors"] >= 1
    log = read_preference_log(tmp_path / "world" / "preferences.jsonl")
    errs = [r for r in log if r["type"] == "iteration" and r["outcome"] == "error"]
    assert errs and errs[0]["error"]["class"] == "TimeoutError"
    assert errs[0]["arm_reward"] == 0.0 and errs[0]["accepted_id"] is None
    assert any(r["outcome"] == "accepted" for r in log if r["type"] == "iteration")


def test_malformed_model_output_in_the_loop_is_not_fatal(tmp_path):
    inner = make_backend()

    def respond(prompt):
        out = inner.generate_json(prompt)
        for c in (out or {}).get("candidates", []):
            c["derived_from"] = [{"id": "e1"}, {"target": "e2"}]
            c["facts"] = [f["text"] for f in c["facts"]]
        return out
    result = run_loop(tmp_path, FakeLLMBackend(respond), iterations=5)
    assert result.stop_reason == "max_iterations"


def test_consecutive_failure_limit_stops_with_a_clear_reason(tmp_path):
    def boom():
        return ValueError("invalid JSON after retries")
    backend = flaky_backend(set(range(1, 1000)), boom)
    result = run_loop(tmp_path, backend, iterations=50,
                      max_consecutive_failures=3)
    assert result.stop_reason == "too_many_failures"
    assert "too_many_failures" in STOP_REASONS
    assert result.iterations == 3 and result.counters["errors"] == 3
    # checkpoint keeps the reason and a later resume can continue
    again = run_loop(tmp_path, make_backend(), iterations=6,
                     max_consecutive_failures=3)
    assert again.stop_reason == "max_iterations"
    assert again.counters["accepted"] >= 1


def test_a_success_resets_the_consecutive_failure_count(tmp_path):
    result = run_loop(tmp_path, flaky_backend({2, 3, 7, 8}), iterations=10,
                      max_consecutive_failures=3)
    assert result.stop_reason == "max_iterations"


def test_example_run_exits_nonzero_on_too_many_failures():
    import example_run

    class R:
        stop_reason = "too_many_failures"
    assert example_run._exit_code(R()) == 1

    class Ok:
        stop_reason = "max_iterations"
    assert example_run._exit_code(Ok()) == 0
