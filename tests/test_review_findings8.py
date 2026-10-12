"""Issue #105: eight confirmed review findings (fake backends and mocks only)."""
import itertools
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import requests
import yaml

from src.llm import BackendUnavailable
from src.ollama_client import OllamaClient
from src.pipeline import Pipeline
from src.world.builder import recheck_against_graph
from src.world.explore import BackendWaitExhausted, ExplorationLoop
from src.world.structured import generate_structured
from tests.test_anthropic_client import fake_anthropic_module  # noqa: F401
from tests.test_backend_unavailable import Flaky, make_loop, ok_response
from tests.test_world_explore import AXES, BRIEF, RAW, _item, cfg, make_backend, small_graph
from tests.test_world_parallel import loop as parallel_loop
from tests.test_world_parallel import seeded

CONFIG = Path(__file__).resolve().parent.parent / "config" / "ollama_config.yaml"


# ------------------------------------------------------------------ 1

class AlwaysDown(Flaky):
    def generate_schema(self, *args, **kwargs):
        self.calls += 1
        raise BackendUnavailable("down")


def test_no_progress_ends_with_75_path_even_when_probe_succeeds(tmp_path):
    backend = AlwaysDown(make_backend(), fail_on=(), probes=[])
    loop = make_loop(tmp_path, backend, backend_wait_max_seconds=500)
    with patch("src.world.explore.time.sleep"):
        with pytest.raises(BackendWaitExhausted):
            loop.run()
    assert backend.probe_calls >= 1
    assert loop.state["backend_waits"]["abandoned"] == 1


def test_failed_generation_time_counts_against_the_wall_budget(tmp_path):
    backend = AlwaysDown(make_backend(), fail_on=(), probes=[])
    ticks = itertools.count(0, 10)
    loop = make_loop(tmp_path, backend, clock=lambda: next(ticks))
    with patch("src.world.explore.time.sleep"):
        result = loop.run(max_wall_seconds=25)
    assert result.stop_reason == "max_wall_seconds"
    assert result.state["elapsed_seconds"] >= 25


# ------------------------------------------------------------------ 2

def ollama(**kw):
    return OllamaClient(model="m", retry_delay=0, **kw)


def test_request_timeout_is_capped_by_the_remaining_deadline():
    with patch("requests.post", return_value=ok_response()) as post, \
            patch("src.ollama_client.time.monotonic", lambda: 0.0):
        assert ollama(timeout=300, call_deadline_seconds=1).generate("p") == "done"
    assert post.call_args.kwargs["timeout"] == 1


def test_success_after_the_deadline_is_unavailable():
    now = [0.0]

    def slow(*args, **kwargs):
        now[0] += 2
        return ok_response()

    with patch("requests.post", side_effect=slow), \
            patch("src.ollama_client.time.monotonic", lambda: now[0]):
        with pytest.raises(BackendUnavailable):
            ollama(call_deadline_seconds=1).generate("p")


def test_no_request_is_sent_without_remaining_time():
    with patch("requests.post") as post, patch("src.ollama_client.time.monotonic", lambda: 0.0):
        with pytest.raises(BackendUnavailable):
            ollama(call_deadline_seconds=0).generate("p")
    post.assert_not_called()


# ------------------------------------------------------------------ 3

def test_resume_overrides_carry_to_the_next_resume(tmp_path):
    def build(config, **kw):
        return Pipeline(config_path=config, output_dir=tmp_path, run_id="c1",
                        backend=make_backend(), seed=11, **kw)

    cfg_a = yaml.safe_load(CONFIG.read_text("utf-8"))
    cfg_a.setdefault("engine", {})["explore"] = {"budget": {"max_generation_calls": 4000}}
    path_a = tmp_path / "a.yaml"
    path_a.write_text(yaml.safe_dump(cfg_a), encoding="utf-8")
    cfg_b = json.loads(json.dumps(cfg_a))
    cfg_b["engine"]["explore"]["budget"]["max_generation_calls"] = 77
    path_b = tmp_path / "b.yaml"
    path_b.write_text(yaml.safe_dump(cfg_b), encoding="utf-8")

    build(str(path_a), budget={"max_iterations": 2}).run(RAW)
    build(str(path_a), budget={"max_iterations": 5}).resume()
    third = build(str(path_b))
    assert third.budget["max_iterations"] == 5
    assert third.budget["max_generation_calls"] == 4000
    manifest = json.loads((tmp_path / "world_c1" / "run_manifest.json").read_text("utf-8"))
    assert manifest["budget"]["requested"] == {"max_iterations": 2}


# ------------------------------------------------------------------ 4

def test_recheck_sees_proper_nouns_of_already_committed_facts():
    committed = {"id": "e9", "name": "Other", "facts": [
        {"kind": "proper_noun", "name": "Zorvanth", "text": "A harbor is mentioned."}]}
    graph = {"meta": {"language": "en"}, "entities": [committed]}
    entity = {"id": "e10", "name": "Fresh", "facts": [
        {"kind": "proper_noun", "name": "Zorvanth", "text": "Completely different wording."}]}
    failures = recheck_against_graph(
        entity, graph, brief=BRIEF, raw_input="", contract={}, judge_backend=None,
        language="en", new_entity_ids=[])
    assert any("already present" in f["reason"] for f in failures)


# ------------------------------------------------------------------ 5

def test_ollama_length_cut_is_per_thread():
    client = ollama()
    length = ok_response("x")
    length.json.return_value = {"response": "x", "done_reason": "length"}
    main_thread = threading.current_thread()
    original = client.generate_text

    def interleaved(*args, **kwargs):
        result = original(*args, **kwargs)
        if threading.current_thread() is main_thread:
            # Another thread records a length cut after this call's metadata
            # was recorded and before the caller decides on continuation.
            with patch("requests.post", return_value=length):
                t = threading.Thread(target=lambda: client.generate_text("other"))
                t.start()
                t.join()
        return result

    client.generate_text = interleaved
    with patch("requests.post", return_value=ok_response("a")) as post:
        assert client.generate_long_text("p") == "a"
    assert post.call_count == 1


def test_error_response_after_the_deadline_is_unavailable_not_none():
    now = [0.0]
    bad = Mock()
    bad.text = "grammar failure"
    bad.status_code = 400
    error = requests.exceptions.HTTPError("400", response=bad)
    response = Mock()
    response.raise_for_status.side_effect = error

    def slow(*args, **kwargs):
        now[0] += 2
        return response

    with patch("requests.post", side_effect=slow), \
            patch("src.ollama_client.time.monotonic", lambda: now[0]):
        with pytest.raises(BackendUnavailable):
            ollama(call_deadline_seconds=1).generate("p")


@pytest.mark.usefixtures("fake_anthropic_module")
def test_anthropic_refusal_in_another_thread_does_not_affect_this_one():
    from tests.test_anthropic_client import FakeStream, fake_message, make_client

    messages = {"ok": fake_message(text='{"a": 1}'), "refused": fake_message(stop_reason="refusal")}
    sdk = Mock()
    block = SimpleNamespace(type="tool_use", name="structured_output", input={"a": 1})
    messages["ok"].content = [block]
    gate = threading.Event()
    results = {}

    def stream(**request):
        label = request["messages"][0]["content"]
        if label == "refuse":
            return FakeStream(messages["refused"])
        gate.wait(timeout=5)
        return FakeStream(messages["ok"])

    sdk.messages.stream.side_effect = stream
    client = make_client(sdk)
    main_thread = threading.current_thread()
    record = client._record_message

    def refuse():
        results["refused"] = client.generate_schema("refuse", {"type": "object"})

    def interleaved(message):
        recorded = record(message)
        if threading.current_thread() is main_thread:
            # A refusal is recorded after the normal response's metadata and
            # before the caller decides whether that response succeeded.
            thread = threading.Thread(target=refuse)
            thread.start()
            thread.join()
        return recorded

    gate.set()
    client._record_message = interleaved
    results["ok"] = client.generate_schema("fine", {"type": "object"})
    assert results["refused"] is None
    assert json.loads(results["ok"]) == {"a": 1}


# ------------------------------------------------------------------ 6

def test_unsettled_candidates_are_not_counted_as_accepted(tmp_path):
    import src.world.explore as ex
    from src.world.explore import BudgetExhausted

    seeded(tmp_path, make_backend())
    lp = parallel_loop(tmp_path, make_backend(), 3)
    graph = lp.store.load_or_create("en")
    before = len(graph["entities"])

    def exhausted(*args, **kwargs):
        raise BudgetExhausted("budget")

    with patch.object(ex, "recheck_against_graph", exhausted):
        graph, settled, stop = lp._iterate_batch(graph, 3)
    assert isinstance(stop, BudgetExhausted) and settled == 1
    metrics = lp.builder.metrics
    assert metrics["accepted"] == len(graph["entities"]) - before
    assert metrics["accepted"] + metrics["failed"] == settled


# ------------------------------------------------------------------ 7

def test_structured_metrics_survive_concurrent_recording():
    backend = SimpleNamespace(
        backend_name="t", model="m",
        generate_schema=lambda *a, **k: '{"description": "x"}')
    schema = {"type": "object", "properties": {"description": {"type": "string"}},
              "required": ["description"], "additionalProperties": False}
    per_thread, threads = 40, 8

    def work():
        for _ in range(per_thread):
            generate_structured(backend, "p", schema, task="t", max_attempts=1)

    pool = [threading.Thread(target=work) for _ in range(threads)]
    for t in pool:
        t.start()
    for t in pool:
        t.join()
    entry = backend._structured_metrics["t"]
    assert entry["calls"] == per_thread * threads
    assert entry["attempts"]["1"] == per_thread * threads


# ------------------------------------------------------------------ 8

def test_same_generation_input_is_chosen_once_per_batch(tmp_path):
    import src.world.explore as ex

    items = [_item("world_gap"), _item("unexpanded")]
    lp = ExplorationLoop(make_backend(), tmp_path, BRIEF, AXES, seed=3, language="en",
                         config=cfg(), parallel_builds=3)
    seen = []
    lp._settle = lambda graph, it, arm, op, target, it_, *a, **k: (
        seen.append((op, target, it_["axis"])) or graph)
    original = ex.evaluate_frontier
    ex.evaluate_frontier = lambda *a, **k: [dict(i) for i in items]
    try:
        with patch.object(ex, "candidate_pairs", lambda its, c: [(i, "zoom") for i in its]):
            lp._iterate_batch(small_graph(), 3)
    finally:
        ex.evaluate_frontier = original
    assert seen == [("zoom", "e1", None)]


# ------------------------------------------------------------------ 1 (batch re-check)

def test_recheck_failure_after_a_settled_candidate_counts_toward_the_wait_limit(tmp_path):
    import src.world.explore as ex

    seeded(tmp_path, make_backend())
    lp = parallel_loop(tmp_path, make_backend(), 3)
    lp.backend_wait_max_seconds = 100
    now = [0.0]
    lp.clock = lambda: now[0]
    real = ex.recheck_against_graph
    calls = [0]

    def flaky(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 1:
            return real(*args, **kwargs)
        now[0] += 200  # the failing re-check takes longer than the allowance
        raise BackendUnavailable("down")

    with patch.object(ex, "recheck_against_graph", flaky), \
            patch("src.world.explore.time.sleep"), \
            patch.object(lp, "_backend_alive", return_value=True):
        with pytest.raises(BackendWaitExhausted):
            lp.run(max_wall_seconds=10_000)
