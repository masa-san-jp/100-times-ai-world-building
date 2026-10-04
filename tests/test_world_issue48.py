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


# Review regressions: measurability, reviewed growth, kind semantics and cost.
def batch_judge(**assessments):
    return FakeLLMBackend(assessments)


def assessment(score=1, issues=None, approve=False):
    return {"score": score, "issues": issues or [], "approve_premise_extension": approve}


def test_new_weight_unit_is_measurable_and_needs_no_large_deduction():
    g, candidate, _ = generated("照合所で受け取る札束の重さは2kg。", "number",
        premise_usage={"units": ["kg"]})
    backend = batch_judge(specificity=assessment(), consistency=assessment(approve=True))
    result = score(g, candidate, LLMJudge(backend), ["specificity", "consistency"])
    assert result.passed, result.to_dict()
    assert result.scores["consistency"] == 1
    assert result.premise_extension["units"] == ["kg"]
    assert len(backend.json_prompts) == 1
    assert "quantity can be measured" in backend.json_prompts[0]
    assert "technology.description" in backend.json_prompts[0]
    assert "provenance" in backend.json_prompts[0]
    assert world_premises(g)["technology"]["units"] == CONTRACT["technology"]["units"]


def test_voltage_unit_is_rejected_by_semantic_review_not_symbol_list():
    g, candidate, _ = generated("巻上げ装置の定格は220V。", "number",
        premise_usage={"units": ["V"]})
    g["entities"][0]["world_premises"]["technology"]["description"] = "手動の装置と機械的測定のみ。電気の供給も利用もない。"
    assert score(g, candidate).scores["consistency"] == 1  # unit symbols alone do not establish a violation
    backend = batch_judge(specificity=assessment(), consistency=assessment(0.4, [
        {"field": "facts[1]", "code": "undefined_unit", "why": "電圧の測定には前提にない電気の利用が必要"}]))
    result = score(g, candidate, LLMJudge(backend), ["specificity", "consistency"])
    assert not result.passed and "consistency" in result.failed
    assert any(d.code == "undefined_unit" and d.penalty > 0 for d in result.deductions)
    assert not result.premise_extension
    assert len(backend.json_prompts) == 1
    assert "電気の供給も利用もない" in backend.json_prompts[0]
    assert "V" not in world_premises(g)["technology"]["units"]


def test_accepted_extension_persists_and_reaches_next_candidate_and_revision(tmp_path):
    from src.world.explore import ExplorationLoop
    g, candidate, _ = generated("照合所で受け取る札束の重さは2kg。", "number",
        premise_usage={"units": ["kg"], "technologies": ["刻み棒による荷重比較"]},
        reason="刻み棒で巻上げ器のたわみを比較し、同じ札束を基準に荷重を量る。")
    backend = batch_judge(specificity=assessment(), consistency=assessment(approve=True))
    verifier = RewardVerifier(load_reward_config(overrides={"llm_judges": ["specificity", "consistency"]}), judge=LLMJudge(backend))
    result = verifier.verify(g, candidate, brief=BRIEF)
    assert result.passed, result.to_dict()
    loop = ExplorationLoop(FakeLLMBackend(), tmp_path, BRIEF, [], verifier=verifier)
    loop.store.save(g)
    committed = loop._commit(g, candidate["entity"], result)
    loaded = loop.store.load()
    assert loaded == committed
    assert not validate_graph(loaded, brief=BRIEF)
    root = loaded["entities"][0]
    assert root["world_premises"] == CONTRACT  # original limits are preserved
    history = next(e for e in loaded["entities"] if e["id"] == candidate["entity"]["id"])["premise_extension"]
    assert history == result.premise_extension
    assert history["source_entity"] == "e1" and history["reason"] == candidate["entity"]["provenance"]["reason"]
    contract = world_premises(loaded)
    assert "kg" in contract["technology"]["units"]
    assert "刻み棒による荷重比較" in contract["technology"]["capabilities"]
    assert contract["technology"]["description"] == CONTRACT["technology"]["description"]
    next_backend = FakeLLMBackend({"candidates": [raw("照合所の札束の重さは3kg。", "number", name="オルカ札束所", premise_usage={"units": ["kg"]})]})
    runner = OperatorRunner(next_backend)
    following = runner.run("expand", loaded, "e2", 1, brief=BRIEF)[0]
    following_result = score(loaded, following)
    assert following_result.scores["consistency"] == 1
    assert not any(d.code == "undefined_unit" for d in following_result.deductions)
    runner.revise(following, [], loaded, brief=BRIEF)
    assert all('"kg"' in p for p in next_backend.json_prompts)
    (tmp_path / "input").mkdir()
    (tmp_path / "input/input_brief.json").write_text(json.dumps(BRIEF))
    final = json.loads(render_world_package(tmp_path)["world_json"].read_text())
    assert world_premises(final)["technology"] == contract["technology"]
    # Removing a rolled-back contributor also removes its additions.
    rolled_back = {**loaded, "entities": [e for e in loaded["entities"] if "premise_extension" not in e]}
    assert "kg" not in world_premises(rolled_back)["technology"]["units"]


@pytest.mark.parametrize("response", [
    {}, {"consistency": {"score": []}},
    {"consistency": assessment(approve=False)},
    {"consistency": {"score": 1, "approve_premise_extension": True}},
    {"consistency": assessment(0.4, approve=True)},
    {"consistency": assessment(1, [{"code": "undefined_technology"}], approve=True)},
    {"consistency": {"score": "NaN", "issues": [], "approve_premise_extension": True}},
    {"consistency": {"score": 2, "issues": [], "approve_premise_extension": True}},
    {"consistency": {"score": True, "issues": [], "approve_premise_extension": True}},
])
def test_extension_requires_explicit_usable_consistency_approval(response):
    g, candidate, _ = generated("照合所の荷重比較装置の重さは2kg。", "number",
        premise_usage={"units": ["kg"], "technologies": ["荷重比較装置"]})
    backend = FakeLLMBackend(response)
    result = score(g, candidate, LLMJudge(backend), ["specificity", "consistency"])
    assert len(backend.json_prompts) == 1
    assert not result.passed and "consistency" in result.failed
    assert not result.premise_extension
    assert "kg" not in world_premises(g)["technology"]["units"]


@pytest.mark.parametrize("missing", ["usage", "reason", "judge"])
def test_extension_requires_declared_usage_derivation_and_judge(missing):
    g, candidate, _ = generated("照合所の札束の重さは2kg。", "number", premise_usage={"units": ["kg"]})
    if missing == "usage":
        candidate["entity"].pop("premise_usage")
    if missing == "reason":
        candidate["entity"]["provenance"]["reason"] = ""
    backend = batch_judge(consistency=assessment(approve=True))
    result = score(g, candidate, None if missing == "judge" else LLMJudge(backend), ["consistency"])
    assert not result.premise_extension
    assert "kg" not in world_premises(g)["technology"]["units"]


def test_rejected_candidate_cannot_contribute_even_when_consistency_approves():
    g, candidate, _ = generated("照合所の札束の重さは2kg。", "number", premise_usage={"units": ["kg"]})
    backend = batch_judge(specificity=assessment(0.1), consistency=assessment(approve=True))
    result = score(g, candidate, LLMJudge(backend), ["specificity", "consistency"])
    assert not result.passed and not result.premise_extension
    assert "kg" not in world_premises(g)["technology"]["units"]


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


def test_semantic_judge_supplements_object_kind_rules_in_one_call():
    g, candidate, _ = generated("照合所の受付は世襲で引き継がれる。", "object")
    backend = batch_judge(specificity=assessment(0.4, [{"field": "facts[1]", "code": "non_object_fact", "why": "人の役割の記述"}]), consistency=assessment())
    result = score(g, candidate, LLMJudge(backend), ["specificity", "consistency"])
    assert len(backend.json_prompts) == 1
    assert any(d.code == "non_object_fact" and d.penalty > 0 for d in result.deductions)
    assert "physical tool, facility or item" in backend.json_prompts[0]


@pytest.mark.parametrize("failure", ["threshold", "total", "structure"])
def test_deterministic_rejection_skips_all_judging(failure):
    g, candidate, _ = generated()
    config = load_reward_config(overrides={"llm_judges": ["specificity", "consistency"]})
    if failure == "threshold":
        candidate["entity"]["summary"] = "重要な役割を持つ。"
        candidate["entity"]["facts"] = []
    elif failure == "total":
        candidate["entity"]["facts"][2]["text"] = "照合所は刻み棒を測定に使う。持続可能な使用を推進する。"
        assert score(g, candidate).failed == []
        assert score(g, candidate).reward < 0.99
        config["thresholds"]["total"] = 0.99
    else:
        candidate["entity"]["parent"] = "missing"
    backend = batch_judge(specificity=assessment(), consistency=assessment())
    result = RewardVerifier(config, judge=LLMJudge(backend)).verify(g, candidate, brief=BRIEF)
    assert not result.passed
    assert backend.json_prompts == []


def test_batch_response_routes_scores_and_missing_criterion_does_not_retry():
    g, candidate, _ = generated()
    backend = FakeLLMBackend([{ "specificity": assessment(0.8), "consistency": assessment(0.4, [{"field": "facts[1]", "code": "implausible_value", "why": "measurement incompatible"}])},
                              {"specificity": assessment(0.9)}])
    judge = LLMJudge(backend)
    baseline = score(g, candidate)
    first = score(g, candidate, judge, ["specificity", "consistency", "specificity"])
    assert first.scores["specificity"] == pytest.approx(baseline.scores["specificity"] - 0.2)
    assert first.scores["consistency"] == pytest.approx(0.4)
    second = score(g, candidate, judge, ["specificity", "consistency"])
    assert second.scores["consistency"] == baseline.scores["consistency"]
    assert len(backend.json_prompts) == 2


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
    assert "kg" not in world_premises(g)["technology"]["units"]


def test_generator_cannot_supply_its_own_approval_history():
    g, candidate, _ = generated("照合所の札束の重さは2kg。", "number", premise_usage={"units": ["kg"]})
    from src.world.premises import proposed_extension
    candidate["entity"]["premise_extension"] = proposed_extension(candidate["entity"], world_premises(g))
    backend = batch_judge(consistency=assessment(approve=True))
    result = score(g, candidate, LLMJudge(backend), ["consistency"])
    assert not result.passed and not result.premise_extension
    assert not backend.json_prompts
    assert any(d.code == "graph_invalid" for d in result.deductions)


def test_reviewed_growth_is_not_limited_to_bootstrap_array_size():
    from src.world.premises import proposed_extension
    g = graph()
    for index in range(2):
        units = [f"u{index}_{n}" for n in range(16)]
        _, candidate, _ = generated(premise_usage={"units": units})
        candidate["entity"]["id"] = f"e{index + 3}"
        candidate["entity"]["premise_extension"] = proposed_extension(candidate["entity"], world_premises(g))
        g["entities"].append(candidate["entity"])
    assert not validate_graph(g)
    assert len(world_premises(g)["technology"]["units"]) == len(CONTRACT["technology"]["units"]) + 32


def test_exploration_uses_one_counted_judge_call_and_commits_history(tmp_path):
    from types import SimpleNamespace
    from src.world.explore import ExplorationLoop, load_explore_config, read_preference_log
    def respond(prompt):
        if "CRITERION:" in prompt:
            return {"specificity": assessment(), "consistency": assessment(approve=True)}
        return {"candidates": [raw("照合所の札束の重さは2kg。", "number", premise_usage={"units": ["kg"]})]}
    backend = FakeLLMBackend(respond)
    verifier = RewardVerifier(load_reward_config(overrides={"llm_judges": ["specificity", "consistency"]}),
        judge=LLMJudge(backend), contrasts=SimpleNamespace(get=lambda *args: []))
    config = load_explore_config()
    config["coverage"]["enabled"] = False
    config["generation"].update(candidates=1, max_rewrites=0)
    loop = ExplorationLoop(backend, tmp_path, BRIEF, [], config=config, language="ja", verifier=verifier)
    loop.store.save(graph())
    result = loop.run(max_iterations=1, max_generation_calls=2)
    assert result.counters["accepted"] == 1
    assert result.counters["generation_calls"] == 2  # generation + batched review
    assert sum("CRITERION:" in prompt for prompt in backend.json_prompts) == 1
    assert "kg" in world_premises(result.graph)["technology"]["units"]
    records = read_preference_log(tmp_path / "world/preferences.jsonl")
    adopted = next(r for r in records if r["type"] == "candidate" and r["decision"] == "accepted")
    assert adopted["result"]["premise_extension"]["units"] == ["kg"]
