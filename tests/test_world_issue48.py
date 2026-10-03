"""Issue #48 acceptance tests: synthetic worlds and deterministic fakes only."""

import copy
import json

import pytest

from src.llm.fake import FakeLLMBackend
from src.world.graph import GraphStore, local_context, make_entity, new_graph, validate_graph
from src.world.operators import OPERATORS, OperatorRunner
from src.world.premises import world_premises
from src.world.render import render_world_package
from src.world.reward import RewardVerifier, load_reward_config
from src.world.verify import LLMJudge


BRIEF = {"statements": [{"id": "s1", "text": "岩棚の集落は共有の荷揚げ場の順番を札で管理する。",
                         "quote": "岩棚の集落は共有の荷揚げ場の順番を札で管理する。"}]}
PROV = {"statement_ids": ["s1"], "derived_from": [], "reason": ""}
CONTRACT = {
    "calendar": {"name": "巡輪紀", "origin": "最初の共同荷揚げ場の開設",
                 "markers": ["巡輪紀", "架台紀"]},
    "technology": {"description": "手回し巻上げ器と刻み棒による測定。連続動力や自動計測はない。",
                   "capabilities": ["手回し巻上げ器", "刻み棒"],
                   "units": ["cm", "m", "年", "巡", "間"]}}


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
    return {"type": "institution", "name": "ミオル照合所",
            "summary": "順番札の刻みを照合して架台の使用順を記録する。",
            "facts": [{"kind": "proper_noun", "text": "札の照合台はミオル架台と呼ばれる。"},
                      {"kind": kind, "text": text},
                      {"kind": "object", "text": "照合所は刻み棒を測定に使う。"}],
            "statement_ids": ["s1"], "reason": "共有の使用順を記録するための取り決め。",
            **extra}


def generated(text="設立は巡輪紀18年。", kind="period", **extra):
    g = graph()
    backend = FakeLLMBackend({"candidates": [raw(text, kind, **extra)]})
    out = OperatorRunner(backend).run("expand", g, "e2", 1, brief=BRIEF)
    assert len(out) == 1
    return g, out[0], backend


def score(g, candidate, judge=None, criteria=()):
    verifier = RewardVerifier(load_reward_config(overrides={"llm_judges": list(criteria)}),
                              judge=judge)
    return verifier.verify(g, candidate, brief=BRIEF, store=False)


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
def test_undefined_units_are_detected_without_a_technology_blacklist(unit):
    g, candidate, _ = generated(f"巻上げ装置の定格は1.5{unit}。", "number")
    result = score(g, candidate)
    assert result.scores["consistency"] < 0.7
    assert any(d.code == "undefined_unit" for d in result.deductions)


def test_arbitrary_input_defined_calendar_capability_and_unit_are_allowed():
    # Even a familiar-looking year or technical notation is legal if the
    # supplied world contract explicitly defines it. No deny list is used.
    g, candidate, _ = generated("西暦1987年に設置、定格220V。", "period",
                               premise_usage={"calendars": ["西暦"],
                                              "technologies": ["電動巻上げ器"], "units": ["V"]})
    g["entities"][0]["world_premises"]["calendar"]["markers"].append("西暦")
    g["entities"][0]["world_premises"]["technology"]["capabilities"].append("電動巻上げ器")
    g["entities"][0]["world_premises"]["technology"]["units"].append("V")
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


@pytest.mark.parametrize("unit", ["m/s", "%", "m²"])
def test_compound_and_symbolic_units_require_the_exact_defined_notation(unit):
    g, candidate, _ = generated(f"荷揚げの測定値は12{unit}。", "number")
    assert any(d.code == "undefined_unit" for d in score(g, candidate).deductions)
    g["entities"][0]["world_premises"]["technology"]["units"].append(unit)
    assert score(g, candidate).scores["consistency"] == 1


def test_candidate_cannot_authorize_its_own_technology_by_redefining_contract():
    g = graph()
    altered = copy.deepcopy(CONTRACT)
    altered["technology"]["units"].append("kW")
    item = raw("定格は1.5kW。", "number", world_premises=altered)
    out = OperatorRunner(FakeLLMBackend({"candidates": [item]})).run(
        "premise", g, n=1, brief=BRIEF)
    assert out == []  # structurally conflicting contracts never reach storage
    _, candidate, _ = generated("定格は1.5kW。", "number")
    candidate["entity"]["world_premises"] = altered
    candidate["entity"].update(scale="world", parent=None, origin_operator="premise")
    candidate["operator"] = "premise"
    result = score(g, candidate)
    assert {"premise_conflict", "undefined_unit"} <= {d.code for d in result.deductions}
    assert world_premises(g)["technology"]["units"] == CONTRACT["technology"]["units"]


def test_initial_premise_records_world_specific_decisions_without_changing_input(tmp_path):
    g = new_graph("ja")
    brief_before = copy.deepcopy(BRIEF)
    item = raw(world_premises=CONTRACT)
    backend = FakeLLMBackend({"candidates": [item]})
    candidate = OperatorRunner(backend).run("premise", g, n=1, brief=BRIEF)[0]
    assert BRIEF == brief_before
    assert not g["entities"]  # only an accepted candidate becomes authoritative
    assert candidate["entity"]["world_premises"] == CONTRACT
    assert candidate["entity"]["provenance"]["reason"]
    assert score(g, candidate).scores["consistency"] == 1
    g["entities"].append(candidate["entity"])
    store = GraphStore(tmp_path, brief=BRIEF)
    store.save(g)
    assert world_premises(store.load())["calendar"] == CONTRACT["calendar"]
    (tmp_path / "input").mkdir()
    (tmp_path / "input/input_brief.json").write_text(json.dumps(BRIEF))
    paths = render_world_package(tmp_path)
    final = json.loads(paths["world_json"].read_text())
    assert final["entities"][0]["world_premises"] == CONTRACT
    page = (tmp_path / "final/world_bible/entities/e1.md").read_text()
    assert "巡輪紀" in page and "技術の能力と限界" in page


@pytest.mark.parametrize("value", [None, {}, {"calendar": "bad"},
                                  {**CONTRACT, "technology": {"units": []}}])
def test_missing_or_malformed_bootstrap_contract_is_not_accepted(value):
    item = raw()
    if value is not None:
        item["world_premises"] = value
    runner = OperatorRunner(FakeLLMBackend({"candidates": [item]}))
    assert runner.run("premise", new_graph("ja"), n=1, brief=BRIEF) == []


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


@pytest.mark.parametrize("operator", OPERATORS)
def test_every_operator_and_revision_receives_authoritative_premises(operator):
    g = graph()
    # The contract is on a distant root, beyond the target's bounded context.
    g["entities"].append(make_entity("e3", "place", "別棚", "world", provenance=PROV))
    g["entities"].append(make_entity("e4", "institution", "別棚受付", "region",
                                    parent="e3", provenance=PROV))
    assert local_context(g, "e4")["world_premises"]["source_entity"] == "e1"
    backend = FakeLLMBackend({"candidates": [raw()]})
    runner = OperatorRunner(backend)
    target = None if operator == "premise" else "e4"
    candidates = runner.run(operator, g, target, n=1, brief=BRIEF)
    assert candidates
    runner.revise(candidates[0], [{"field": "summary", "code": "test",
                                  "message": "clarify the action"}], g, brief=BRIEF)
    assert len(backend.json_prompts) == 2
    for prompt in backend.json_prompts:
        assert '"source_entity":"e1"' in prompt
        assert "最初の共同荷揚げ場の開設" in prompt
        assert "手回し巻上げ器" in prompt


def judging_backend(bad_text, code):
    def respond(prompt):
        if bad_text in prompt:
            return {"score": 0.4, "issues": [{"field": "facts[1]", "code": code,
                                               "why": "measured subject or stated link is incompatible"}]}
        return {"score": 1, "issues": []}
    return FakeLLMBackend(respond)


def test_optional_judge_detects_implausible_magnitude_for_the_subject():
    backend = judging_backend("支える石壁の厚さは2cm", "implausible_value")
    judge = LLMJudge(backend)
    g, bad, _ = generated("荷揚げ架台を支える石壁の厚さは2cm。", "number")
    _, good, _ = generated("荷揚げ架台を支える石壁の厚さは80cm。", "number")
    bad_result = score(g, bad, judge, ["consistency"])
    good_result = score(g, good, judge, ["consistency"])
    assert bad_result.scores["consistency"] == pytest.approx(0.4)
    assert good_result.scores["consistency"] == 1
    assert any(d.code == "implausible_value" and d.field == "facts[1]"
               for d in bad_result.deductions)
    prompt = backend.json_prompts[0]
    assert '"type": "institution"' in prompt
    assert "world_premises" in prompt and "order of magnitude" in prompt


def test_optional_judge_detects_unrelated_objects_and_accepts_explicit_use():
    backend = judging_backend("採掘用ロープ200m", "unrelated_fact")
    judge = LLMJudge(backend)
    g, bad, _ = generated("採掘用ロープ200m。", "object")
    _, good, _ = generated("照合所は点検時に架台へ降りるため長さ200mのロープを使う。", "object")
    bad_result = score(g, bad, judge, ["specificity"])
    good_result = score(g, good, judge, ["specificity"])
    assert bad_result.scores["specificity"] < good_result.scores["specificity"]
    assert any(d.code == "unrelated_fact" and d.field == "facts[1]"
               for d in bad_result.deductions)
    assert not any(d.code == "unrelated_fact" for d in good_result.deductions)
    assert '"relations"' in backend.json_prompts[0]


def test_optional_judge_catches_undeclared_capabilities_in_plain_prose():
    backend = judging_backend("リアルタイムで自動測定", "undefined_technology")
    g, candidate, _ = generated("水位をリアルタイムで自動測定する。", "procedure")
    assert "premise_usage" not in candidate["entity"]
    result = score(g, candidate, LLMJudge(backend), ["consistency"])
    assert result.scores["consistency"] < 0.7
    assert any(d.code == "undefined_technology" for d in result.deductions)
    assert "implied capabilities" in backend.json_prompts[0]


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


def test_optional_judge_is_not_called_when_disabled_or_returns_no_usable_score():
    g, candidate, _ = generated()
    backend = FakeLLMBackend({"score": [], "issues": []})
    judge = LLMJudge(backend)
    baseline = score(g, candidate, judge)
    assert backend.json_prompts == []
    assert score(g, candidate, judge, ["consistency"]).scores == baseline.scores
