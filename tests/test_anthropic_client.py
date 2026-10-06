"""Tests for the optional Anthropic backend using a fake SDK module."""

import builtins
import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.llm.anthropic_client import AnthropicClient


class FakeAnthropicError(Exception):
    pass


class FakeAPIError(FakeAnthropicError):
    pass


class FakeAPIStatusError(FakeAPIError):
    pass


class FakeRateLimitError(FakeAPIStatusError):
    pass


class FakeBadRequestError(FakeAPIStatusError):
    pass


class FakeAPIConnectionError(FakeAPIError):
    pass


@pytest.fixture(autouse=True)
def fake_anthropic_module(monkeypatch):
    module = types.ModuleType("anthropic")
    module.AnthropicError = FakeAnthropicError
    module.APIStatusError = FakeAPIStatusError
    module.RateLimitError = FakeRateLimitError
    module.BadRequestError = FakeBadRequestError
    module.APIConnectionError = FakeAPIConnectionError
    module.Anthropic = Mock()
    monkeypatch.setitem(sys.modules, "anthropic", module)
    return module


class FakeStream:
    def __init__(self, message):
        self.message = message
        self.final_message_called = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def get_final_message(self):
        self.final_message_called = True
        return self.message


def fake_message(text="generated", stop_reason="end_turn", stop_details=None):
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking="ignored"),
            SimpleNamespace(type="text", text=text),
        ],
        stop_reason=stop_reason,
        stop_details=stop_details,
    )


def make_client(sdk_client, request_options=None):
    return AnthropicClient(
        model="test-model",
        request_options=request_options or {"max_tokens": 64000},
        client=sdk_client,
    )


def test_request_options_must_include_max_tokens():
    with pytest.raises(ValueError, match="request_options.max_tokens"):
        AnthropicClient(model="test-model", request_options={})


def test_request_options_are_passed_through_and_ollama_options_are_ignored():
    sdk_client = Mock()
    stream = FakeStream(fake_message())
    sdk_client.messages.stream.return_value = stream
    request_options = {
        "max_tokens": 64000,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
    }
    client = make_client(sdk_client, request_options)

    result = client.generate_text(
        "Write a scene",
        temperature=0.2,
        top_p=0.8,
        top_k=10,
        budget_tokens=123,
    )

    assert result == "generated"
    request = sdk_client.messages.stream.call_args.kwargs
    assert request["model"] == "test-model"
    assert request["max_tokens"] == 64000
    assert request["thinking"] == {"type": "adaptive"}
    assert request["output_config"] == {"effort": "high"}
    assert "temperature" not in request
    assert "budget_tokens" not in request
    assert "top_p" not in request
    assert "top_k" not in request
    assert stream.final_message_called is True


def test_betas_in_request_options_selects_beta_stream():
    sdk_client = Mock()
    sdk_client.beta = Mock()
    sdk_client.beta.messages.stream.return_value = FakeStream(fake_message())
    client = make_client(
        sdk_client,
        {
            "max_tokens": 64000,
            "betas": ["server-side-fallback-test"],
            "fallbacks": "default",
        },
    )

    assert client.generate_text("Write") == "generated"
    request = sdk_client.beta.messages.stream.call_args.kwargs
    assert request["betas"] == ["server-side-fallback-test"]
    assert request["fallbacks"] == "default"
    sdk_client.messages.stream.assert_not_called()


def test_stop_reason_max_tokens_is_recorded_as_truncation():
    sdk_client = Mock()
    sdk_client.messages.stream.return_value = FakeStream(
        fake_message('{"key": "value"}', stop_reason="max_tokens")
    )
    client = make_client(sdk_client)

    assert client.generate_schema("Return JSON", {"type": "object"}, constrained=True) is None
    assert client.last_response_meta["stop_reason"] == "max_tokens"
    assert client.last_response_meta["truncated"] is True


def test_stop_reason_refusal_is_a_recorded_failure():
    sdk_client = Mock()
    details = {"category": "safety", "explanation": "blocked"}
    sdk_client.messages.stream.return_value = FakeStream(
        fake_message("", stop_reason="refusal", stop_details=details)
    )
    client = make_client(sdk_client)

    assert client.generate_text("unsafe") is None
    assert client.last_response_meta["stop_reason"] == "refusal"
    assert client.last_response_meta["stop_details"] == details
    assert client.last_response_meta["failed"] is True


def test_sdk_receives_configured_retry_count(fake_anthropic_module):
    sdk_client = Mock()
    fake_anthropic_module.Anthropic.return_value = sdk_client
    AnthropicClient(model="test-model", request_options={"max_tokens": 1})

    fake_anthropic_module.Anthropic.assert_called_once_with(
        timeout=900.0,
        max_retries=2,
    )


def test_anthropic_is_optional_for_imports(monkeypatch):
    real_import = builtins.__import__
    sys.modules.pop("anthropic", None)

    def reject_anthropic(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("simulated missing optional dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_anthropic)
    with pytest.raises(ImportError, match="optional 'anthropic'"):
        AnthropicClient(model="test-model", request_options={"max_tokens": 1})


def test_generate_schema_forces_one_tool_and_returns_tool_input():
    sdk_client = Mock()
    message = SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="structured_output", input={"key": "value"})], stop_reason="tool_use", stop_details=None)
    sdk_client.messages.stream.return_value = FakeStream(message)
    client = make_client(sdk_client)
    schema = {"type": "object"}
    assert client.generate_schema("Return", schema, constrained=False, system_prompt="System", images=[b"image"]) == '{"key": "value"}'
    request = sdk_client.messages.stream.call_args.kwargs
    assert request["tools"][0]["input_schema"] == schema
    assert len(request["tools"]) == 1
    assert request["tool_choice"] == {"type": "tool", "name": "structured_output"}
    assert request["system"] == "System"
    assert request["messages"][0]["content"][0]["type"] == "image"
    assert sdk_client.messages.stream.call_count == 1
