"""Generate a bounded world contract before entity exploration."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from .criteria import contract_terms, outside_terms, real_world_check
from .schemas import load_schema
from .structured import generate_structured, StructuredFailure, StructuredResult
from .premises import CONTRACT_ID, normalize_premises, world_premises

PROMPT_PATH = Path(__file__).resolve().parents[2] / "config/prompts/world/contract.yaml"


def establish_contract(backend, graph, brief, axes, *, max_attempts=3, max_conversions=2, raw_input=""):
    """Mutate only the contract records; never create exploration entities.

    k is the total number of attempts, including the initial call. Completed
    stages (including failures) are reused on resume. Legacy contracts win.
    """
    if graph.get("contract_stage"):
        stage = graph["contract_stage"]
        if stage["status"] == "failed":
            failure = stage.get("structured_failure")
            if failure:
                raise StructuredFailure("world_contract", StructuredResult(
                    None, failure["attempts"], failure["violations"], 0.0, "constrained"))
            raise ValueError(f"world_contract: previously failed: {stage.get('errors')}")
        return stage
    if world_premises(graph):
        graph["contract_stage"] = {"status": "success", "attempts": 0,
                                   "reused": True, "checks_enabled": True,
                                   "disabled_checks": [], "errors": []}
        return graph["contract_stage"]
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("structured.max_attempts must be a positive integer")
    prompts = yaml.safe_load(PROMPT_PATH.read_text(encoding="utf-8"))
    # Only input-derived statements, constraints and axes; no graph context.
    context = {
        "statements": [{"id": s["id"], "text": str(s.get("text", ""))[:160]}
                       for s in brief.get("statements", [])[:12]],
        "constraints": [str(c)[:160] for c in brief.get("constraints", [])[:8]],
        "axes": [{k: str(a.get(k, ""))[:160] for k in ("name", "meaning")}
                 for a in axes[:16]],
    }
    prompt = prompts["user"].format(
        language=graph["meta"]["language"],
        context=json.dumps(context, ensure_ascii=False, separators=(",", ":")),
        errors="(none)")
    def validate_terms(data):
        judged = real_world_check(backend, contract_terms(data), language=graph["meta"]["language"],
            max_attempts=max_attempts, max_conversions=max_conversions)
        if judged.data is None:
            return [{"path": "$", "expected": "valid real_world_check", "actual": data,
                     "message": "no_outside_premises: " + json.dumps(judged.violations[-1], ensure_ascii=False)}]
        return [{"path": "$", "expected": "terms specified in original input", "actual": item["term"],
                 "message": "no_outside_premises: " + item["term"] + ": " + item["reason"]}
                for item in outside_terms(judged.data, raw_input)]

    result = generate_structured(backend, prompt, load_schema("world_contract"),
        task="world_contract", max_attempts=max_attempts, max_conversions=max_conversions,
        system_prompt=prompts["system"], content_validator=validate_terms)
    success = result.data is not None
    graph["contract_stage"] = {"status": "success" if success else "failed",
        "attempts": result.attempts, "checks_enabled": success, "disabled_checks": [],
        "errors": [{"attempt": i, "errors": [v["message"] for v in violations]}
                   for i, violations in enumerate(result.violations, 1)],
        **({"structured_failure": result.failure("world_contract")} if not success else {})}
    if not success:
        raise StructuredFailure("world_contract", result)
    graph["world_contract"] = {
        "id": CONTRACT_ID, "scale": "world",
        "world_premises": normalize_premises(result.data),
        "provenance": {"statement_ids": [s["id"] for s in context["statements"]],
                       "derived_from": [],
                       "reason": "Contract derived from input brief and world axes"}}

    return graph["contract_stage"]
