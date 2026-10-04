"""Generate a bounded world contract before entity exploration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

import yaml
from loguru import logger

from .premises import CONTRACT_ID, normalize_premises, premise_errors, world_premises

PROMPT_PATH = Path(__file__).resolve().parents[2] / "config/prompts/world/contract.yaml"


def establish_contract(backend, graph, brief, axes, *, max_attempts=3):
    """Mutate only the contract records; never create exploration entities.

    k is the total number of attempts, including the initial call. Completed
    stages (including failures) are reused on resume. Legacy contracts win.
    """
    if graph.get("contract_stage"):
        return graph["contract_stage"]
    if world_premises(graph):
        graph["contract_stage"] = {"status": "success", "attempts": 0,
                                   "reused": True, "checks_enabled": True,
                                   "disabled_checks": [], "errors": []}
        return graph["contract_stage"]
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("contract.max_attempts must be a positive integer")
    prompts = yaml.safe_load(PROMPT_PATH.read_text(encoding="utf-8"))
    # Only input-derived statements, constraints and axes; no graph context.
    context = {
        "statements": [{"id": s["id"], "text": str(s.get("text", ""))[:160]}
                       for s in brief.get("statements", [])[:12]],
        "constraints": [str(c)[:160] for c in brief.get("constraints", [])[:8]],
        "axes": [{k: str(a.get(k, ""))[:160] for k in ("name", "meaning")}
                 for a in axes[:16]],
    }
    history = []
    errors = []
    for attempt in range(1, max_attempts + 1):
        prompt = prompts["user"].format(
            language=graph["meta"]["language"],
            context=json.dumps(context, ensure_ascii=False, separators=(",", ":")),
            errors="; ".join(errors) or "(none)")
        try:
            response = backend.generate_json(prompt, system_prompt=prompts["system"])
            errors = premise_errors(response)
            if isinstance(response, Mapping) and "society" not in response:
                errors.append("society needs description and institutions")
        except Exception as exc:
            response = None
            errors = [f"{type(exc).__name__}: {str(exc)[:200]}"]
        history.append({"attempt": attempt, "errors": list(errors)})
        logger.info("world contract attempt {}: {}", attempt, errors or "success")
        if not errors:
            graph["world_contract"] = {
                "id": CONTRACT_ID, "scale": "world",
                "world_premises": normalize_premises(response),
                "provenance": {"statement_ids": [s["id"] for s in context["statements"]],
                               "derived_from": [],
                               "reason": "Contract derived from input brief and world axes"},
            }
            break
    success = not errors
    graph["contract_stage"] = {"status": "success" if success else "failed",
                               "attempts": attempt, "checks_enabled": success,
                               "disabled_checks": [] if success else [
                                   "calendar", "technology", "units", "institutions"],
                               "errors": history}
    if not success:
        logger.info("World contract unavailable: calendar, technology, unit and institution contract checks disabled; continuing exploration")
    return graph["contract_stage"]
