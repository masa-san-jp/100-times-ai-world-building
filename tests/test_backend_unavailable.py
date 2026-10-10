"""Issue #91: an unresponsive backend is detected, waited out, or ends the run."""
import json
from unittest.mock import Mock, patch

import pytest
import requests

from src.llm import BackendUnavailable
from src.llm.fake import FakeLLMBackend
from src.ollama_client import OllamaClient
from src.world.builder import EntityBuilder
from src.world.contract import establish_contract
from src.world.criteria import real_world_check, restatement_check
from src.world.explore import BackendWaitExhausted, ExplorationLoop
from src.world.graph import new_graph
from src.world.structured import generate_structured
from tests.test_world_explore import AXES, BRIEF, RAW, cfg, make_backend

SCHEMA = {"type": "object", "properties": {"description": {"type": "string"}},
          "required": ["description"], "additionalProperties": False}


def ok_response(text="done"):
    response = Mock()
    response.json.return_value = {"response": text, "done_reason": "stop"}
    return response


def client(**kw):
    return OllamaClient(model="m", retry_delay=0, **kw)


# ------------------------------------------------------------ ollama client

def test_timeout_with_dead_server_raises_immediately_without_retry():
    with patch("requests.post", side_effect=requests.exceptions.Timeout) as post, \
            patch("requests.get", side_effect=requests.exceptions.ConnectionError) as get, \
            patch("src.ollama_client.time.sleep"):
        with pytest.raises(BackendUnavailable):
            client().generate("p")
    assert post.call_count == 1
    assert get.call_args.kwargs["timeout"] == 10
    assert get.call_args.args[0].endswith("/api/tags")


def test_connection_error_with_dead_server_raises():
    with patch("requests.post", side_effect=requests.exceptions.ConnectionError), \
            patch("requests.get", side_effect=requests.exceptions.Timeout):
        with pytest.raises(BackendUnavailable):
            client().generate("p")


def test_timeout_with_live_server_is_retried():
    with patch("requests.post", side_effect=[requests.exceptions.Timeout, ok_response("hello")]) as post, \
            patch("requests.get", return_value=Mock(status_code=200)), \
            patch("src.ollama_client.time.sleep"):
        assert client().generate("p") == "hello"
    assert post.call_count == 2


def test_live_server_exhausting_retries_still_returns_none():
    with patch("requests.post", side_effect=requests.exceptions.Timeout), \
            patch("requests.get", return_value=Mock(status_code=200)), \
            patch("src.ollama_client.time.sleep"):
        assert client(max_retries=2).generate("p") is None


def test_call_deadline_stops_retrying_even_when_server_answers_tags():
    with patch("requests.post", side_effect=requests.exceptions.Timeout) as post, \
            patch("requests.get", return_value=Mock(status_code=200)), \
            patch("src.ollama_client.time.sleep"):
        with pytest.raises(BackendUnavailable, match="exceeded"):
            client(max_retries=5, call_deadline_seconds=-1).generate("p")
    assert post.call_count == 1


def test_generate_schema_is_covered_too():
    with patch("requests.post", side_effect=requests.exceptions.Timeout), \
            patch("requests.get", side_effect=requests.exceptions.ConnectionError):
        with pytest.raises(BackendUnavailable):
            client().generate_schema("p", SCHEMA)


def test_factory_passes_call_deadline():
    from src.llm.factory import build_backend_clients
    clients = build_backend_clients("ollama", {"generation": "m"},
                                    {"call_deadline_seconds": 42}, {})
    assert clients["generation"].call_deadline_seconds == 42.0
    default = build_backend_clients("ollama", {"generation": "m"}, {}, {})
    assert default["generation"].call_deadline_seconds == 1800.0


# ------------------------------------------------- never swallowed upstream

def dead(*args, **kwargs):
    raise BackendUnavailable("down")


def dead_backend():
    return FakeLLMBackend(dead)


def test_structured_generation_propagates():
    with pytest.raises(BackendUnavailable):
        generate_structured(dead_backend(), "p", SCHEMA, task="image_description", max_attempts=3)


def test_entity_builder_propagates():
    with pytest.raises(BackendUnavailable):
        EntityBuilder(dead_backend(), None).build(
            new_graph("en"), "premise", None, brief=BRIEF, axes=AXES, contract={}, frontier_axis=None)


def test_contract_builder_propagates():
    with pytest.raises(BackendUnavailable):
        establish_contract(dead_backend(), new_graph("en"), BRIEF, AXES, raw_input=RAW)


def test_judgement_calls_propagate():
    with pytest.raises(BackendUnavailable):
        real_world_check(dead_backend(), ["x"], language="en", max_attempts=2, max_conversions=0)
    with pytest.raises(BackendUnavailable):
        restatement_check(dead_backend(), "a fact", ["another"], language="en",
                          max_attempts=2, max_conversions=0)


def test_review_judge_failure_propagates_through_builder():
    builder = EntityBuilder(make_backend(), None, judge_backend=dead_backend())
    with pytest.raises(BackendUnavailable):
        builder.build(new_graph("en"), "premise", None, brief=BRIEF, axes=AXES,
                      contract={}, frontier_axis=None)


# ------------------------------------------------------- exploration loop

class Flaky:
    """Delegates to a fake backend but fails chosen generation calls."""

    def __init__(self, inner, fail_on, probes):
        self._fake = inner
        self.fail_on = set(fail_on)
        self.probes = list(probes)
        self.calls = 0
        self.probe_calls = 0

    def generate_schema(self, *args, **kwargs):
        self.calls += 1
        if self.calls in self.fail_on:
            raise BackendUnavailable("down")
        return self._fake.generate_schema(*args, **kwargs)

    def is_alive(self):
        self.probe_calls += 1
        return self.probes.pop(0) if self.probes else True

    def __getattr__(self, name):
        return getattr(self._fake, name)


def make_loop(tmp_path, backend, **kw):
    c = cfg(budget={"max_iterations": 2})
    return ExplorationLoop(backend, tmp_path, BRIEF, AXES, seed=3, language="en",
                           config=c, **kw)


def test_loop_waits_then_redoes_the_iteration(tmp_path):
    sleeps = []
    backend = Flaky(make_backend(), fail_on={3}, probes=[False, False, True])
    with patch("src.world.explore.time.sleep", side_effect=sleeps.append):
        result = make_loop(tmp_path, backend).run()
    assert sleeps == [60, 120, 240]
    assert backend.probe_calls == 3
    assert result.stop_reason == "max_iterations" and result.iterations == 2
    waits = result.state["backend_waits"]
    assert waits == {"started": 1, "recovered": 1, "abandoned": 0, "total_seconds": 420.0}
    manifest = json.loads((tmp_path / "run_manifest.json").read_text()) \
        if (tmp_path / "run_manifest.json").exists() else None
    assert manifest is None or manifest["world_explore"]["backend_waits"] == waits


def test_wait_intervals_cap_at_600(tmp_path):
    sleeps = []
    backend = Flaky(make_backend(), fail_on={3}, probes=[False] * 7 + [True])
    with patch("src.world.explore.time.sleep", side_effect=sleeps.append):
        make_loop(tmp_path, backend).run()
    assert sleeps == [60, 120, 240, 480, 600, 600, 600, 600]


def test_loop_exits_when_wait_allowance_is_exceeded(tmp_path):
    sleeps = []
    backend = Flaky(make_backend(), fail_on={3}, probes=[False] * 100)
    loop = make_loop(tmp_path, backend, backend_wait_max_seconds=500)
    with patch("src.world.explore.time.sleep", side_effect=sleeps.append):
        with pytest.raises(BackendWaitExhausted) as info:
            loop.run()
    assert sum(sleeps) > 500 and sum(sleeps) - sleeps[-1] <= 500
    assert "--choice 2 --run-id" in info.value.resume_command
    assert info.value.run_id in info.value.resume_command
    assert loop.state["backend_waits"]["abandoned"] == 1
    # The checkpoint is saved so --choice 2 can continue.
    assert loop.checkpoints.load_checkpoint("world_explore")["backend_waits"]["abandoned"] == 1


def test_main_returns_exit_code_75(tmp_path, monkeypatch):
    import example_run

    def boom(*args, **kwargs):
        raise BackendWaitExhausted("gone", "r1", "python example_run.py --choice 2 --run-id r1")
    monkeypatch.setattr(example_run, "resume_run", boom)
    assert example_run.main(["--choice", "2", "--run-id", "r1"]) == 75
