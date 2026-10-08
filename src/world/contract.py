"""Assemble the world contract from independently generated and checked items."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from .criteria import outside_terms, real_world_check
from .schemas import load_schema
from .structured import generate_structured, StructuredFailure, StructuredResult
from .premises import CONTRACT_ID, normalize_premises, world_premises

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config/world/contract.yaml"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "config/prompts/world/contract_items.yaml"

# Item, section, destination, output key, count setting, checked term key.
ITEMS = (
    ("calendar_name", "calendar", "name", "name", None, "name"),
    ("calendar_origin", "calendar", "origin", "origin", None, None),
    ("calendar_marker", "calendar", "markers", "marker", "n_markers", "marker"),
    ("technology_description", "technology", "description", "description", None, None),
    ("capability", "technology", "capabilities", "capability", "n_capabilities", "capability"),
    ("unit", "technology", "units", None, "n_units", "symbol"),
    ("society_description", "society", "description", "description", None, None),
    ("institution", "society", "institutions", None, "n_institutions", "name"),
)


class ContractBuilder:
    def __init__(self, backend, *, max_attempts=3, max_conversions=2, raw_input=""):
        self.backend = backend
        self.max_attempts = max_attempts
        self.max_conversions = max_conversions
        self.raw_input = raw_input
        self.cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        self.max_item_attempts = self.cfg.get("max_item_attempts", 4)
        for key, value, minimum in (("structured.max_attempts", max_attempts, 1),
                                    ("structured.max_conversions", max_conversions, 0),
                                    ("max_item_attempts", self.max_item_attempts, 1)):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{key} must be an integer >= {minimum}")
        schema = load_schema("world_contract")
        for _, section, field, _, count_key, _ in ITEMS:
            if count_key:
                count = self.cfg[count_key]
                bounds = schema["properties"][section]["properties"][field]
                if (isinstance(count, bool) or not isinstance(count, int)
                        or not bounds.get("minItems", 0) <= count <= bounds["maxItems"]):
                    raise ValueError(f"{count_key} must satisfy world_contract array bounds")
        self.prompts = yaml.safe_load(PROMPT_PATH.read_text(encoding="utf-8"))

    def build(self, graph, brief, axes):
        context = {
            "statements": [{"id": s["id"], "text": str(s.get("text", ""))[:160]}
                           for s in brief.get("statements", [])[:12]],
            "constraints": [str(c)[:160] for c in brief.get("constraints", [])[:8]],
            "axes": [{k: str(a.get(k, ""))[:160] for k in ("name", "meaning")}
                     for a in axes[:16]],
        }
        contract = {"calendar": {}, "technology": {}, "society": {}}
        stage = {"status": "failed", "attempts": 0, "checks_enabled": False,
                 "disabled_checks": [], "errors": [], "steps": [], "metrics": {"steps": {}}}
        language = graph["meta"]["language"]
        for item, section, field, output_key, count_key, term_key in ITEMS:
            if count_key:
                contract[section][field] = []
            for slot in range(self.cfg[count_key] if count_key else 1):
                entry = stage["metrics"]["steps"].setdefault(item,
                    {"calls": 0, "attempts": {}, "reasons": {}, "failures": 0})
                check_calls = 0

                def validate_item(data):
                    nonlocal check_calls
                    if not term_key:
                        return []
                    term = data[term_key]
                    violations = []
                    judged = real_world_check(self.backend, [term], language=language,
                        max_attempts=self.max_attempts, max_conversions=self.max_conversions)
                    check_calls += judged.attempts + judged.conversions
                    if judged.data is None:
                        violations.append({"path": "$", "expected": "valid real_world_check",
                            "actual": data, "message": "no_outside_premises: " +
                            json.dumps(judged.violations[-1], ensure_ascii=False)})
                    else:
                        violations.extend({"path": f'$["{term_key}"]',
                            "expected": "terms specified in original input", "actual": v["term"],
                            "category": v["category"], "reason": v["reason"],
                            "message": f"no_outside_premises: {v['term']}: {v['category']}: {v['reason']}"}
                            for v in outside_terms(judged.data, self.raw_input))
                    if count_key:
                        existing = contract[section][field]
                        terms = [v[term_key] for v in existing] if output_key is None else existing
                        if term in terms:
                            violations.append({"path": f'$["{term_key}"]',
                                "expected": "unique entry in this contract list", "actual": term,
                                "message": f"duplicate: {term} already appears in {section}.{field}"})
                    return violations

                prompt = self.prompts["common"]["user"].format(
                    language=language, context=json.dumps(context, ensure_ascii=False, separators=(",", ":")),
                    contract=json.dumps(contract, ensure_ascii=False), item=item,
                    slot=slot if count_key else None, instruction=self.prompts["items"][item])
                result = generate_structured(self.backend, prompt, load_schema("contract/" + item),
                    task="contract/" + item, max_attempts=self.max_item_attempts,
                    max_conversions=self.max_conversions,
                    system_prompt=self.prompts["common"]["system"], content_validator=validate_item)
                calls = result.attempts + result.conversions + check_calls
                stage["attempts"] += result.attempts
                entry["calls"] += calls
                attempt_key = str(result.attempts)
                entry["attempts"][attempt_key] = entry["attempts"].get(attempt_key, 0) + 1
                reasons = []
                for attempt, violations in enumerate(result.violations, 1):
                    if not violations:
                        continue
                    messages = [v["message"] for v in violations]
                    stage["errors"].append({"item": item, "slot": slot if count_key else None,
                                             "attempt": attempt, "errors": messages})
                    reasons.extend(messages)
                    for message in messages:
                        entry["reasons"][message] = entry["reasons"].get(message, 0) + 1
                stage["steps"].append({"step": item, "slot": slot if count_key else None,
                    "attempts": result.attempts, "calls": calls, "accepted": result.data is not None,
                    "violations": result.violations})
                if result.data is None:
                    entry["failures"] += 1
                    stage["failure"] = {"step": item, "slot": slot if count_key else None,
                                        "reason": "; ".join(reasons)}
                    stage["structured_failure"] = result.failure("world_contract")
                    graph["contract_stage"] = stage
                    raise StructuredFailure("world_contract", result)
                value = result.data[output_key] if output_key else result.data
                if count_key:
                    contract[section][field].append(value)
                else:
                    contract[section][field] = value
        Draft202012Validator(load_schema("world_contract")).validate(contract)
        graph["world_contract"] = {
            "id": CONTRACT_ID, "scale": "world", "world_premises": normalize_premises(contract),
            "provenance": {"statement_ids": [s["id"] for s in context["statements"]],
                           "derived_from": [],
                           "reason": "Contract derived from input brief and world axes"}}
        stage.update(status="success", checks_enabled=True)
        graph["contract_stage"] = stage
        return stage


def establish_contract(backend, graph, brief, axes, *, max_attempts=3, max_conversions=2, raw_input=""):
    """Reuse saved stages and legacy contracts; otherwise build item by item."""
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
    return ContractBuilder(backend, max_attempts=max_attempts,
        max_conversions=max_conversions, raw_input=raw_input).build(graph, brief, axes)


def contract_metrics_markdown(stage):
    lines = ["## Contract items", "",
             "| Item | Calls | Attempt distribution | Failures | Rejection reasons |",
             "| --- | ---: | --- | ---: | --- |"]
    for item, entry in stage.get("metrics", {}).get("steps", {}).items():
        reasons = json.dumps(entry["reasons"], ensure_ascii=False).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {item} | {entry['calls']} | {json.dumps(entry['attempts'])} | "
                     f"{entry['failures']} | {reasons} |")
    lines += ["",
             "| Item | Slot | Calls | Attempt distribution | Failures | Rejection reasons |",
             "| --- | --- | ---: | --- | ---: | --- |"]
    for record in stage.get("steps", []):
        reasons = [v["message"] for violations in record["violations"] for v in violations]
        text = json.dumps(reasons, ensure_ascii=False).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {record['step']} | {record['slot']} | {record['calls']} | "
                     f"{json.dumps({str(record['attempts']): 1})} | {int(not record['accepted'])} | {text} |")
    if stage.get("failure"):
        lines += ["", "Failed item: " + json.dumps(stage["failure"], ensure_ascii=False)]
    return "\n".join(lines) + "\n"
