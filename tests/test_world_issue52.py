"""Issue #52: acceptance on synthetic worlds through production paths."""

import copy
import json
from types import SimpleNamespace

import pytest

from src.llm.fake import FakeLLMBackend
from src.world.explore import ExplorationLoop, load_explore_config, read_preference_log
from src.world.graph import make_entity, new_graph, validate_graph
from src.world.operators import OPERATORS, OperatorRunner
from src.world.premises import normalize_premises, premise_errors, world_premises
from src.world.render import render_world_package
from src.world.reward import RewardVerifier, load_reward_config
from src.world.verify import LLMJudge


BRIEF = {"statements": [{"id": "s1", "text": "共同作業の割当は参加者が札で照合する。",
                         "quote": "共同作業の割当は参加者が札で照合する。"}]}
PROV = {"statement_ids": ["s1"], "derived_from": [], "reason": ""}
CONTRACT = {
    "calendar": {"name": "照環紀", "origin": "最初の共同作業", "markers": ["照環紀"]},
    "technology": {"description": "刻み棒と手動の比較装置で長さと容器量を測る。遠隔自動計測はない。",
                   "capabilities": ["刻み棒", "比較容器"], "units": ["刻", "槽", "年"]},
    "society": {"description": "参加者の持ち回り照合で割当を決める。恒常的な外部統治権はない。",
                "institutions": ["札照合の持ち回り"]}}
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
    return {"type": "institution", "name": "ナリオ照合所", "axes": ["a1"],
            "summary": "欠けた札を照合台で取り除き、次の順番札を渡す。",
            "facts": [{"kind": "proper_noun", "text": "照合台の固有名はナリオ台。"},
                      {"kind": kind, "text": text},
                      {"kind": "object", "text": "照合所は比較容器を棚に保管する。"}],
            "statement_ids": ["s1"], "derived_from": [],
            "reason": "札の持ち回り照合を参加者が行い、その手順を記録する。", **extra}


def generate(g, item):
    backend = FakeLLMBackend({"candidates": [item]})
    candidates = OperatorRunner(backend).run("expand", g, "e2", 1, brief=BRIEF, axes=AXES)
    assert len(candidates) == 1
    return candidates[0], backend


def assessment(score=1, issues=None, approve=False):
    return {"score": score, "issues": issues or [], "approve_premise_extension": approve}


def verify(g, candidate, response=None, criteria=()):
    backend = FakeLLMBackend(response) if response is not None else None
    verifier = RewardVerifier(load_reward_config(overrides={"llm_judges": list(criteria)}),
                              judge=LLMJudge(backend) if backend else None)
    result = verifier.verify(g, candidate, brief=BRIEF, axes=AXES)
    return result, backend


@pytest.mark.parametrize("declared", [False, True])
def test_unsupported_social_authority_is_penalized_even_when_not_declared(declared):
    g = graph()
    item = raw("照合所は上位統治局の許可証がなければ作業を禁止する。", "procedure")
    if declared:
        item["premise_usage"] = {"institutions": ["上位統治局"]}
    candidate, _ = generate(g, item)
    result, backend = verify(g, candidate, {"consistency": assessment(0.4, [
        {"field": "facts[1]", "code": "unsupported_institution",
         "why": "外部統治権の由来が社会の前提にも入力にも軸にもない。"}])})
    assert not result.passed and result.scores["consistency"] < 0.7
    assert any(d.code == "unsupported_institution" and d.field == "facts[1]" for d in result.deductions)
    assert len(backend.json_prompts) == 1
    assert "world_axes" in backend.json_prompts[0]
    assert "恒常的な外部統治権はない" in backend.json_prompts[0]
    assert "even when undeclared" in backend.json_prompts[0]


@pytest.mark.parametrize("name", ["札照合の持ち回り", "ナリオ札合わせ番"])
def test_supported_and_derived_social_names_are_allowed(name):
    g = graph()
    candidate, _ = generate(g, raw(f"{name}は参加者の交替時に欠けた札を回収する。", "procedure",
        premise_usage={"institutions": [name]}, reason="参加者の持ち回りから札の回収当番を導く。外部への統治権は持たない。"))
    result, backend = verify(g, candidate, {"consistency": assessment()})
    assert result.scores["consistency"] == 1
    assert not result.deductions_for("consistency")
    assert name in backend.json_prompts[0]
    assert "札の照合で参加者の順を決める" in backend.json_prompts[0]
    assert candidate["entity"]["premise_usage"]["institutions"] == [name]


@pytest.mark.parametrize("language,text", [
    ("ja", "年間500槽/日。"), ("ja", "年間 ５００ m³/日。"),
    ("ja", "月間20槽/年。"), ("ja", "日量4槽/時間。"),
    ("en", "Annual 500 qx/day."), ("en", "monthly output 20 qx per year."),
])
def test_rate_dimension_conflicts_are_deterministic_and_skip_judge(language, text):
    g = graph(language)
    candidate, _ = generate(g, raw(text))
    baseline, _ = verify(g, candidate)
    assert baseline.scores["consistency"] < 0.7
    deduction = next(d for d in baseline.deductions if d.code == "dimension_conflict")
    assert deduction.field == "facts[1]" and deduction.penalty > 0
    result, backend = verify(g, candidate, {"consistency": assessment(approve=True)})
    assert not result.passed and backend.json_prompts == []
    assert not result.premise_extension


@pytest.mark.parametrize("language,text", [
    ("ja", "年間500槽。"), ("ja", "日量500槽/日。"),
    ("ja", "年間を通じて日量500槽/日を比較容器で測る。"),
    ("ja", "観測期間は1年、容器量は500槽/日。"),
    ("en", "Daily 500 qx/day."), ("en", "Annual 500 qx/year."),
    ("en", "For one year, throughput was 500 qx/day."),
])
def test_totals_matching_rates_and_observation_windows_are_not_dimension_conflicts(language, text):
    g = graph(language)
    candidate, _ = generate(g, raw(text))
    result, _ = verify(g, candidate)
    assert not any(d.code == "dimension_conflict" for d in result.deductions)


@pytest.mark.parametrize("unit", ["槽", "qx", "m3/日"])
@pytest.mark.parametrize("declared", [True, False])
def test_every_measured_unit_receives_review_even_registered_or_undeclared(unit, declared):
    g = graph(society=False)  # Mandatory review must come from the quantity itself.
    item = raw(f"容器量は2.5{unit}を遠隔自動計測する。")
    if declared:
        item["premise_usage"] = {"units": [unit]}
    candidate, _ = generate(g, item)
    result, backend = verify(g, candidate, {"consistency": assessment(0.4, [
        {"field": "facts[1]", "code": "undefined_unit", "why": "前提には遠隔自動計測の能力がない。"}])})
    assert not result.passed
    assert any(d.code == "undefined_unit" and d.penalty > 0 for d in result.deductions)
    assert len(backend.json_prompts) == 1
    assert unit in result.premise_review["observed_units"]
    assert "including registered" in backend.json_prompts[0]


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


@pytest.mark.parametrize("declared", [True, False])
def test_extension_is_approved_recorded_and_available_in_real_exploration_path(tmp_path, declared):
    item = raw("比較容器の容量は2.5qx。", reason="比較容器の基準量を刻み棒の目盛で揃え、同じ基準量をqxと記す。")
    if declared:
        item["premise_usage"] = {"units": ["qx"]}
    def respond(prompt):
        if "CRITERION:" in prompt:
            return {"consistency": assessment(approve=True)}
        return {"candidates": [item]}
    backend = FakeLLMBackend(respond)
    verifier = RewardVerifier(load_reward_config(), judge=LLMJudge(backend),
                              contrasts=SimpleNamespace(get=lambda *args: []))
    config = load_explore_config()
    config["coverage"]["enabled"] = False
    config["generation"].update(candidates=1, max_rewrites=0)
    loop = ExplorationLoop(backend, tmp_path, BRIEF, AXES, config=config,
                           language="ja", verifier=verifier)
    loop.store.save(graph())
    result = loop.run(max_iterations=1, max_generation_calls=2)
    assert result.counters["accepted"] == 1
    assert result.counters["generation_calls"] == 2
    assert not validate_graph(result.graph, brief=BRIEF)
    assert "qx" in world_premises(result.graph)["technology"]["units"]
    assert result.graph["entities"][0]["world_premises"] == CONTRACT
    history = result.graph["entities"][-1]["premise_extension"]
    assert history["units"] == ["qx"] and history["reason"] == item["reason"]
    records = read_preference_log(tmp_path / "world/preferences.jsonl")
    adopted = next(r for r in records if r["type"] == "candidate" and r["decision"] == "accepted")
    review = adopted["result"]["premise_review"]
    assert review["proposal"] == history and review["extension_approved"]
    assert review["recorded"] and review["extension_status"] == "recorded"
    assert bool(review["inferred"]) is not declared
    follow, follow_backend = generate(result.graph, raw("比較容器の容量は3qx。", name="フィル容器所"))
    follow_result, _ = verify(result.graph, follow, {"consistency": assessment()})
    assert follow_result.scores["consistency"] == 1 and not follow_result.premise_extension
    assert '"qx"' in follow_backend.json_prompts[0]
    assert not follow_result.premise_review["proposal"]
    (tmp_path / "input").mkdir()
    (tmp_path / "input/input_brief.json").write_text(json.dumps(BRIEF))
    exported = json.loads(render_world_package(tmp_path)["world_json"].read_text())
    assert exported["premise_extensions"] == [{"entity": result.graph["entities"][-1]["id"], **history}]
    rolled_back = copy.deepcopy(result.graph)
    rolled_back["entities"].pop()
    assert "qx" not in world_premises(rolled_back)["technology"]["units"]


@pytest.mark.parametrize("response", [{}, {"consistency": {"score": 1}},
    {"consistency": {"score": True, "issues": []}},
    {"consistency": {"score": 2, "issues": []}},
    {"consistency": {"score": 1, "issues": ["bad"]}},
    {"consistency": {"score": 1, "issues": [{}]}},
    {"consistency": {"score": 1, "issues": [{"field": "facts[1]", "why": "contradiction"}]}}])
def test_quantity_review_missing_or_invalid_fails_and_is_logged(response):
    g = graph()
    candidate, _ = generate(g, raw("比較容器の容量は3槽。"))
    result, backend = verify(g, candidate, response)
    assert not result.passed and not result.premise_extension
    assert result.premise_review["state"] == "missing_or_invalid"
    assert any(d.code == "review_missing" for d in result.deductions)
    assert len(backend.json_prompts) == 1


def test_reason_omission_is_visible_and_cannot_extend_premises():
    g = graph()
    candidate, _ = generate(g, raw("比較容器の容量は3qx。", reason=""))
    result, _ = verify(g, candidate, {"consistency": assessment(approve=True)})
    assert not result.premise_extension
    assert not result.premise_review["reason_present"]
    assert result.premise_review["extension_status"] == "no_proposal"
    assert result.premise_review["proposal_state"] == "reason_missing"
    assert "qx" not in world_premises(g)["technology"]["units"]


@pytest.mark.parametrize("field", ["name", "summary", "facts"])
def test_quantities_in_every_field_trigger_consistency_review(field):
    g = graph(society=False)
    item = raw("照合台は照環紀3年に設置された。", "period")
    if field == "facts":
        item["facts"][1] = {"kind": "number", "text": "容器量は3槽。"}
    else:
        item[field] += " 容器量は3槽。"
    candidate, _ = generate(g, item)
    result, backend = verify(g, candidate, {"consistency": assessment()})
    assert result.premise_review["criteria"] == ["consistency"]
    assert "槽" in result.premise_review["observed_units"]
    assert result.premise_review["state"] == "reviewed"
    assert len(backend.json_prompts) == 1


@pytest.mark.parametrize("operator", OPERATORS)
def test_society_survives_every_generation_and_revision_prompt(operator):
    g = graph()
    backend = FakeLLMBackend({"candidates": [raw()]})
    runner = OperatorRunner(backend)
    candidate = runner.run(operator, g, None if operator == "premise" else "e2",
                           1, brief=BRIEF, axes=AXES)[0]
    revised = runner.revise(candidate, [], g, brief=BRIEF, axes=AXES)
    assert revised
    assert all("恒常的な外部統治権はない" in p for p in backend.json_prompts)


def test_bootstrap_society_is_recorded_as_a_derived_premise():
    g = new_graph("ja")
    item = raw(world_premises=CONTRACT)
    backend = FakeLLMBackend({"candidates": [item]})
    before = copy.deepcopy(BRIEF)
    candidate = OperatorRunner(backend).run("premise", g, n=1, brief=BRIEF, axes=AXES)[0]
    assert BRIEF == before and not g["entities"]
    assert candidate["entity"]["world_premises"]["society"] == CONTRACT["society"]
    result, _ = verify(g, candidate, {"consistency": assessment()})
    assert result.passed, result.to_dict()


def test_valid_measurement_review_without_extension_approval_cannot_register_a_unit():
    g = graph(society=False)
    candidate, _ = generate(g, raw("比較容器の容量は3qx。"))
    result, _ = verify(g, candidate, {"consistency": assessment()})
    assert not result.passed and not result.premise_extension
    assert result.premise_review["state"] == "reviewed"
    assert result.premise_review["extension_status"] == "unapproved"
    assert any(d.code == "extension_unapproved" for d in result.deductions)


@pytest.mark.parametrize("unit", ["m^3/日", "kg/年", "m3/日", "m³/日", "kg*日", "(m^3/日)^2", "kg/年^2"])
@pytest.mark.parametrize("declared", [False, True])
def test_registered_unit_algebra_needs_no_extension_approval(unit, declared):
    g = graph()
    g["entities"][0]["world_premises"]["technology"]["units"] = ["m^3", "kg", "日"]
    item = raw(f"比較容器の搬出量は3{unit}。")
    if declared:
        item["premise_usage"] = {"units": [unit]}
    candidate, _ = generate(g, item)
    result, backend = verify(g, candidate, {"consistency": assessment()})
    assert result.passed, result.to_dict()
    assert not result.premise_extension and not result.premise_review["proposal"]
    assert not any(d.code in {"undefined_unit", "extension_unapproved"} for d in result.deductions)
    assert len(backend.json_prompts) == 1  # measurability is still reviewed


@pytest.mark.parametrize("unit", ["人", "名", "people", "members"])
def test_declared_counter_is_outside_measurement_contract(unit):
    g = graph("en" if unit.isascii() else "ja", society=False)
    item = raw("照合台は照環紀3年に設置された。", "period", premise_usage={"units": [unit]})
    if unit.isascii():
        item["facts"][1] = {"kind": "procedure", "text": "The clerk removes a broken token after comparison."}
    candidate, _ = generate(g, item)
    result, backend = verify(g, candidate, {"consistency": assessment()})
    assert not candidate["entity"]["premise_usage"]["units"]
    assert not result.premise_review["observed_units"]
    assert not result.premise_review["proposal"]
    assert not result.deductions_for("consistency")
    assert backend.json_prompts == []
    # Also protect callers that bypass OperatorRunner normalization.
    candidate["entity"]["premise_usage"]["units"] = [unit]
    follow, follow_backend = verify(g, candidate, {"consistency": assessment()})
    assert follow_backend.json_prompts == []
    assert not follow.premise_review["proposal"]
    assert not follow.deductions_for("consistency")


APPROVAL_FORMS = [
    {"approve_premise_extension": "yes"},
    {"extension_approved": True},
    {"approval": "yes"},
    {"approvePremiseExtension": "yes"},
    {"premise-extension-approval": "yes"},
    {"premise_extension_approvals": {"units": [{"unit": "qx", "approved": "yes"}], "capabilities": []}},
    {"approvals": {"units": {"qx": True}}},
    {"extension_approvals": [{"unit": "qx", "decision": "yes"}]},
    {"approve_extension": [True]},
    {"premise_extension_approvals": {"units": ["yes"]}},
]


@pytest.mark.parametrize("approval", APPROVAL_FORMS)
def test_explicit_approval_variants_are_recorded_and_usable_next_iteration(tmp_path, approval):
    item = raw("比較容器の容量は2.5qx。", reason="比較容器の同じ基準量をqxと記して読み取る。")
    response = {"consistency": {"score": 1, "issues": [], **approval}}
    def respond(prompt):
        return response if "CRITERION:" in prompt else {"candidates": [item]}
    backend = FakeLLMBackend(respond)
    verifier = RewardVerifier(load_reward_config(), judge=LLMJudge(backend),
                              contrasts=SimpleNamespace(get=lambda *args: []))
    config = load_explore_config()
    config["coverage"]["enabled"] = False
    config["generation"].update(candidates=1, max_rewrites=0)
    loop = ExplorationLoop(backend, tmp_path, BRIEF, AXES, config=config, language="ja", verifier=verifier)
    loop.store.save(graph())
    result = loop.run(max_iterations=1, max_generation_calls=2)
    assert result.counters["accepted"] == 1
    assert result.counters["generation_calls"] == 2
    assert "qx" in world_premises(result.graph)["technology"]["units"]
    assert not validate_graph(result.graph, brief=BRIEF)
    candidate_record = next(r for r in read_preference_log(tmp_path / "world/preferences.jsonl")
                            if r["type"] == "candidate" and r["decision"] == "accepted")
    review = candidate_record["result"]["premise_review"]
    assert review["raw_response"] == response and review["extension_status"] == "recorded"
    next_item = raw("交換棚の許容量は3qxで、照合の前に比較容器を満たす。", name="フィル容器所",
                    summary="交換前に当番が空の容器を傾け、縁の欠けを検査する。")
    next_item["facts"][0]["text"] = "交換棚の呼称はフィル棚。"
    next_item["facts"][2]["text"] = "検査台には欠片を集める浅い受け皿を置く。"
    next_candidate, next_backend = generate(result.graph, next_item)
    next_result, _ = verify(result.graph, next_candidate, {"consistency": assessment()})
    assert next_result.passed, next_result.to_dict()
    assert not next_result.premise_extension and not next_result.premise_review["proposal"]
    assert '"qx"' in next_backend.json_prompts[0]
    (tmp_path / "input").mkdir()
    (tmp_path / "input/input_brief.json").write_text(json.dumps(BRIEF))
    exported = json.loads(render_world_package(tmp_path)["world_json"].read_text())
    assert exported["premise_extensions"] == [{"entity": result.graph["entities"][-1]["id"],
                                              **result.graph["entities"][-1]["premise_extension"]}]
    prompt = next(p for p in backend.json_prompts if "CRITERION:" in p)
    assert '"unit": "qx"' in prompt and '"approved": "<yes or no>"' in prompt
    assert "existing dimension" in prompt


@pytest.mark.parametrize("unit", ["m", "mm", "メートル"])
def test_same_measurable_dimension_can_be_explicitly_approved_without_unit_catalog(unit):
    g = graph()
    g["entities"][0]["world_premises"]["technology"]["units"] = ["m^3", "kg", "日"]
    candidate, _ = generate(g, raw(f"刻み棒で測る長さは3{unit}。", premise_usage={"units": [unit]},
        reason="既存の刻み棒の目盛を比較して長さを読む。同じ長さを別の表記で記す。"))
    result, _ = verify(g, candidate, {"consistency": {"score": 1, "issues": [],
        "premise_extension_approvals": {"units": [{"unit": unit, "approved": "yes"}]}}})
    assert result.passed and result.premise_extension["units"] == [unit]
    candidate["entity"]["premise_extension"] = result.premise_extension
    g["entities"].append(candidate["entity"])
    assert unit in world_premises(g)["technology"]["units"]


@pytest.mark.parametrize("approval", [
    {"approved": "no"}, {"approved": "yesterday"}, {"approved": 1},
    {"approvals": {"units": []}},
    {"approvals": {"units": [{"unit": "other", "approved": "yes"}]}},
    {"approvals": {"units": [{"unit": "qx", "approved": "no"}]}, "approved": True},
    {"approvals": {"units": [{"unit": "qx", "approved": "yes"}, {"unit": "qx", "approved": False}]}},
    {"approvals": {"units": [{"unit": "qx", "approved": "yes"}], "capabilities": []}},
])
def test_missing_conflicting_and_negative_item_approvals_cannot_add_capabilities(approval):
    g = graph()
    candidate, _ = generate(g, raw("比較容器の容量は3qx。", premise_usage={"units": ["qx"],
        "technologies": ["交互比較法"]}, reason="比較容器を交互に入れ替えて量を読む。"))
    result, _ = verify(g, candidate, {"consistency": {"score": 1, "issues": [], **approval}})
    assert not result.passed and not result.premise_extension
    assert result.premise_review["extension_status"] == "unapproved"


def test_item_yes_for_unit_and_capability_is_approved_but_contradictions_still_fail():
    g = graph()
    candidate, _ = generate(g, raw("比較容器の容量は3qx。", premise_usage={"units": ["qx"],
        "technologies": ["交互比較法"]}, reason="比較容器を交互に入れ替えて量を読む。"))
    approvals = {"units": [{"unit": "qx", "approved": "yes"}],
                 "capabilities": [{"capability": "交互比較法", "approved": True}]}
    result, backend = verify(g, candidate, {"consistency": {"score": 1, "issues": [],
        "premise_extension_approvals": approvals}})
    assert result.passed and result.premise_extension["capabilities"] == ["交互比較法"]
    assert '"capability": "交互比較法"' in backend.json_prompts[0]
    contradicted, _ = verify(g, candidate, {"consistency": {"score": 0.4, "issues": [
        {"field": "facts[1]", "code": "undefined_technology", "why": "測定手段が限界を超える。"}],
        "premise_extension_approvals": approvals}})
    assert not contradicted.passed and not contradicted.premise_extension


def test_judge_response_is_logged_before_parsing_even_when_invalid(caplog):
    g = graph()
    candidate, _ = generate(g, raw("比較容器の容量は3qx。"))
    response = {"consistency": {"score": 1, "approval": "yes"}}
    with caplog.at_level("DEBUG", logger="src.world.verify"):
        result, _ = verify(g, candidate, response)
    assert result.premise_review["raw_response"] == response
    assert "world judge response" in caplog.text and "approval" in caplog.text
    assert not result.passed and not result.premise_extension


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


def test_semantic_judge_can_penalize_paraphrased_effect_without_new_call():
    g = graph()
    candidate, _ = generate(g, raw(summary="すべての負担が解消される。"))
    result, backend = verify(g, candidate, {"consistency": assessment(), "specificity": {
        "score": 0.4, "issues": [{"field": "summary", "code": "purpose_without_mechanism",
                                   "why": "負担が消える手順や観測結果がない。"}]}}, criteria=["specificity"])
    assert not result.passed
    assert any(d.code == "purpose_without_mechanism" and d.penalty > 0 for d in result.deductions)
    assert len(backend.json_prompts) == 1
    assert "protection" in backend.json_prompts[0]


@pytest.mark.parametrize("registered,unit", [
    (["qx"], "qx²"), (["qx^3"], "qx3"), (["qx^3"], "ｑｘ³"),
    (["qx^3", "槽"], "qx^6/槽"), (["qx/uv", "uv/zr"], "qx/zr"),
    (["qx/uv"], "(qx/uv)^2"),
])
def test_unit_algebra_works_for_invented_symbols_and_registered_composites(registered, unit):
    g = graph()
    g["entities"][0]["world_premises"]["technology"]["units"] = registered
    candidate, _ = generate(g, raw(f"比較容器の容量は3{unit}。", premise_usage={"units": [unit]}))
    result, _ = verify(g, candidate, {"consistency": assessment()})
    assert result.passed, result.to_dict()
    assert not result.premise_review["proposal"]
    assert not any(d.code == "undefined_unit" for d in result.deductions)


@pytest.mark.parametrize("registered,unit", [
    (["qx^3"], "qx"), (["qx"], "QX"), (["qx/uv"], "qx"),
    (["qx"], "uv/uv"), (["qx"], "(qx/uv)^2"), (["qx"], "qx^"),
])
def test_algebra_cannot_register_unknown_factors_roots_or_malformed_expressions(registered, unit):
    g = graph()
    g["entities"][0]["world_premises"]["technology"]["units"] = registered
    candidate, _ = generate(g, raw(f"比較容器の容量は3{unit}。", premise_usage={"units": [unit]}))
    result, _ = verify(g, candidate, {"consistency": assessment()})
    assert not result.passed and not result.premise_extension
    assert result.premise_review["proposal"]
    assert any(d.code == "extension_unapproved" for d in result.deductions)


def test_unparsed_backend_response_text_is_saved_even_when_json_review_is_invalid(caplog):
    class RawResponseBackend(FakeLLMBackend):
        def generate_json(self, *args, **kwargs):
            self.last_response_meta = {"response": 'approval=yes; units=[qx]'}
            return super().generate_json(*args, **kwargs)
    g = graph()
    candidate, _ = generate(g, raw("比較容器の容量は3qx。"))
    backend = RawResponseBackend({})
    verifier = RewardVerifier(load_reward_config(), judge=LLMJudge(backend))
    with caplog.at_level("DEBUG", logger="src.world.verify"):
        result = verifier.verify(g, candidate, brief=BRIEF, axes=AXES)
    assert result.premise_review["raw_response"] == {}
    assert result.premise_review["raw_response_text"] == 'approval=yes; units=[qx]'
    assert 'approval=yes; units=[qx]' in caplog.text
    assert not result.passed and not result.premise_extension


def test_top_level_approval_is_read_and_conflicting_envelopes_are_rejected():
    candidate, _ = generate(graph(), raw("比較容器の容量は3qx。"))
    response = {"consistency": {"score": 1, "issues": []}, "extension_approval": "yes"}
    result, _ = verify(graph(), candidate, response)
    assert result.passed and result.premise_extension["units"] == ["qx"]
    response["consistency"]["extension_approval"] = "no"
    refused, _ = verify(graph(), candidate, response)
    assert not refused.passed and not refused.premise_extension
