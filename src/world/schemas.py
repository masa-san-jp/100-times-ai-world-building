"""Repository-owned draft 2020-12 output contracts."""

import copy
import json
from pathlib import Path

from . import graph

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "config" / "schemas"


def load_schema(task):
    return json.loads((SCHEMA_DIR / f"{task}.json").read_text(encoding="utf-8"))


def candidates_schema(n):
    schema = load_schema("candidates")
    candidates = schema["properties"]["candidates"]
    candidates.update(minItems=n, maxItems=n)
    props = candidates["items"]["properties"]
    props["type"]["enum"] = list(graph.ENTITY_TYPES)
    props["relations"]["items"]["properties"]["type"]["enum"] = list(graph.RELATION_TYPES)
    props["facts"]["items"]["properties"]["kind"]["enum"] = list(graph.FACT_KINDS)
    return schema


def world_axes_schema(catalog):
    schema = load_schema("world_axes")
    schema["properties"]["axes"]["items"]["properties"]["domain"]["enum"] = [
        d["id"] for d in catalog["domains"]] + [None]
    return schema


def judge_schema(criteria, proposal=None):
    schema = load_schema("judge")
    for criterion in dict.fromkeys(criteria):
        assessment = copy.deepcopy(schema["$defs"]["assessment"])
        if criterion == "consistency" and proposal:
            groups = {}
            for group, definition, key in (("units", "unit_approval", "unit"),
                                            ("capabilities", "capability_approval", "capability")):
                terms = proposal.get(group, [])
                item = copy.deepcopy(schema["$defs"][definition])
                if terms:
                    item["properties"][key]["enum"] = list(terms)
                groups[group] = {"type": "array", "items": item,
                                 "minItems": len(terms), "maxItems": len(terms)}
            assessment["properties"]["premise_extension_approvals"] = {
                "type": "object", "properties": groups,
                "required": list(groups), "additionalProperties": False}
            assessment["required"].append("premise_extension_approvals")
        schema["properties"][criterion] = assessment
        schema["required"].append(criterion)
    return schema
