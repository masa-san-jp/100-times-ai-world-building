"""Repository-owned draft 2020-12 output contracts."""

import copy
import json
from pathlib import Path

from . import graph

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "config" / "schemas"


def load_schema(task):
    return json.loads((SCHEMA_DIR / f"{task}.json").read_text(encoding="utf-8"))


def world_axes_schema(catalog):
    schema = load_schema("world_axes")
    schema["properties"]["axes"]["items"]["properties"]["domain"]["enum"] = [
        d["id"] for d in catalog["domains"]] + [None]
    return schema


def step_schema(step, *, types=(), statement_ids=(), entity_ids=(), axis_ids=(), fact_count=0,
                kind=None, contract=None):
    """Fill a step contract with the ids allowed by this build's context."""
    schema = load_schema("steps/" + step)
    props = schema["properties"]
    def choices(values):
        # JSON Schema forbids an empty enum; false is the empty set of values.
        return {"enum": list(values)} if values else False
    if step == "type":
        props["type"] = choices(types)
    elif step == "grounding":
        props["statement_ids"]["items"] = choices(statement_ids)
        props["derived_from"]["items"] = choices(entity_ids)
    elif step == "axes":
        props["axes"]["items"] = choices(axis_ids)
    elif step == "fact" and kind in {"number", "period"}:
        contract = contract or {}
        props["value"] = {"type": "number"}
        if kind == "number":
            props["subject"] = {"type": "string", "minLength": 1, "maxLength": 80}
            props["unit"] = (choices(contract.get("technology", {}).get("units", []))
                             if contract else
                             {"type": "string", "minLength": 1, "maxLength": 20})
        else:
            calendar = contract.get("calendar", {})
            props["marker"] = choices([
                *([calendar["name"]] if "name" in calendar else []),
                *calendar.get("markers", [])])
        schema["required"] = list(props)
    elif step == "relations":
        rel = props["relations"]["items"]["properties"]
        rel["type"] = choices(graph.RELATION_TYPES)
        rel["target"] = choices(entity_ids)
    elif step == "review":
        props["issues"]["items"]["properties"]["field"]["enum"] = [
            "name", "summary", *(f"facts[{i}]" for i in range(fact_count))]
    return schema
