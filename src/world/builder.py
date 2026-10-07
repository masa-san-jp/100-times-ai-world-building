"""Assemble an entity from independently generated and checked fields."""
from __future__ import annotations

import copy
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

import yaml

from .graph import ENTITY_TYPES, get_entity, local_context, make_entity, next_entity_id
from .language import load_language_rules, rules_for
from .operators import (OPERATORS, OperatorConfig, OperatorError, _TARGET_RELATION,
                        _clip, _world_context, load_prompts, placement)
from .quantities import NUMBER, is_counter, registered_unit, unit_factors, units_in_text
from .schemas import step_schema
from .structured import generate_structured
from .textsim import ngrams_of, normalize_item
from .verify import reference_text, verify_consistency, verify_objectivity

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
ALLOWED_TYPES = {
    "premise": ("place", "institution", "group", "practice", "concept"),
    "expand": tuple(t for t in ENTITY_TYPES if t != "document"),
    "zoom": tuple(t for t in ENTITY_TYPES if t != "document"),
    "cause": ("event", "concept", "institution", "practice"),
    "perspective": ("group", "practice", "person"),
    "history": ("event", "place", "object"),
    "document": ("document",),
}


@dataclass
class StepRecord:
    step: str
    slot: int | None
    attempt: int
    output: dict | None
    checks: list
    accepted: bool


@dataclass
class BuildResult:
    entity: dict | None
    steps: list[StepRecord]
    failure: dict | None
    calls: int


def fact_plan(scale, min_concrete_facts, contract):
    count = max(2, int(min_concrete_facts.get(scale, 0)) + 1)
    cycle = ("object", "procedure", "period" if contract else "procedure")
    return ["number", "proper_noun", *(cycle[i % 3] for i in range(count - 2))]


def overlap(text, reference):
    mine = ngrams_of(text, 3)
    return len(mine & ngrams_of(reference, 3)) / len(mine) if mine else 0.0


def check(criterion, ok, reason):
    return {"criterion": criterion, "ok": bool(ok), "reason": reason}


def value_in_text(value, text):
    """Compare complete numeric tokens after width and grouping normalization."""
    return any(Decimal(token.replace(",", "")) == Decimal(str(value))
               for token in re.findall(NUMBER, unicodedata.normalize("NFKC", text)))


class EntityBuilder:
    def __init__(self, backend, cfg=None, prompts=None, rules=None):
        self.backend = backend
        self.cfg = cfg or {}
        build = self.cfg.get("build", {})
        self.max_step_attempts = build.get("max_step_attempts", 4)
        self.review_rounds = build.get("review_rounds", 2)
        self.structured_attempts = self.cfg.get("structured", {}).get("max_attempts", 3)
        self.structured_conversions = self.cfg.get("structured", {}).get("max_conversions", 2)
        for key, value, minimum in (("max_step_attempts", self.max_step_attempts, 1),
                                    ("review_rounds", self.review_rounds, 0),
                                    ("structured.max_attempts", self.structured_attempts, 1),
                                    ("structured.max_conversions", self.structured_conversions, 0)):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{key} must be an integer >= {minimum}")
        self.operator_cfg = OperatorConfig(**self.cfg.get("operator", {}))
        self.prompts = prompts if prompts is not None else yaml.safe_load(
            (CONFIG_DIR / "prompts/world/steps.yaml").read_text(encoding="utf-8"))
        self.tasks = load_prompts()["operators"]
        self.rules = rules if rules is not None else load_language_rules()
        self.metrics = {"steps": {}, "accepted": 0, "failed": 0, "failures_by_step": {}}

    def build(self, graph, operator, target_id, *, brief, axes, contract, frontier_axis):
        if operator not in OPERATORS:
            raise OperatorError(f"unknown operator: {operator}")
        target = get_entity(graph, target_id) if target_id else None
        if operator != "premise" and target is None:
            raise OperatorError(f"{operator} needs an existing target entity id")
        cfg = self.operator_cfg
        ctx = (local_context(graph, target_id, cfg.context_limits) if target is not None
               else _world_context(graph, cfg))
        views = ([ctx["entity"], ctx.get("parent") or {}, *ctx["siblings"], *ctx["related"]]
                 if target is not None else ctx["entities"])
        ids = list(dict.fromkeys(v["id"] for v in views if v.get("id")))
        statements = [s for s in brief.get("statements", []) if s.get("id")][:cfg.max_statements]
        axis_view = list(axes)[:cfg.max_axes]
        # The selected gap remains available even when the prompt axis list is bounded.
        if frontier_axis and frontier_axis not in {a["id"] for a in axis_view}:
            selected = next(a for a in axes if a["id"] == frontier_axis)
            axis_view = [*axis_view[:-1], selected]
        place = placement(operator, graph, target)
        entity = {"id": next_entity_id(graph), **place, "origin_operator": operator, "facts": []}
        plan = fact_plan(place["scale"], cfg.min_concrete_facts, contract)
        reference = reference_text(graph, target_id, brief, cfg.context_limits)
        language = graph["meta"]["language"]
        rl = rules_for(self.rules, language)
        records, attempts = [], {}
        calls = 0
        failure = None
        schema_args = dict(types=ALLOWED_TYPES[operator], statement_ids=[s["id"] for s in brief.get("statements", []) if s.get("id")],
                           entity_ids=ids, axis_ids=[a["id"] for a in axes], fact_count=len(plan))

        def prompt(step, slot, correction=""):
            instruction = self.prompts["steps"][step]
            if step in {"fact", "fact_check"}:
                kind = plan[slot]
                instruction = instruction.format(kind=kind, name=entity.get("name", ""),
                    fact=entity["facts"][slot]["text"] if step == "fact_check" else "",
                    kind_instruction=self.prompts["fact_kinds"][kind])
            return self.prompts["common"]["user"].format(
                language=language, operator=operator, task=self.tasks[operator].strip(),
                target=target_id, statements="\n".join(f"{s['id']}: {_clip(s.get('text'), cfg.max_text_chars)}" for s in statements),
                axes="\n".join(f"{a['id']}: {_clip(a.get('name'), 40)} - {_clip(a.get('meaning'), cfg.max_text_chars)}" for a in axis_view),
                context=json.dumps(ctx, ensure_ascii=False), contract=json.dumps(contract, ensure_ascii=False),
                entity=json.dumps(entity, ensure_ascii=False), step=step, slot=slot,
                instruction=instruction, correction=correction or "(none)")

        def generate(step, slot, correction=""):
            nonlocal calls
            result = generate_structured(self.backend, prompt(step, slot, correction),
                step_schema(step, **schema_args,
                            kind=plan[slot] if step == "fact" else None, contract=contract), task=step,
                system_prompt=self.prompts["common"]["system"], max_attempts=self.structured_attempts,
                max_conversions=self.structured_conversions)
            calls += result.attempts + result.conversions
            entry = self.metrics["steps"].setdefault(step, {"calls": 0, "attempts": {}, "reasons": {}, "failures": 0})
            entry["calls"] += result.attempts + result.conversions
            return result

        def apply(step, slot, data):
            if step == "grounding":
                provenance = copy.deepcopy(data)
                if operator in _TARGET_RELATION and target_id not in provenance["derived_from"]:
                    provenance["derived_from"].append(target_id)
                entity["provenance"] = provenance
            elif step == "axes":
                values = list(dict.fromkeys(data["axes"]))
                if frontier_axis and frontier_axis not in values:
                    values = [frontier_axis, *values[:2]]
                entity["axes"] = values
            elif step == "fact":
                fact = {"kind": plan[slot], "text": data["fact"], "provenance": copy.deepcopy(entity["provenance"])}
                fact.update({key: data[key] for key in ("subject", "value", "unit", "marker") if key in data})
                if slot < len(entity["facts"]):
                    entity["facts"][slot] = fact
                else:
                    entity["facts"].append(fact)
            else:
                entity.update(copy.deepcopy(data))

        def content_checks(step, slot, data):
            if step == "grounding":
                prov = entity["provenance"]
                return [check("grounded", bool(prov["statement_ids"] or prov["derived_from"]), "at least one source is required"),
                        check("grounded", not prov["derived_from"] or len(prov["reason"].strip()) >= 10,
                              "derived_from requires a reason of at least 10 characters")]
            if step == "name":
                name = entity["name"]
                checks = [check("distinct", bool(normalize_item(name)) and all(normalize_item(name) != normalize_item(e["name"]) for e in graph["entities"]),
                                "name must differ from existing names after normalization")]
                script = rl.get("name_script")
                if script:
                    letters = [c for c in name if c.isalpha()]
                    checks.append(check("objective", bool(letters) and all(re.fullmatch(script, c) for c in letters), "name must use the output language's script"))
                return checks
            if step == "summary":
                deductions = verify_objectivity({"entity": entity}, language, self.rules).deductions
                narrative = [d for d in deductions if d.code in {"quotation", "first_person", "second_person"}]
                return [check("objective", not deductions, "; ".join(d.message for d in deductions)),
                        check("no_story", not narrative, "; ".join(d.message for d in narrative)),
                        check("informative", overlap(entity["summary"], reference) <= 0.6, "character 3-gram overlap must be <= 0.6")]
            if step == "relations":
                return [check("consistent", all(r["target"] != entity["id"] for r in entity["relations"]), "self references are forbidden")]
            if step != "fact":
                return []
            text, kind = data["fact"], plan[slot]
            others = [f["text"] for i, f in enumerate(entity["facts"]) if i != slot]
            units = units_in_text(text, contract, rl)
            if kind == "number":
                times = {normalize_item(v) for v in rl.get("time_basis_aliases", {})}
                def non_time(unit):
                    factors = unit_factors(unit)
                    return normalize_item(unit) not in times and (
                        factors is None or any(normalize_item(factor) not in times for factor in factors))
                specific = (value_in_text(data["value"], text) and data["unit"] in text
                            and not is_counter(data["unit"], rl) and non_time(data["unit"]))
                specific_reason = "number requires its value and non-time measurement unit in the fact text"
            elif kind == "period":
                specific = data["marker"] in text and value_in_text(data["value"], text)
                specific_reason = "period requires its calendar marker and value in the fact text"
            else:
                confirmed = generate("fact_check", slot)
                entry = self.metrics["steps"]["fact_check"]
                dist = entry["attempts"]
                dist[str(confirmed.attempts)] = dist.get(str(confirmed.attempts), 0) + 1
                specific = confirmed.data is not None and confirmed.data["matches"]
                if not specific:
                    entry["failures"] += 1
                specific_reason = (confirmed.data["reason"] if confirmed.data else json.dumps(confirmed.violations[-1], ensure_ascii=False))
                if not specific:
                    reasons = entry["reasons"].setdefault("specific", {})
                    reasons[specific_reason] = reasons.get(specific_reason, 0) + 1
            candidate = {"entity": entity, "operator": operator, "target": target_id}
            deductions = verify_consistency(candidate, graph, axes, brief).deductions
            conflicts = [d for d in deductions if d.code == "number_conflict"]
            calendar_issues = [d for d in deductions if d.code == "undefined_calendar" and d.field == f"facts[{slot}]"]
            return [check("specific", specific, specific_reason),
                    check("informative", overlap(text, reference + "\n" + "\n".join(others)) <= 0.6, "character 3-gram overlap must be <= 0.6"),
                    check("fits_world", not contract or (all(registered_unit(u, contract, rl) for u in units) and not calendar_issues),
                          "units and calendar markers must belong to the contract"),
                    check("consistent", not conflicts, "; ".join(d.message for d in conflicts)),
                    check("distinct", normalize_item(text) not in {normalize_item(t) for t in others}, "facts in the entity must not duplicate one another")]

        def record(step, slot, attempt, output, checks):
            accepted = all(c["ok"] for c in checks)
            records.append(StepRecord(step, slot, attempt, copy.deepcopy(output), checks, accepted))
            entry = self.metrics["steps"][step]
            for c in checks:
                if not c["ok"]:
                    reasons = entry["reasons"].setdefault(c["criterion"], {})
                    reasons[c["reason"]] = reasons.get(c["reason"], 0) + 1
            return accepted

        def run_step(step, slot=None, correction=""):
            nonlocal failure
            key = (step, slot)
            while attempts.get(key, 0) < self.max_step_attempts:
                attempts[key] = attempts.get(key, 0) + 1
                previous = copy.deepcopy(entity)
                result = generate(step, slot, correction)
                data = result.data
                if data is None:
                    checks = [check("consistent", False, "schema: " + json.dumps(result.violations[-1], ensure_ascii=False))]
                else:
                    apply(step, slot, data)
                    checks = content_checks(step, slot, data)
                if record(step, slot, attempts[key], data, checks):
                    return True
                entity.clear()
                entity.update(previous)
                reasons = [c for c in checks if not c["ok"]]
                failure = {"step": step, "slot": slot, "reason": "; ".join(c["criterion"] + ": " + c["reason"] for c in reasons)}
                correction = "PREVIOUS OUTPUT:\n" + json.dumps(data, ensure_ascii=False) + "\nFAILED CHECKS:\n" + json.dumps(reasons, ensure_ascii=False)
            if failure is None or failure["step"] != step or failure["slot"] != slot:
                failure = {"step": step, "slot": slot, "reason": correction}
            return False

        def finish(success):
            for (step, slot), count in attempts.items():
                dist = self.metrics["steps"][step]["attempts"]
                dist[str(count)] = dist.get(str(count), 0) + 1
            if success:
                self.metrics["accepted"] += 1
                built = make_entity(entity["id"], entity["type"], entity["name"], entity["scale"],
                    axes=entity["axes"], parent=entity["parent"], relations=entity.get("relations", []),
                    summary=entity["summary"], facts=entity["facts"], provenance=entity["provenance"])
                built["origin_operator"] = operator
                if operator in _TARGET_RELATION:
                    rel = {"type": _TARGET_RELATION[operator], "target": target_id}
                    if rel not in built["relations"]:
                        built["relations"].append(rel)
                return BuildResult(built, records, None, calls)
            self.metrics["failed"] += 1
            step = failure["step"]
            counts = self.metrics["failures_by_step"]
            counts[step] = counts.get(step, 0) + 1
            self.metrics["steps"][step]["failures"] += 1
            return BuildResult(None, records, failure, calls)

        if len(ALLOWED_TYPES[operator]) == 1:
            entity["type"] = ALLOWED_TYPES[operator][0]
        elif not run_step("type"):
            return finish(False)
        for step in ("grounding", "name", "axes", "summary"):
            if not run_step(step):
                return finish(False)
        for slot in range(len(plan)):
            if not run_step("fact", slot):
                return finish(False)
        if ids and not run_step("relations"):
            return finish(False)
        entity.setdefault("relations", [])
        if operator in _TARGET_RELATION:
            relation = {"type": _TARGET_RELATION[operator], "target": target_id}
            if relation not in entity["relations"]:
                entity["relations"].append(relation)
        for rnd in range(self.review_rounds + 1):
            result = generate("review", None)
            attempts[("review", None)] = rnd + 1
            data = result.data
            if data is None:
                checks = [check("consistent", False, "schema: " + json.dumps(result.violations[-1], ensure_ascii=False))]
            else:
                checks = [check(k, v, "; ".join(i["reason"] for i in data["issues"] if i["criterion"] == k)) for k, v in data["verdicts"].items()]
                # A false verdict without a corresponding issue cannot authorize a repair.
                for k, v in data["verdicts"].items():
                    if not v and not any(i["criterion"] == k for i in data["issues"]):
                        checks.append(check(k, False, "false verdict has no issue identifying an affected field"))
                if data["issues"] and all(data["verdicts"].values()):
                    checks.append(check("consistent", False, "issues contradict the passing verdicts"))
            if record("review", None, rnd + 1, data, checks):
                return finish(True)
            failure = {"step": "review", "slot": None, "reason": "; ".join(c["criterion"] + ": " + c["reason"] for c in checks if not c["ok"])}
            if rnd == self.review_rounds:
                break
            if data is None or not data["issues"]:
                continue
            grouped = {}
            for issue in data["issues"]:
                grouped.setdefault(issue["field"], []).append(issue)
            for field, issues in grouped.items():
                step = "fact" if field.startswith("facts[") else field
                slot = int(field[6:-1]) if step == "fact" else None
                correction = "PREVIOUS OUTPUT:\n" + json.dumps(entity["facts"][slot] if step == "fact" else {step: entity[step]}, ensure_ascii=False) + "\nREVIEW ISSUES:\n" + json.dumps(issues, ensure_ascii=False)
                if not run_step(step, slot, correction):
                    return finish(False)
        return finish(False)


def build_metrics_markdown(metrics):
    lines = ["## Entity building", "", f"- Accepted entities: {metrics.get('accepted', 0)}",
             f"- Failed entities: {metrics.get('failed', 0)}",
             "- Failed entities by step: " + json.dumps(metrics.get("failures_by_step", {}), ensure_ascii=False), "",
             "| Step | Calls | Attempt distribution | Failures | Reasons by criterion |",
             "| --- | ---: | --- | ---: | --- |"]
    for step, entry in metrics.get("steps", {}).items():
        reasons = json.dumps(entry["reasons"], ensure_ascii=False).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {step} | {entry['calls']} | {json.dumps(entry['attempts'])} | {entry['failures']} | {reasons} |")
    return "\n".join(lines) + "\n"
