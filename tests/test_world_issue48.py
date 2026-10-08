"""Issue #48 acceptance tests: synthetic worlds and deterministic fakes only."""

import copy
import json

import pytest

from tests.helpers_world import candidate_output, deterministic_candidate, deterministic_result
from src.llm.fake import FakeLLMBackend
from tests.helpers_world import contract_backend
from src.world.graph import GraphStore, local_context, make_entity, new_graph, validate_graph
from src.world.operators import OPERATORS, validate_candidate
from src.world.premises import unit_symbols, world_premises
from src.world.render import render_world_package


BRIEF = {"statements": [{"id": "s1", "text": "岩棚の集落は共有の荷揚げ場の順番を札で管理する。",
                         "quote": "岩棚の集落は共有の荷揚げ場の順番を札で管理する。"}]}
PROV = {"statement_ids": ["s1"], "derived_from": [], "reason": ""}
CONTRACT = {
    "calendar": {"name": "巡輪紀", "origin": "最初の共同荷揚げ場の開設",
                 "markers": ["巡輪紀", "架台紀"]},
    "technology": {"description": "手回し巻上げ器と刻み棒による測定。連続動力や自動計測はない。",
                   "capabilities": ["手回し巻上げ器", "刻み棒"],
                   "units": [{"symbol": "cm", "quantity": "長さ"},
                             {"symbol": "m", "quantity": "長さ"},
                             {"symbol": "年", "quantity": "期間"},
                             {"symbol": "巡", "quantity": "照合の間隔"},
                             {"symbol": "間", "quantity": "期間"}]}}


def graph():
    g = new_graph("ja")
    root = make_entity("e1", "place", "岩棚連域", "world", provenance=PROV,
                       summary="共有の荷揚げ場を持つ岩棚群。")
    root.update(origin_operator="premise", world_premises=copy.deepcopy(CONTRACT))
    region = make_entity("e2", "institution", "架台調整会", "region", parent="e1",
                         summary="荷揚げの順番札を照合する組織。", provenance=PROV)
    g["entities"] = [root, region]
    return g


def raw(text="設立は巡輪紀18年。", kind="period", **extra):
    return candidate_output({"type": "institution", "name": "ミオル照合所",
            "summary": "順番札の刻みを照合して架台の使用順を記録する。",
            "facts": [{"kind": "proper_noun", "text": "札の照合台はミオル架台と呼ばれる。"},
                      {"kind": kind, "text": text},
                      {"kind": "object", "text": "照合所は刻み棒を測定に使う。"}],
            "statement_ids": ["s1"], "reason": "共有の使用順を記録するための取り決め。",
            **extra})


def generated(text="設立は巡輪紀18年。", kind="period", **extra):
    g = graph()
    return g, deterministic_candidate(raw(text, kind, **extra)), None


def score(g, candidate):
    return deterministic_result(g, candidate, BRIEF)


@pytest.mark.parametrize("text", ["設立年 1987", "設立は西暦1987年。",
                                  "活動期間1990-2025", "設立は別紀18年。"])
def test_undefined_chronology_is_penalized(text):
    g, candidate, _ = generated(text)
    result = score(g, candidate)
    assert result.scores["consistency"] < 0.7
    assert "consistency" in result.failed
    assert any(d.code == "undefined_calendar" for d in result.deductions)


@pytest.mark.parametrize("text", ["巡輪紀18年", "架台紀1987年", "巡輪紀1990-2025",
                                  "補修の期間は5年。", "照合は3年間続く。",
                                  "補修は10年前。", "照合の間隔は300巡。"])
def test_defined_chronology_and_durations_are_not_penalized(text):
    g, candidate, _ = generated(text)
    result = score(g, candidate)
    assert result.scores["consistency"] == 1
    assert not result.deductions_for("consistency")


@pytest.mark.parametrize("unit", ["V", "kW", "qx"])
def test_undefined_units_are_warnings_without_a_technology_blacklist(unit):
    g, candidate, _ = generated(f"巻上げ装置の定格は1.5{unit}。", "number")
    result = score(g, candidate)
    assert result.scores["consistency"] == 1
    assert any(d.code == "undefined_unit" and d.penalty == 0 for d in result.deductions)


def test_arbitrary_input_defined_calendar_capability_and_unit_are_allowed():
    # Even a familiar-looking year or technical notation is legal if the
    # supplied world contract explicitly defines it. No deny list is used.
    g, candidate, _ = generated("西暦1987年に設置、定格220V。", "period",
                               premise_usage={"calendars": ["西暦"],
                                              "technologies": ["電動巻上げ器"], "units": ["V"]})
    g["entities"][0]["world_premises"]["calendar"]["markers"].append("西暦")
    g["entities"][0]["world_premises"]["technology"]["capabilities"].append("電動巻上げ器")
    g["entities"][0]["world_premises"]["technology"]["units"].append({"symbol": "V", "quantity": "定格電圧"})
    result = score(g, candidate)
    assert result.scores["consistency"] == 1


def test_device_reference_must_be_defined_and_survives_normalization():
    g, candidate, _ = generated("自動記録器を使用する。", "object",
                               premise_usage={"technologies": ["自動記録器"]})
    assert candidate["entity"]["premise_usage"]["technologies"] == ["自動記録器"]
    result = score(g, candidate)
    assert any(d.code == "undefined_technology" for d in result.deductions)
    assert result.scores["consistency"] < 0.7


def test_unit_symbols_preserve_case_and_fullwidth_numeric_text_is_normalized():
    g, candidate, _ = generated("長さは１２ｍ。", "number")
    assert score(g, candidate).scores["consistency"] == 1
    _, candidate, _ = generated("長さは12M。", "number")
    assert any(d.code == "undefined_unit" for d in score(g, candidate).deductions)


@pytest.mark.parametrize("unit", ["m/s", "%", "qx²"])
def test_compound_and_symbolic_units_with_unregistered_factors_need_registration(unit):
    g, candidate, _ = generated(f"荷揚げの測定値は12{unit}。", "number")
    assert any(d.code == "undefined_unit" for d in score(g, candidate).deductions)
    g["entities"][0]["world_premises"]["technology"]["units"].append({"symbol": unit, "quantity": "荷揚げの測定値"})
    assert score(g, candidate).scores["consistency"] == 1




def test_contract_stage_records_world_specific_decisions_without_changing_input(tmp_path):
    from src.world.contract import establish_contract
    from src.world.premises import CONTRACT_ID
    g = new_graph("ja")
    brief_before = copy.deepcopy(BRIEF)
    contract = {**CONTRACT, "technology": {**CONTRACT["technology"], "units": CONTRACT["technology"]["units"][:4]}, "society": {"description": "札で共有の使用順を決める。", "institutions": []}}
    stage = establish_contract(contract_backend(contract), g, BRIEF, [])
    assert BRIEF == brief_before and not g["entities"]
    assert stage["status"] == "success" and world_premises(g)["source_entity"] == CONTRACT_ID
    store = GraphStore(tmp_path, brief=BRIEF)
    store.save(g)
    assert world_premises(store.load())["calendar"] == CONTRACT["calendar"]
    (tmp_path / "input").mkdir()
    (tmp_path / "input/input_brief.json").write_text(json.dumps(BRIEF))
    paths = render_world_package(tmp_path)
    final = json.loads(paths["world_json"].read_text())
    assert final["world_contract"]["world_premises"] == contract
    assert "巡輪紀" in paths["report"].read_text()






def test_conflicting_contracts_and_malformed_usage_cannot_be_persisted():
    g = graph()
    other = copy.deepcopy(g["entities"][0])
    other["id"] = "e3"
    other["world_premises"]["calendar"]["origin"] = "別の起点"
    g["entities"].append(other)
    assert any("conflicting world contracts" in e for e in validate_graph(g))
    _, candidate, _ = generated()
    candidate["entity"]["premise_usage"] = {"technologies": "malformed"}
    g = graph()
    g["entities"].append(candidate["entity"])
    assert any("premise_usage" in e for e in validate_graph(g))












@pytest.mark.parametrize("language,text", [
    ("ja", "持続可能な荷揚げ場の利用を推進している。"),
    ("ja", "公平な配分を目的としている。"),
    ("en", "The office promotes sustainable use of shared platforms.")])
def test_purpose_and_evaluation_wording_costs_specificity(language, text):
    g, vague, _ = generated(text, "procedure")
    g["meta"]["language"] = language
    concrete = copy.deepcopy(vague)
    concrete["entity"]["facts"][1]["text"] = "受付係が毎巡、札の刻みを照合し、欠けた札を回収する。"
    bad = score(g, vague)
    good = score(g, concrete)
    assert bad.scores["specificity"] < good.scores["specificity"]
    assert any(d.code == "purpose_without_mechanism" and d.field == "facts[1]"
               for d in bad.deductions)




# Review regressions: measurability, reviewed growth, kind semantics and cost.
















@pytest.mark.parametrize("language,text", [
    ("ja", "委員は水番家系の代表である。"),
    ("ja", "担当者は受付の責任者である。"),
    ("en", "The delegates are representatives of the keepers."),
    ("en", "The clerk belongs to the council."),
])
def test_person_attributes_relations_and_roles_are_not_object_facts(language, text):
    from src.world.verify import load_language_rules, verify_specificity
    g, candidate, _ = generated(text, "object")
    result = verify_specificity(candidate, language, load_language_rules())
    assert any(d.code == "non_object_fact" and d.field == "facts[1]" and d.penalty > 0 for d in result.deductions)
    # A role cannot fill object kind coverage when no physical object exists.
    candidate["entity"]["facts"].pop(2)
    result = verify_specificity(candidate, language, load_language_rules())
    assert all("object" not in d.detail["kinds"] for d in result.deductions if d.code == "kind_coverage")


@pytest.mark.parametrize("language,text", [
    ("ja", "委員は照合台に置いた刻み棒で札を測定する。"),
    ("ja", "照合所は刻み棒を測定に使う。"),
    ("ja", "手回し巻上げ器は荷揚げを担う。"),
    ("en", "The clerk uses a marked rod at the desk."),
    ("en", "The office keeps a ledger on its table."),
    ("en", "The ledger belongs to the council."),
    ("en", "The marked rod is responsible for comparing lengths."),
])
def test_physical_objects_linked_to_people_remain_object_facts(language, text):
    from src.world.verify import load_language_rules, verify_specificity
    _, candidate, _ = generated(text, "object")
    result = verify_specificity(candidate, language, load_language_rules())
    assert not any(d.code == "non_object_fact" for d in result.deductions)








@pytest.mark.parametrize("bad_extension", [
    None, {"source_entity": []}, {"source_entity": "missing"},
    {"source_entity": "e1", "units": "kg", "capabilities": [], "reason": "bad"},
    {"source_entity": "e1", "units": ["undeclared"], "capabilities": [], "reason": "bad"},
])
def test_invalid_extension_history_is_rejected_without_crashing(bad_extension):
    g, candidate, _ = generated("照合所の札束の重さは2kg。", "number", premise_usage={"units": ["kg"]})
    candidate["entity"]["premise_extension"] = bad_extension
    g["entities"].append(candidate["entity"])
    assert any("premise_extension" in e for e in validate_graph(g))
    assert "kg" not in unit_symbols(world_premises(g))
