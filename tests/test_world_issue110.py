"""Issue #110: issuer standpoints and divergent records of the same event.

Documents about the same target may differ in their issuers' claims, but not
in the world's numbers or periods.  All generation uses the deterministic fake.
"""
import json

from src.world.builder import recheck_against_graph
from src.world.graph import make_entity, validate_graph
from src.world.render import render_world_package
from src.world.verify import document_conflicts, same_event_documents, verify_consistency
from tests.helpers_world import write_package
from tests.test_world_builder import AXES, BRIEF, build, backend_with, graph

PROV = {"statement_ids": ["s1"], "derived_from": [], "reason": ""}
EXISTING_SUMMARY = "The levy roll records the grain quota owed by the settlement and judges it fair."


def existing_document(eid="e4", target="e3", standpoint="tax office", facts=None):
    doc = make_entity(eid, "document", "Levy Roll Nine", "settlement", parent="e2", axes=["a1"],
        relations=[{"type": "related_to", "target": target}], summary=EXISTING_SUMMARY,
        facts=facts if facts is not None else [
            {"kind": "number", "text": "Capacity measured 40 quota.", "subject": "Capacity",
             "value": 40, "unit": "quota", "provenance": PROV}],
        provenance=PROV)
    doc["origin_operator"] = "document"
    doc["issuer_standpoint"] = standpoint
    return doc


def world_with_document():
    g = graph("settlement")
    g["entities"].append(existing_document())
    return g


def number_override(value, subject="Capacity"):
    def change(step, slot, attempt, prompt, good):
        if step == "fact_element" and slot == 0:
            return {**good, "subject": subject, "value": value, "unit": "quota"}
        return good
    return change


def test_document_records_issuer_standpoint_and_it_renders(tmp_path):
    g = graph("settlement")
    _, result = build(g=g, operator="document", target="e3")
    entity = result.entity
    assert entity and entity["type"] == "document"
    assert isinstance(entity["issuer_standpoint"], str) and entity["issuer_standpoint"].strip()
    assert [s.step for s in result.steps][:3] == ["grounding", "standpoint", "name"]
    g["entities"].append(entity)
    assert validate_graph(g, AXES, BRIEF) == []
    write_package(tmp_path, g["entities"])
    render_world_package(tmp_path)
    page = next(tmp_path.rglob("documents.md")).read_text(encoding="utf-8")
    assert f"Issuer standpoint: {entity['issuer_standpoint']}" in page


def test_only_documents_may_carry_a_standpoint():
    g = graph("settlement")
    g["entities"][-1]["issuer_standpoint"] = "tax office"
    assert any("issuer_standpoint" in e for e in validate_graph(g, AXES, BRIEF))
    g = world_with_document()
    g["entities"][-1]["issuer_standpoint"] = " "
    assert any("issuer_standpoint" in e for e in validate_graph(g, AXES, BRIEF))
    assert validate_graph(world_with_document(), AXES, BRIEF) == []


def test_same_event_document_gets_another_standpoint_and_keeps_numbers():
    g = world_with_document()
    claims = "The settlers' society records the same quota and judges it a burden on late harvests."

    def change(step, slot, attempt, prompt, good):
        if step == "standpoint":
            # LOCAL CONTEXT shows the existing issuer; the first answer repeats it.
            assert '"issuer_standpoint": "tax office"' in prompt
            assert "issuer whose standpoint differs" in prompt
            return {"issuer_standpoint": "Tax Office" if attempt == 1 else "settlers' mutual-aid society"}
        if step == "summary":
            return {"summary": claims}
        return number_override(40, "Stored grain")(step, slot, attempt, prompt, good)

    backend = backend_with(change)
    _, result = build(backend, g, "document", "e3")
    entity = result.entity
    assert entity and result.failure is None
    rows = [s for s in result.steps if s.step == "standpoint"]
    assert [r.accepted for r in rows] == [False, True]
    assert "new_information" in json.dumps(rows[0].checks)
    assert entity["issuer_standpoint"] == "settlers' mutual-aid society"
    assert {"type": "related_to", "target": "e3"} in entity["relations"]
    # The claims differ; the numbers do not contradict the existing record.
    assert entity["summary"] != EXISTING_SUMMARY
    assert [d["id"] for d in same_event_documents(entity, g)] == ["e4"]
    assert document_conflicts(entity, g) == []
    g["entities"].append(entity)
    assert validate_graph(g, AXES, BRIEF) == []
    assert recheck_against_graph(entity, {**g, "entities": g["entities"][:-1]}, brief=BRIEF,
        raw_input="", contract={}, judge_backend=backend, language="en") == []


def test_contradicting_number_in_same_event_document_fails_consistent():
    _, result = build(backend_with(number_override(55)), world_with_document(), "document", "e3")
    assert result.entity is None
    assert result.failure["step"] == "fact_text" and result.failure["slot"] == 0
    assert "consistent" in result.failure["reason"]
    assert "document e4 of the same event" in result.failure["reason"]


def test_same_number_on_another_target_is_not_compared():
    g = graph("settlement")
    g["entities"].append(existing_document(target="e2"))
    _, result = build(backend_with(number_override(55)), g, "document", "e3")
    assert result.entity and result.failure is None


def test_contradicting_period_label_in_same_event_document_is_a_number_conflict():
    period = {"kind": "period", "text": "Levy period VelaCount 3 cycles.", "marker": "VelaCount",
              "value": 3, "provenance": PROV}
    g = graph("settlement")
    g["entities"].append(existing_document(facts=[period]))
    other = existing_document("e5", standpoint="district guild",
        facts=[{**period, "text": "Levy period VelaCount 5 cycles.", "value": 5}])
    other["name"] = "Guild Levy Notice"
    result = verify_consistency({"entity": other, "operator": "document", "target": "e3"}, g)
    assert [d.code for d in result.deductions].count("number_conflict") == 1
    agreeing = existing_document("e5", standpoint="district guild", facts=[period])
    assert document_conflicts(agreeing, g) == []


def test_commit_recheck_rejects_parallel_conflict_and_repeated_standpoint():
    g = world_with_document()
    late = existing_document("e5", standpoint="Tax  Office", facts=[
        {"kind": "number", "text": "Capacity measured 41 quota.", "subject": "Capacity",
         "value": 41, "unit": "quota", "provenance": PROV}])
    late["name"] = "Levy Roll Ten"
    failures = recheck_against_graph(late, g, brief=BRIEF, raw_input="", contract={},
        judge_backend=None, language="en")
    reasons = [f["reason"] for f in failures]
    assert any(r.startswith("consistent:") and "e4" in r for r in reasons)
    assert any(r.startswith("new_information: issuer standpoint") for r in reasons)
