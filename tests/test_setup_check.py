"""Tests for backend-specific setup checks."""

import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock

from setup_check import check_anthropic


def anthropic_config():
    return {
        "anthropic": {
            "model": "test-model",
            "request_options": {"max_tokens": 9000},
        }
    }


def test_anthropic_setup_retrieves_model_capabilities_and_warns(monkeypatch, capsys):
    retrieve = Mock(
        return_value=SimpleNamespace(max_input_tokens=100000, max_tokens=8000)
    )
    client = SimpleNamespace(models=SimpleNamespace(retrieve=retrieve))
    module = types.ModuleType("anthropic")
    module.Anthropic = Mock(return_value=client)
    monkeypatch.setitem(sys.modules, "anthropic", module)

    assert check_anthropic(anthropic_config()) is True

    retrieve.assert_called_once_with("test-model")
    output = capsys.readouterr().out
    assert "max_input_tokens: 100000" in output
    assert "max_tokens: 8000" in output
    assert "exceeds the model max_tokens" in output


def test_anthropic_setup_reports_missing_model(monkeypatch, capsys):
    module = types.ModuleType("anthropic")
    module.Anthropic = Mock(return_value=SimpleNamespace())
    monkeypatch.setitem(sys.modules, "anthropic", module)

    assert check_anthropic({"anthropic": {}}) is False
    assert "model is not configured" in capsys.readouterr().out


def test_anthropic_setup_reports_unknown_model(monkeypatch, capsys):
    error = RuntimeError("not found")
    error.status_code = 404
    client = SimpleNamespace(models=SimpleNamespace(retrieve=Mock(side_effect=error)))
    module = types.ModuleType("anthropic")
    module.Anthropic = Mock(return_value=client)
    monkeypatch.setitem(sys.modules, "anthropic", module)

    assert check_anthropic(anthropic_config()) is False
    assert "does not exist or is unavailable" in capsys.readouterr().out


def test_engine_config_check_passes_on_the_repository_config(capsys):
    from setup_check import check_engine_config

    assert check_engine_config() is True
    assert "exploration config" in capsys.readouterr().out


def test_engine_config_check_reports_a_missing_model(tmp_path, capsys):
    from setup_check import check_engine_config

    config = tmp_path / "c.yaml"
    config.write_text("backend: ollama\nmodel: {}\n", encoding="utf-8")
    assert check_engine_config(str(config)) is False
    assert "model.name is not set" in capsys.readouterr().out


def test_required_files_are_the_engine_files():
    import setup_check

    names = " ".join(setup_check.ENGINE_FILES)
    assert "src/world/explore.py" in names and "config/world/reward.yaml" in names
    assert "story" not in names and "plot" not in names
    assert "ipynb" not in names


def test_ollama_model_check_uses_the_configured_model(monkeypatch, capsys):
    import setup_check

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"models": [{"name": "my-local-model"}]}

    monkeypatch.setattr("requests.get", lambda *a, **k: Response())
    config = {"model": {"name": "my-local-model"}}
    assert setup_check.check_ollama_models(config) is True
    assert setup_check.check_ollama_models(config, model="absent") is False
    assert "ollama pull absent" in capsys.readouterr().out
    assert setup_check.check_ollama_models({}) is False
