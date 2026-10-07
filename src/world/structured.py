"""Generate, validate and repair every structured model response."""

import json
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
from jsonschema import Draft202012Validator
from loguru import logger

CONVERT_PROMPT_PATH = Path(__file__).resolve().parents[2] / "config/prompts/structured/convert.yaml"


@dataclass
class StructuredResult:
    data: Optional[dict]
    attempts: int
    violations: list
    elapsed: float
    mode: str
    converted: bool = False
    conversions: int = 0

    def failure(self, task):
        return {"task": task, "attempts": self.attempts,
                "violations": self.violations}


class StructuredFailure(ValueError):
    def __init__(self, task, result):
        self.task = task
        self.result = result
        super().__init__(f"{task}: {json.dumps(result.violations[-1], ensure_ascii=False)}")


def client_instance(backend):
    while "_inner" in vars(backend):
        backend = backend._inner
    return backend


def _path(parts):
    return "$" + "".join(f"[{p}]" if isinstance(p, int) else f"[{json.dumps(p)}]" for p in parts)


def _is_schema_echo(data):
    return (isinstance(data, dict) and len(data.keys() & {
        "$schema", "properties", "required", "additionalProperties", "type"}) >= 2)


def _validate_response(raw, validator):
    json_response = raw
    if isinstance(raw, str):
        fenced = re.fullmatch(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", raw.strip(), re.DOTALL)
        if fenced:
            json_response = fenced.group(1)
    try:
        parsed = json.loads(json_response, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (TypeError, ValueError) as exc:
        return None, [{"path": "$", "expected": "valid JSON object",
                       "actual": raw, "message": str(exc)}], False
    if _is_schema_echo(parsed):
        return parsed, [{"path": "$", "expected": "content rather than a JSON Schema",
                         "actual": parsed, "message": "Schema echo: output copies a JSON Schema"}], True
    violations = [{"path": _path(error.absolute_path),
                   "expected": {error.validator: error.validator_value},
                   "actual": error.instance, "message": error.message}
                  for error in validator.iter_errors(parsed)]
    return parsed, violations, True


def _placeholder_violations(data, schema):
    def normalize(value):
        return unicodedata.normalize("NFKC", value).strip().lower()

    placeholders = {"string", "number", "integer", "boolean", "object", "array", "null", "..."}

    def collect(node):
        if isinstance(node, dict):
            placeholders.update(normalize(key) for key in node.get("properties", {}))
            for child in node.values():
                collect(child)
        elif isinstance(node, list):
            for child in node:
                collect(child)

    collect(schema)
    violations = []

    def check(value, node, parts):
        node = node if isinstance(node, dict) else {}
        if isinstance(value, dict):
            for key, child in value.items():
                check(child, node.get("properties", {}).get(key, {}), [*parts, key])
        elif isinstance(value, list):
            for index, child in enumerate(value):
                check(child, node.get("items", {}), [*parts, index])
        elif isinstance(value, str) and "enum" not in node and normalize(value) in placeholders:
            violations.append({"path": _path(parts), "expected": "non-placeholder content",
                               "actual": value, "message": "Placeholder value: regenerate substantive content"})

    check(data, schema, [])
    return violations


def _contains_boolean(schema):
    if isinstance(schema, dict):
        types = schema.get("type", [])
        if types == "boolean" or isinstance(types, list) and "boolean" in types:
            return True
        return any(_contains_boolean(value) for value in schema.values())
    if isinstance(schema, list):
        return any(_contains_boolean(value) for value in schema)
    return False


def _normalize(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).lower()


def _fidelity_violations(data, schema, source):
    """Check values against the raw generation, never a previous conversion."""
    normalized = _normalize(source)
    numeric_source = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", normalized)
    violations = []

    def check(value, node, parts):
        node = node if isinstance(node, dict) else {}
        if isinstance(value, dict):
            for key, child in value.items():
                check(child, node.get("properties", {}).get(key, {}), [*parts, key])
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                check(child, node.get("items", {}), [*parts, index])
            return
        if isinstance(value, str):
            if "enum" in node:
                return
            matches = _normalize(value) in normalized
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            notation = str(int(value)) if isinstance(value, int) or value.is_integer() else str(value)
            matches = _normalize(notation) in numeric_source
        else:
            return
        if not matches:
            violations.append({"path": _path(parts), "expected": "value present in SOURCE OUTPUT",
                               "actual": value, "message": "Converted value is absent from SOURCE OUTPUT"})

    check(data, schema, [])
    return violations


def generate_structured(backend, prompt, schema, *, task, system_prompt=None,
                        images=None, max_attempts, max_conversions=2):
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("structured.max_attempts must be a positive integer")
    if isinstance(max_conversions, bool) or not isinstance(max_conversions, int) or max_conversions < 0:
        raise ValueError("structured.max_conversions must be a nonnegative integer")
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    client = client_instance(backend)
    if "_structured_modes" not in vars(client):
        client._structured_modes = {}
    key = (getattr(client, "backend_name", type(client).__name__), getattr(client, "model", None))
    forced = getattr(client, "schema_always_constrained", False) is True
    constrained = forced or client._structured_modes.get(key, True)
    original = prompt + "\n\nOUTPUT SCHEMA:\n" + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    current = original
    history, modes = [], []
    start = time.monotonic()
    data = None
    mode = "constrained" if constrained else "unconstrained"
    converted = False
    conversions = {"tried": 0, "succeeded": 0, "fidelity_failures": 0, "schema_failures": 0}
    content_counts = {"placeholder_violations": 0, "schema_echo": 0}

    def generate(current_prompt, current_system, current_images=None):
        nonlocal constrained, mode
        mode = "constrained" if constrained else "unconstrained"
        modes.append(mode)
        raw = backend.generate_schema(current_prompt, schema, system_prompt=current_system,
                                      images=current_images, constrained=constrained)
        parsed, violations, parseable = _validate_response(raw, validator)
        content_invalid = _is_schema_echo(parsed)
        if content_invalid:
            content_counts["schema_echo"] += 1
        elif not violations:
            violations = _placeholder_violations(parsed, schema)
            content_counts["placeholder_violations"] += len(violations)
            content_invalid = bool(violations)
        if not parseable and constrained and not forced:
            constrained = False
            client._structured_modes[key] = False
            logger.info("Structured output switched to unconstrained for backend={} model={}", *key)
        return raw, parsed, violations, parseable, content_invalid

    for attempt in range(1, max_attempts + 1):
        raw, parsed, violations, _, content_invalid = generate(current, system_prompt, images)
        history.append(list(violations))
        if not violations:
            data = parsed
            break
        if (not content_invalid and isinstance(raw, str) and raw.strip()
                and not _contains_boolean(schema) and max_conversions):
            prompts = yaml.safe_load(CONVERT_PROMPT_PATH.read_text(encoding="utf-8"))
            conversion_prompt = prompts["user"].format(
                schema=json.dumps(schema, ensure_ascii=False, separators=(",", ":")), source=raw)
            feedback = []
            for _ in range(max_conversions):
                current_conversion = conversion_prompt
                if feedback:
                    current_conversion += "\n\nPREVIOUS CONVERSION VIOLATIONS:\n" + json.dumps(feedback, ensure_ascii=False)
                conversions["tried"] += 1
                _, candidate, conversion_violations, parseable, content_invalid = generate(current_conversion, prompts["system"])
                fidelity_violations = _fidelity_violations(candidate, schema, raw) if parseable else []
                conversions["schema_failures"] += bool(conversion_violations) and not content_invalid
                conversions["fidelity_failures"] += bool(fidelity_violations)
                feedback = conversion_violations + fidelity_violations
                if not feedback:
                    data = candidate
                    converted = True
                    conversions["succeeded"] += 1
                    break
                history[-1].extend(feedback)
                if content_invalid:
                    break
            if converted:
                break
        current = (original + "\n\nREPAIR INSTRUCTIONS: Regenerate the complete JSON object. Fix EVERY violation below.\n"
                   + json.dumps(history[-1], ensure_ascii=False) + "\nPREVIOUS OUTPUT:\n" + (raw or "(empty)"))
    result = StructuredResult(data, attempt, history, time.monotonic() - start, mode,
                              converted, conversions["tried"])
    if "_structured_metrics" not in vars(client):
        client._structured_metrics = {}
    metrics = client._structured_metrics
    if isinstance(metrics, dict):
        entry = metrics.setdefault(task, {"calls": 0, "attempts": {}, "failures": 0,
                                          "elapsed": 0.0, "modes": {}})
        entry["calls"] += 1
        if data is None:
            entry["failures"] += 1
        else:
            count = str(attempt)
            entry["attempts"][count] = entry["attempts"].get(count, 0) + 1
        entry["elapsed"] += result.elapsed
        for name, count in content_counts.items():
            entry[name] = entry.get(name, 0) + count
        counts = entry.setdefault("conversions", {name: 0 for name in conversions})
        for name, count in conversions.items():
            counts[name] += count
        for used in modes:
            entry["modes"][used] = entry["modes"].get(used, 0) + 1
    return result


def metrics_markdown(metrics):
    lines = ["## Structured output", "",
             "| Task | Calls | Attempts to compliance | Failures | Seconds | Modes (attempts) | Placeholder violations | Schema echo | Conversions tried | Conversions succeeded | Fidelity failures | Schema failures |",
             "| --- | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for task, entry in metrics.items():
        counts = entry.get("conversions", {})
        lines.append(f"| {task} | {entry['calls']} | {json.dumps(entry['attempts'])} | {entry['failures']} | {entry['elapsed']:.3f} | {json.dumps(entry['modes'])} | "
                     f"{entry.get('placeholder_violations', 0)} | {entry.get('schema_echo', 0)} | "
                     f"{counts.get('tried', 0)} | {counts.get('succeeded', 0)} | {counts.get('fidelity_failures', 0)} | {counts.get('schema_failures', 0)} |")
    return "\n".join(lines) + "\n"
