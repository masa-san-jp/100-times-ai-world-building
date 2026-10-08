"""Synthetic regression cases run through the existing criterion checks."""

import copy
import json
import re
from collections import Counter
from pathlib import Path

import pytest
import yaml

from src.llm.fake import FakeLLMBackend
from src.world.builder import EntityBuilder
from src.world.graph import new_graph
from src.world.world_criteria import load_world_criteria_config, world_status


ROOT = Path(__file__).resolve().parents[1]
CASES = [case for path in sorted((ROOT / "tests/fixtures/criteria_cases").glob("*.json"))
         for case in json.loads(path.read_text(encoding="utf-8"))]
CRITERIA = yaml.safe_load((ROOT / "config/world/criteria.yaml").read_text(encoding="utf-8"))


def test_case_collection_covers_every_criterion():
    assert CASES
    assert len({case["id"] for case in CASES}) == len(CASES)
    assert {case["criterion"] for case in CASES} == set(CRITERIA)
    counts = Counter((case["criterion"], case["expected"]) for case in CASES)
    for criterion in CRITERIA:
        for expected in ("pass", "fail"):
            assert counts[criterion, expected] >= 3, (criterion, expected)
    for case in CASES:
        assert set(case) == {"id", "criterion", "check", "input", "expected", "note"}
        assert case["check"] in CRITERIA[case["criterion"]]["checks"] or (
            case["criterion"] == "faithful" and case["check"] == "world.faithful")
        assert isinstance(case["input"], dict)
        assert case["note"].strip()
        assert case["expected"] in {"pass", "fail"}


def run_entity_case(data, criterion, monkeypatch):
    graph = new_graph(data.get("language", "en"))
    graph["entities"] = data.get("entities", [])
    if data.get("contract"):
        graph["world_contract"] = {"world_premises": data["contract"]}
    brief = data.get("brief", {"statements": [{"id": "s1", "text": "Records are retained."}]})
    axes = [{"id": "a1", "name": "Records", "meaning": "Record properties", "weight": 1}]
    outputs = {
        "type": {"type": "concept"},
        "grounding": {"statement_ids": ["s1"], "derived_from": [], "reason": ""},
        "name": {"name": "Zevral"},
        "axes": {"axes": ["a1"]},
        "summary": {"summary": "The records retain measured capacity alongside their identifiers."},
        "relations": {"relations": []},
        "review": {"verdicts": {key: True for key in
                   ("consistent", "objective", "no_outside_premises")}, "issues": []},
        **data.get("outputs", {}),
    }
    facts = data.get("facts", [
        {"subject": "Capacity", "value": 12, "unit": "q2v", "fact": "Capacity is 12 q2v."},
        {"name": "Nuvrel", "fact": "Nuvrel identifies retained records."},
    ])
    # Isolate fact checks and the entity gate from the mandatory proper-name
    # slot, as in the existing issue 70 gate tests. Production planning is unchanged.
    if "fact_kinds" in data:
        monkeypatch.setattr("src.world.builder.fact_plan", lambda *args: data["fact_kinds"])

    def respond(prompt):
        if "STEP: real_world_check\n" in prompt:
            terms = json.JSONDecoder().raw_decode(prompt.split("TERMS:\n", 1)[1])[0]
            return {"items": [{"term": term,
                "category": data.get("categories", {}).get(term, "invented"),
                "reason": "Synthetic classification for deterministic checks."} for term in terms]}
        step = re.search(r"^STEP: (.+)$", prompt, re.M).group(1)
        if step in {"fact_element", "fact_text"}:
            slot = int(re.search(r"^SLOT: (.+)$", prompt, re.M).group(1))
            return ({"fact": facts[slot]["fact"]} if step == "fact_text" else
                    {k: v for k, v in facts[slot].items() if k != "fact"})
        return outputs[step]

    result = EntityBuilder(FakeLLMBackend(respond), {
        "build": {"max_step_attempts": 1, "review_rounds": 0},
        "structured": {"max_attempts": 1, "max_conversions": 0},
    }).build(graph, "premise", None, brief=brief, axes=axes,
             contract=data.get("contract", {}), frontier_axis=None,
             raw_input=data.get("raw_input", ""))
    checks = [check for row in result.steps for check in row.checks
              if check["criterion"] == criterion]
    assert checks, result.failure
    if result.entity is None:
        assert any(not check["ok"] for check in checks), result.failure
    return all(check["ok"] for check in checks)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_criteria_case(case, monkeypatch):
    data = copy.deepcopy(case["input"])
    if case["check"].startswith("world."):
        result = world_status(data["graph"], data.get("axes", []), data.get("brief", {}),
                              data.get("contract"), load_world_criteria_config())
        rows = [row for metric, row in result["criteria"].items()
                if metric.split(".")[0] == case["criterion"]]
        assert rows
        passed = all(row["met"] for row in rows)
    else:
        passed = run_entity_case(data, case["criterion"], monkeypatch)
    assert ("pass" if passed else "fail") == case["expected"], case["note"]
