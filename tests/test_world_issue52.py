"""Issue #52: acceptance on synthetic worlds through production paths."""

import copy
import json
from types import SimpleNamespace

import pytest

from tests.helpers_world import candidate_output, deterministic_candidate, deterministic_result
from src.llm.fake import FakeLLMBackend
from tests.helpers_world import contract_backend, configure_contract
from src.world.explore import ExplorationLoop, load_explore_config, read_preference_log
from src.world.graph import make_entity, new_graph, validate_graph
from src.world.operators import OPERATORS
from src.world.premises import normalize_premises, premise_errors, world_premises
from src.world.render import render_world_package


BRIEF = {"statements": [{"id": "s1", "text": "共同作業の割当は参加者が札で照合する。",
                         "quote": "共同作業の割当は参加者が札で照合する。"}]}
PROV = {"statement_ids": ["s1"], "derived_from": [], "reason": ""}
CONTRACT = {
    "calendar": {"name": "照環紀", "origin": "最初の共同作業", "markers": ["照環紀"]},
    "technology": {"description": "刻み棒と手動の比較装置で長さと容器量を測る。遠隔自動計測はない。",
                   "capabilities": ["刻み棒", "比較容器"],
                   "units": [{"symbol": "刻", "quantity": "長さ"},
                             {"symbol": "槽", "quantity": "容器量"},
                             {"symbol": "年", "quantity": "期間"}]},
    "society": {"description": "参加者の持ち回り照合で割当を決める。恒常的な外部統治権はない。",
                "institutions": [{"name": "札照合の持ち回り", "description": "参加者が交替で割当札を照合する。"}]}}
AXES = [{"id": "a1", "domain": "law", "name": "割当の規則",
         "meaning": "札の照合で参加者の順を決める。", "statement_ids": ["s1"]}]


def graph(language="ja", society=True):
    g = new_graph(language)
    root = make_entity("e1", "place", "トル環域", "world", provenance=PROV)
    root.update(origin_operator="premise", world_premises=copy.deepcopy(CONTRACT))
    if not society:
        root["world_premises"].pop("society")
    region = make_entity("e2", "institution", "照合番", "region", parent="e1", provenance=PROV)
    g["entities"] = [root, region]
    return g


def raw(text="長さの比較は3刻ごとに刻み棒で行う。", kind="number", **extra):
    return candidate_output({"type": "institution", "name": "ナリオ照合所", "axes": ["a1"],
            "summary": "欠けた札を照合台で取り除き、次の順番札を渡す。",
            "facts": [{"kind": "proper_noun", "text": "照合台の固有名はナリオ台。"},
                      {"kind": kind, "text": text},
                      {"kind": "object", "text": "照合所は比較容器を棚に保管する。"}],
            "statement_ids": ["s1"], "derived_from": [],
            "reason": "札の持ち回り照合を参加者が行い、その手順を記録する。", **extra})


def generate(g, item):
    return deterministic_candidate(item), None


def verify(g, candidate):
    return deterministic_result(g, candidate, BRIEF), None


@pytest.mark.parametrize("text,kind", [
    ("契約番号 001", "proper_noun"), ("メンバー数 200", "number"),
    ("照合所の会員数は 200人。", "number"),
    ("Contract number 001.", "proper_noun"), ("Member count: 200.", "number"),
])
def test_identifiers_and_counts_alone_are_thin_regardless_of_kind(text, kind):
    language = "en" if text.isascii() else "ja"
    g = graph(language)
    candidate, _ = generate(g, raw(text, kind))
    result, _ = verify(g, candidate)
    assert any(d.code == "thin_fact" and d.field == "facts[1]" and d.penalty > 0 for d in result.deductions)
    assert result.scores["specificity"] < 1


@pytest.mark.parametrize("text", [
    "契約番号001を照合し、欠けた札の再交付を記録する。",
    "メンバー200人が交替ごとに2人ずつ札を照合する。",
    "Contract number 001 controls replacement of damaged tokens.",
])
def test_numeric_facts_with_procedures_have_substance(text):
    g = graph("en" if text.isascii() else "ja")
    candidate, _ = generate(g, raw(text))
    result, _ = verify(g, candidate)
    assert not any(d.code == "thin_fact" for d in result.deductions)


def test_society_roundtrip_legacy_compatibility_and_validation(tmp_path):
    assert normalize_premises(CONTRACT) == CONTRACT
    legacy = copy.deepcopy(CONTRACT)
    legacy.pop("society")
    assert normalize_premises(legacy) == legacy
    for bad in (None, {}, {"description": "", "institutions": []},
                {"description": "枠組み", "institutions": "bad"}):
        assert premise_errors({**CONTRACT, "society": bad})
    g = graph()
    from src.world.graph import GraphStore
    store = GraphStore(tmp_path, brief=BRIEF)
    store.save(g)
    assert world_premises(store.load())["society"] == CONTRACT["society"]
    (tmp_path / "input").mkdir()
    (tmp_path / "input/input_brief.json").write_text(json.dumps(BRIEF))
    paths = render_world_package(tmp_path)
    page = (tmp_path / "final/world_bible/entities/e1.md").read_text()
    assert "制度・社会の枠組み" in page and "札照合の持ち回り" in page
    assert world_premises(json.loads(paths["world_json"].read_text()))["society"] == CONTRACT["society"]












def test_bootstrap_society_is_recorded_by_separate_contract_stage(tmp_path, monkeypatch):
    from src.world.contract import establish_contract
    g = new_graph("ja")
    before = copy.deepcopy(BRIEF)
    configure_contract(monkeypatch, tmp_path, CONTRACT)
    stage = establish_contract(contract_backend(CONTRACT), g, BRIEF, AXES)
    assert stage["status"] == "success" and BRIEF == before and not g["entities"]
    assert g["world_contract"]["world_premises"]["society"] == CONTRACT["society"]









APPROVAL_FORMS = [
    {"approve_premise_extension": "yes"},
    {"extension_approved": True},
    {"approval": "yes"},
    {"approvePremiseExtension": "yes"},
    {"premise-extension-approval": "yes"},
    {"premise_extension_approvals": {"units": [{"unit": "qx", "approved": "yes", "why": "derived measurement"}], "capabilities": []}},
    {"approvals": {"units": {"qx": True}}},
    {"extension_approvals": [{"unit": "qx", "decision": "yes"}]},
    {"approve_extension": [True]},
    {"premise_extension_approvals": {"units": ["yes"]}},
]












@pytest.mark.parametrize("text", ["メンバー 12 名", "照合番の参加者は１２人。", "札束 12 本。", "箱 3個である。",
                                 "Twelvefold assembly: 12 people."])
@pytest.mark.parametrize("kind", ["number", "object", "proper_noun"])
def test_count_only_syntax_does_not_depend_on_label_vocabulary_or_kind(text, kind):
    g = graph("en" if text.isascii() else "ja")
    candidate, _ = generate(g, raw(text, kind))
    result, _ = verify(g, candidate)
    assert any(d.field == "facts[1]" and d.code in {"thin_fact", "bare_count"} and d.penalty > 0 for d in result.deductions)
    assert result.scores["specificity"] < 1


@pytest.mark.parametrize("text", ["メンバー12名が交替ごとに札を照合する。", "箱3個は破損している。",
                                 "The 12 people compare tokens after each exchange."])
def test_count_with_property_or_procedure_is_not_a_count_only_fragment(text):
    candidate, _ = generate(graph("en" if text.isascii() else "ja"), raw(text, "procedure"))
    result, _ = verify(graph("en" if text.isascii() else "ja"), candidate)
    assert not any(d.field == "facts[1]" and d.code in {"thin_fact", "bare_count"} for d in result.deductions)


@pytest.mark.parametrize("text", ["環境を保護する。", "低影響。", "水資源の過剰利用を防止する。",
                                 "安定供給を目的としている。", "The office prevents excessive use.", "Low impact."])
@pytest.mark.parametrize("field", ["summary", "facts"])
def test_unsupported_purpose_or_effect_is_penalized_in_its_own_field(text, field):
    g = graph("en" if text.isascii() else "ja")
    item = raw(text, "procedure") if field == "facts" else raw(summary=text)
    candidate, _ = generate(g, item)
    result, _ = verify(g, candidate)
    expected = "facts[1]" if field == "facts" else "summary"
    assert any(d.field == expected and d.code in {"purpose_without_mechanism", "unsupported_evaluation"}
               and d.penalty > 0 for d in result.deductions)
    assert result.scores["specificity"] < 1


@pytest.mark.parametrize("text", [
    "照合番は安定供給を目的として、札が欠けたときに割当札を回収し、停止した件数を記録する。",
    "The clerk aims to maintain stable supply and removes damaged tokens when a comparison fails, and records the stopped exchanges.",
])
def test_purpose_with_actor_procedure_condition_and_observed_result_is_grounded(text):
    g = graph("en" if text.isascii() else "ja")
    candidate, _ = generate(g, raw(summary=text))
    result, _ = verify(g, candidate)
    assert not any(d.field == "summary" and d.code in {"purpose_without_mechanism", "unsupported_evaluation"}
                   for d in result.deductions)


def test_unrelated_procedure_sentence_does_not_justify_an_effect_claim():
    candidate, _ = generate(graph(), raw(summary="照合番は札が欠けたときに回収し、停止した件数を記録する。環境を保護する。"))
    result, _ = verify(graph(), candidate)
    assert any(d.field == "summary" and d.code == "purpose_without_mechanism" for d in result.deductions)












@pytest.mark.parametrize("language,text", [
    ("ja", "年間500槽/日。"), ("ja", "年間 ５００ m³/日。"),
    ("ja", "月間20槽/年。"), ("ja", "日量4槽/時間。"),
    ("en", "Annual 500 qx/day."), ("en", "monthly output 20 qx per year."),
])
def test_rate_dimension_conflicts_remain_deterministic(language, text):
    candidate, _ = generate(graph(language), raw(text))
    result, _ = verify(graph(language), candidate)
    assert result.scores["consistency"] < 0.7
    deduction = next(d for d in result.deductions if d.code == "dimension_conflict")
    assert deduction.field == "facts[1]" and deduction.penalty > 0


@pytest.mark.parametrize("language,text", [
    ("ja", "年間500槽。"), ("ja", "日量500槽/日。"),
    ("ja", "年間を通じて日量500槽/日を比較容器で測る。"),
    ("ja", "観測期間は1年、容器量は500槽/日。"),
    ("en", "Daily 500 qx/day."), ("en", "Annual 500 qx/year."),
    ("en", "For one year, throughput was 500 qx/day."),
])
def test_totals_matching_rates_and_observation_windows_are_not_dimension_conflicts(language, text):
    candidate, _ = generate(graph(language), raw(text))
    result, _ = verify(graph(language), candidate)
    assert not any(d.code == "dimension_conflict" for d in result.deductions)


@pytest.mark.parametrize("registered,unit", [
    (["qx"], "qx²"), (["qx^3"], "qx3"), (["qx^3"], "ｑｘ³"),
    (["qx^3", "槽"], "qx^6/槽"), (["qx/uv", "uv/zr"], "qx/zr"),
    (["qx/uv"], "(qx/uv)^2"),
])
def test_unit_algebra_works_for_invented_symbols_and_registered_composites(registered, unit):
    from src.world.quantities import registered_unit, units_in_text
    from src.world.language import load_language_rules, rules_for
    g = graph()
    g["entities"][0]["world_premises"]["technology"]["units"] = [
        {"symbol": symbol, "quantity": "容器量の比較値"} for symbol in registered]
    contract = world_premises(g)
    rules = rules_for(load_language_rules(), "ja")
    assert registered_unit(unit, contract, rules)
    assert all(registered_unit(u, contract, rules) for u in units_in_text(f"比較容器の容量は3{unit}。", contract, rules))
    candidate, _ = generate(g, raw(f"比較容器の容量は3{unit}。", premise_usage={"units": [unit]}))
    result, _ = verify(g, candidate)
    assert not any(d.code == "undefined_unit" for d in result.deductions)


@pytest.mark.parametrize("registered,unit", [
    (["qx^3"], "qx"), (["qx"], "QX"), (["qx/uv"], "qx"),
    (["qx"], "uv/uv"), (["qx"], "(qx/uv)^2"), (["qx"], "qx^"),
])
def test_algebra_cannot_register_unknown_factors_roots_or_malformed_expressions(registered, unit):
    from src.world.quantities import registered_unit
    from src.world.language import load_language_rules, rules_for
    g = graph()
    g["entities"][0]["world_premises"]["technology"]["units"] = [
        {"symbol": symbol, "quantity": "容器量の比較値"} for symbol in registered]
    assert not registered_unit(unit, world_premises(g), rules_for(load_language_rules(), "ja"))
