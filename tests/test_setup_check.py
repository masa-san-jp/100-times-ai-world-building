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
