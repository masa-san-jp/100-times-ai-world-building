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
