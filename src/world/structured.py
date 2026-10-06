"""Generate, validate and repair every structured model response."""

import json
import time
from dataclasses import dataclass
from typing import Optional

from jsonschema import Draft202012Validator
from loguru import logger


@dataclass
class StructuredResult:
    data: Optional[dict]
    attempts: int
    violations: list
    elapsed: float
    mode: str

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


def generate_structured(backend, prompt, schema, *, task, system_prompt=None,
                        images=None, max_attempts):
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("structured.max_attempts must be a positive integer")
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
    for attempt in range(1, max_attempts + 1):
        mode = "constrained" if constrained else "unconstrained"
        modes.append(mode)
        raw = backend.generate_schema(current, schema, system_prompt=system_prompt,
                                      images=images, constrained=constrained)
        try:
            parsed = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (TypeError, ValueError) as exc:
            violations = [{"path": "$", "expected": "valid JSON object",
                           "actual": raw, "message": str(exc)}]
            if constrained and not forced:
                constrained = False
                client._structured_modes[key] = False
                logger.info("Structured output switched to unconstrained for backend={} model={}", *key)
        else:
            violations = [{"path": "$" + "".join(f"[{p}]" if isinstance(p, int) else f"[{json.dumps(p)}]" for p in error.absolute_path),
                           "expected": {error.validator: error.validator_value},
                           "actual": error.instance, "message": error.message}
                          for error in validator.iter_errors(parsed)]
            if not violations:
                data = parsed
        history.append(violations)
        if data is not None:
            break
        current = (original + "\n\nREPAIR INSTRUCTIONS: Regenerate the complete JSON object. Fix EVERY violation below.\n"
                   + json.dumps(violations, ensure_ascii=False) + "\nPREVIOUS OUTPUT:\n" + (raw or "(empty)"))
    result = StructuredResult(data, attempt, history, time.monotonic() - start, mode)
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
        for used in modes:
            entry["modes"][used] = entry["modes"].get(used, 0) + 1
    return result


def metrics_markdown(metrics):
    lines = ["## Structured output", "",
             "| Task | Calls | Attempts to compliance | Failures | Seconds | Modes (attempts) |",
             "| --- | ---: | --- | ---: | ---: | --- |"]
    for task, entry in metrics.items():
        lines.append(f"| {task} | {entry['calls']} | {json.dumps(entry['attempts'])} | {entry['failures']} | {entry['elapsed']:.3f} | {json.dumps(entry['modes'])} |")
    return "\n".join(lines) + "\n"
