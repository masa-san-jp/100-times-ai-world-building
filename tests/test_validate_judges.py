"""Judge validation runs in CI using fake backends only."""

import json
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from scripts import validate_judges
from src.llm.fake import FakeLLMBackend
from src.world.criteria import outside_terms
from src.world.schemas import step_schema
from src.world.structured import StructuredFailure


CASES = json.loads(validate_judges.CASE_PATH.read_text(encoding="utf-8"))


def response(term, category):
    return {"items": [{"term": term, "category": category, "reason": "Fake classification."}]}


def run(backend, cases=CASES, max_attempts=1):
    return validate_judges.validate_cases(backend, cases, language="en",
                                        max_attempts=max_attempts, max_conversions=0)


def test_judge_fixture_has_real_and_invented_terms_and_all_categories():
    assert len({case["id"] for case in CASES}) == len(CASES)
    counts = Counter(case["expected_category"] for case in CASES)
    categories = step_schema("real_world_check", terms=["Qevrul"])["properties"]["items"]["items"]["properties"]["category"]["enum"]
    assert set(counts) == set(categories)
    assert counts["invented"] >= 15
    assert sum(count for category, count in counts.items() if category.startswith("real_")) >= 15
    for case in CASES:
        assert set(case) == {"id", "term", "raw_input", "expected_category", "expected_violation", "note"}
        assert type(case["expected_violation"]) is bool
        assert case["note"].strip()
        assert bool(outside_terms(response(case["term"], case["expected_category"]),
                                  case["raw_input"])) == case["expected_violation"]
    assert any(case["expected_category"].startswith("real_") and not case["expected_violation"]
               for case in CASES)


def test_all_judge_cases_execute_through_structured_fake_backend():
    backend = FakeLLMBackend([response(case["term"], case["expected_category"]) for case in CASES])
    report = run(backend)
    assert report["summary"] == {"total": len(CASES), "category_accuracy": 1.0,
        "violation_accuracy": 1.0, "false_true": 0, "false_false": 0}
    assert len(report["cases"]) == len(backend.schema_calls) == len(CASES)
    for case, actual, call in zip(CASES, report["cases"], backend.schema_calls):
        assert actual["id"] == case["id"]
        assert actual["term"] == case["term"]
        assert actual["category"] == case["expected_category"]
        assert actual["violation"] == case["expected_violation"]
        assert actual["reason"] == "Fake classification."
        assert "STEP: real_world_check\n" in call["prompt"]
        assert call["schema"] == step_schema("real_world_check", terms=[case["term"]])


def test_category_accuracy_and_violation_errors_are_measured_separately():
    cases = [
        {"id": "invented-false-true", "term": "Qevrul", "raw_input": "",
         "expected_category": "invented", "expected_violation": False},
        {"id": "unit-false-false", "term": "kg", "raw_input": "",
         "expected_category": "real_unit", "expected_violation": True},
        {"id": "allowed-unit", "term": "kg", "raw_input": "Use Ｋ Ｇ for mass.",
         "expected_category": "real_unit", "expected_violation": False},
        {"id": "wrong-real-category", "term": "Nairobi", "raw_input": "",
         "expected_category": "real_place_name", "expected_violation": True},
    ]
    backend = FakeLLMBackend([response("Qevrul", "real_person_name"), response("kg", "general_word"),
                              response("kg", "real_unit"), response("Nairobi", "real_person_name")])
    report = run(backend, cases)
    assert report["summary"] == {"total": 4, "category_accuracy": 0.25,
        "violation_accuracy": 0.5, "false_true": 1, "false_false": 1}
    assert report["cases"][2]["violation"] is False
    assert report["cases"][3]["category_correct"] is False
    assert report["cases"][3]["violation_correct"] is True


def test_invalid_judge_output_is_repaired_using_existing_harness():
    case = CASES[0]
    backend = FakeLLMBackend([response(case["term"], "unknown-category"),
                              response(case["term"], case["expected_category"])])
    assert run(backend, [case], max_attempts=2)["summary"]["category_accuracy"] == 1.0
    assert len(backend.schema_calls) == 2
    assert "REPAIR INSTRUCTIONS" in backend.schema_calls[1]["prompt"]


def test_exhausted_judge_failure_is_not_counted_as_a_classification():
    with pytest.raises(StructuredFailure) as exc:
        run(FakeLLMBackend({"items": []}), [CASES[0]])
    assert exc.value.task == "real_world_check"


@pytest.mark.parametrize("backend_name", ["ollama", "anthropic"])
def test_cli_uses_requested_model_and_existing_backend_configuration(monkeypatch, capsys, backend_name):
    config = {"backend": backend_name, "server": {"port": 11434},
        "anthropic": {"timeout": 900}, "generation": {"temperature": 0.2, "think": None},
        "engine": {"structured": {"max_attempts": 2, "max_conversions": 0}}}
    backend = FakeLLMBackend([response(case["term"], case["expected_category"]) for case in CASES])
    calls = []

    def build(name, models, server, anthropic):
        calls.append((name, models, server, anthropic))
        return {"generation": backend}

    monkeypatch.setattr(validate_judges, "load_config", lambda path: config)
    monkeypatch.setattr(validate_judges, "build_backend_clients", build)
    assert validate_judges.main(["--model", "requested-model"]) == 0
    assert calls == [(backend_name, {"generation": "requested-model"},
                      config["server"], config["anthropic"])]
    output = json.loads(capsys.readouterr().out)
    assert output["model"] == "requested-model"
    assert output["backend"] == backend_name
    assert output["summary"]["total"] == len(CASES)
    assert output["summary"]["category_accuracy"] == 1.0
    assert all(call["temperature"] == 0.2 and "think" not in call for call in backend.schema_calls)


def test_script_help_runs_from_outside_repository_without_backend(tmp_path):
    import sys

    script = Path(validate_judges.__file__).resolve()
    result = subprocess.run([sys.executable, str(script), "--help"], cwd=tmp_path,
                             capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "--model" in result.stdout
    assert "--task" in result.stdout


RESTATEMENT_CASES = json.loads(validate_judges.RESTATEMENT_CASE_PATH.read_text(encoding="utf-8"))


def test_restatement_fixture_has_both_kinds_of_pairs():
    assert len({case["id"] for case in RESTATEMENT_CASES}) == len(RESTATEMENT_CASES)
    restated = [c for c in RESTATEMENT_CASES if c["expected_restates"] != "none"]
    fresh = [c for c in RESTATEMENT_CASES if c["expected_restates"] == "none"]
    assert len(restated) >= 10 and len(fresh) >= 10
    for case in RESTATEMENT_CASES:
        ids = [f"f{i}" for i in range(1, len(case["candidates"]) + 1)]
        assert case["expected_restates"] in ["none", *ids] and case["note"].strip()


def test_restatement_cases_execute_through_the_fake_backend():
    backend = FakeLLMBackend([{"restates": c["expected_restates"], "reason": "Fake."} for c in RESTATEMENT_CASES])
    report = validate_judges.validate_restatement_cases(backend, RESTATEMENT_CASES, language="en",
                                                        max_attempts=1, max_conversions=0)
    assert report["summary"] == {"total": len(RESTATEMENT_CASES), "accuracy": 1.0,
                                 "false_restates": 0, "missed_restates": 0}
    assert all("STEP: restatement_check\n" in call["prompt"] for call in backend.schema_calls)


def test_restatement_errors_are_counted_by_direction():
    cases = [{"id": "a", "fact": "x", "candidates": ["y"], "expected_restates": "f1"},
             {"id": "b", "fact": "x", "candidates": ["y"], "expected_restates": "none"}]
    backend = FakeLLMBackend([{"restates": "none", "reason": "Fake."}, {"restates": "f1", "reason": "Fake."}])
    summary = validate_judges.validate_restatement_cases(backend, cases, language="en",
                                                         max_attempts=1, max_conversions=0)["summary"]
    assert summary == {"total": 2, "accuracy": 0.0, "false_restates": 1, "missed_restates": 1}
