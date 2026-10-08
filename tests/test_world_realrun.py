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
from src.world.textsim import echo_coverage
from src.world.verify import (
    reference_text, verify_specificity,
    load_language_rules,
)
from tests.test_world_explore import make_backend

RAW_JA = (
    "この塩の盆地では塩鉱業で暮らしが成り立っている。"
    "降水が乏しく、水は古い地下水道から引いている。"
    "鉱夫組合と水守の家系が、地下水道の管理権をめぐって長く争っている。"
)
BRIEF_JA = {"statements": [
    {"id": "s1", "text": "この塩の盆地では塩鉱業で暮らしが成り立っている。",
     "quote": "この塩の盆地では塩鉱業で暮らしが成り立っている。"},
    {"id": "s2", "text": "降水が乏しく、水は古い地下水道から引いている。",
     "quote": "降水が乏しく、水は古い地下水道から引いている。"},
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
              "内陸にある塩の盆地で、塩鉱業が営まれている。降水が乏しく、"
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






# ------------------------------------------------------------- A: genericity















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
        if prompt.startswith("WORLD CONTRACT"):
            from tests.test_world_explore import SYNTHETIC_PREMISES
            return SYNTHETIC_PREMISES
        return {"axes": [{"name": "", "reason": "", "domain": "resources_economy",
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

from src.world.explore import STOP_REASONS, read_preference_log
from src.world.structured import generate_structured




# ----------------------------------------------- resilient loop (#43 fix)

def flaky_backend(bad_calls, exc=lambda: TimeoutError("backend timed out")):
    inner = make_backend()
    calls = {"n": 0}

    def respond(prompt):
        calls["n"] += 1
        if calls["n"] in bad_calls:
            raise exc()
        return inner.json_source(prompt) if hasattr(inner, "json_source") \
            else json.loads(inner.generate_schema(prompt, {}, constrained=True))
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
        out = json.loads(inner.generate_schema(prompt, {}, constrained=True))
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
    inner = make_backend()
    iterations = {"n": 0}
    def respond(prompt):
        if "STEP: type\n" in prompt:
            iterations["n"] += 1
            if iterations["n"] in {2, 3, 7, 8}:
                raise TimeoutError("backend timed out")
        return json.loads(inner.generate_schema(prompt, {}, constrained=True))
    result = run_loop(tmp_path, FakeLLMBackend(respond), iterations=10,
                      max_consecutive_failures=3)
    assert result.stop_reason == "max_iterations"
    assert result.counters["errors"] == 4
    assert result.counters["accepted"] == 6



def test_example_run_exits_nonzero_on_too_many_failures():
    import example_run

    class R:
        stop_reason = "too_many_failures"
    assert example_run._exit_code(R()) == 1

    class Ok:
        stop_reason = "max_iterations"
    assert example_run._exit_code(Ok()) == 0
