"""Issue #105 review fixes: wait accounting, call deadline, resumed budgets."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
import yaml

from src.llm import BackendUnavailable
from src.ollama_client import OllamaClient
from src.pipeline import Pipeline
from src.world.explore import BackendWaitExhausted, ExplorationLoop
from tests.test_backend_unavailable import Flaky, make_loop
from tests.test_review_findings8 import AlwaysDown
from tests.test_world_explore import RAW, cfg, make_backend

CONFIG = Path(__file__).resolve().parent.parent / "config" / "ollama_config.yaml"


def ollama(**kw):
    return OllamaClient(model="m", retry_delay=0, **kw)


def test_waiting_counts_against_the_wall_budget(tmp_path):
    backend = AlwaysDown(make_backend(), fail_on=(), probes=[])
    loop = make_loop(tmp_path, backend, clock=lambda: 0.0)
    with patch("src.world.explore.time.sleep"):
        result = loop.run(max_wall_seconds=10)
    assert result.stop_reason == "max_wall_seconds"
    assert result.state["elapsed_seconds"] >= 60
    assert backend.calls == 1


def test_probe_duration_counts_against_the_wait_allowance(tmp_path):
    now = [0.0]

    class SlowProbe(Flaky):
        def is_alive(self):
            now[0] += 100
            return super().is_alive()

    backend = SlowProbe(make_backend(), fail_on={3}, probes=[True, True])
    loop = make_loop(tmp_path, backend, clock=lambda: now[0],
                     backend_wait_max_seconds=100)
    with patch("src.world.explore.time.sleep"):
        with pytest.raises(BackendWaitExhausted):
            loop.run()
    assert backend.calls == 3  # nothing was regenerated after the slow probe


def test_liveness_probe_is_bounded_by_the_remaining_deadline():
    now = [0.0]

    def timed_out(*args, **kwargs):
        now[0] = 0.5
        raise requests.exceptions.Timeout("slow")

    with patch("requests.post", side_effect=timed_out), \
            patch("requests.get") as get, \
            patch("src.ollama_client.time.monotonic", lambda: now[0]):
        ollama(call_deadline_seconds=1, max_retries=1).generate("p")
    assert get.call_args.kwargs["timeout"] == 0.5


def test_no_liveness_probe_after_the_deadline():
    now = [0.0]

    def timed_out(*args, **kwargs):
        now[0] = 11.0
        raise requests.exceptions.Timeout("slow")

    with patch("requests.post", side_effect=timed_out), \
            patch("requests.get") as get, \
            patch("src.ollama_client.time.monotonic", lambda: now[0]):
        with pytest.raises(BackendUnavailable):
            ollama(call_deadline_seconds=1).generate("p")
    get.assert_not_called()


def test_stored_unlimited_budget_overrides_the_configured_default(tmp_path):
    from src.world.explore import run_world_engine
    seen = []
    original = ExplorationLoop._stop_reason

    def spy(self, graph, budget):
        seen.append(dict(budget))
        return original(self, graph, budget)

    with patch.object(ExplorationLoop, "_stop_reason", spy):
        run_world_engine(
            RAW, None, tmp_path, make_backend(),
            {"max_iterations": 1, "max_generation_calls": None}, 3,
            config=cfg(budget={"max_generation_calls": 77}), render=False)
    assert seen and all(b["max_generation_calls"] is None for b in seen)


def test_missing_effective_budget_falls_back_to_requested(tmp_path):
    config = yaml.safe_load(CONFIG.read_text("utf-8"))
    config.setdefault("engine", {})["explore"] = {"budget": {"max_generation_calls": 77}}
    path = tmp_path / "a.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    manifest_path = tmp_path / "world_d1" / "run_manifest.json"

    Pipeline(config_path=str(path), output_dir=tmp_path, run_id="d1",
             backend=make_backend(), seed=11, budget={"max_iterations": 2})
    data = json.loads(manifest_path.read_text("utf-8"))
    data["budget"] = {"requested": {"max_iterations": 2}}
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    again = Pipeline(config_path=str(path), output_dir=tmp_path, run_id="d1",
                     backend=make_backend(), seed=11)
    assert again.budget["max_iterations"] == 2
    assert again.budget["max_generation_calls"] is None
