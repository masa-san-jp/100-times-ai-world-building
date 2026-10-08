#!/usr/bin/env python3
"""Validate real_world_check on a real backend; never invoked by CI.

    .venv/bin/python scripts/validate_judges.py --model <model>

Backend, generation options and structured retry limits come from the existing
config/ollama_config.yaml. Change its backend setting to use Anthropic. Output
is JSON containing each classification and violation result, classification
and violation accuracies, and false true/false violation counts.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.llm.factory import build_backend_clients
from src.pipeline import ConfiguredBackend
from src.utils import load_config
from src.world.criteria import outside_terms, real_world_check
from src.world.structured import StructuredFailure


CASE_PATH = ROOT / "tests/fixtures/judge_cases/real_world.json"


def validate_cases(backend, cases, *, language, max_attempts, max_conversions):
    results = []
    for case in cases:
        result = real_world_check(backend, [case["term"]], language=language,
            max_attempts=max_attempts, max_conversions=max_conversions)
        if result.data is None:
            raise StructuredFailure("real_world_check", result)
        item = result.data["items"][0]
        violation = bool(outside_terms(result.data, case["raw_input"]))
        results.append({**case, "category": item["category"], "reason": item["reason"],
            "violation": violation,
            "category_correct": item["category"] == case["expected_category"],
            "violation_correct": violation == case["expected_violation"]})
    total = len(results)
    return {"cases": results, "summary": {
        "total": total,
        "category_accuracy": sum(row["category_correct"] for row in results) / total,
        "violation_accuracy": sum(row["violation_correct"] for row in results) / total,
        "false_true": sum(row["violation"] and not row["expected_violation"] for row in results),
        "false_false": sum(not row["violation"] and row["expected_violation"] for row in results),
    }}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    args = parser.parse_args(argv)
    config = load_config(str(ROOT / "config/ollama_config.yaml"))
    clients = build_backend_clients(config.get("backend", "ollama"),
        {"generation": args.model}, config.get("server") or {}, config.get("anthropic") or {})
    backend = ConfiguredBackend(clients["generation"], config.get("generation") or {})
    structured = (config.get("engine") or {}).get("structured") or {}
    cases = json.loads(CASE_PATH.read_text(encoding="utf-8"))
    report = validate_cases(backend, cases, language="en",
        max_attempts=structured.get("max_attempts", 3),
        max_conversions=structured.get("max_conversions", 2))
    print(json.dumps({"model": args.model, "backend": config.get("backend", "ollama"),
                      **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
