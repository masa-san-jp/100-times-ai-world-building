"""
Tests for OllamaClient module
"""

import pytest
import requests
import base64
from unittest.mock import Mock, patch
from src.ollama_client import OllamaClient


def fake_response(text):
    response = Mock()
    response.json.return_value = {"response": text, "done_reason": "stop"}
    return response


class TestOllamaClient:
    """Test cases for OllamaClient"""

    def test_initialization(self):
        """Test client initialization"""
        client = OllamaClient(
            host="http://localhost",
            port=11434,
            model="gpt-oss:20b"
        )

        assert client.base_url == "http://localhost:11434"
        assert client.model == "gpt-oss:20b"
        assert client.timeout == 300
        assert client.max_retries == 3
        assert client.json_mode == "auto"

    @pytest.mark.parametrize("mode", ["invalid", "", None])
    def test_invalid_json_mode_is_rejected(self, mode):
        with pytest.raises(ValueError, match="json_mode"):
            OllamaClient(json_mode=mode)

    def test_check_server_success(self):
        """Test server check when server is running"""
        client = OllamaClient()

        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            result = client.check_server()
            assert result is True

    def test_check_server_failure(self):
        """Test server check when server is not running"""
        client = OllamaClient()

        with patch('requests.get') as mock_get:
            mock_get.side_effect = ConnectionError()

            result = client.check_server()
            assert result is False

    @patch('requests.post')
    def test_generate_success(self, mock_post):
        """Test successful text generation"""
        client = OllamaClient()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": "Generated text"
        }
        mock_post.return_value = mock_response

        result = client.generate("Test prompt")
        assert result == "Generated text"

    @patch('requests.post')
    def test_generate_json_success(self, mock_post):
        """Test successful JSON generation"""
        client = OllamaClient()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": '{"key": "value"}'
        }
        mock_post.return_value = mock_response

        result = client.generate_json("Test prompt")
        assert result == {"key": "value"}

    @patch('requests.post')
    def test_generate_json_uses_explicit_compatibility_fallback(self, mock_post):
        """Invalid structured output gets one same-seed prompt-only retry."""
        client = OllamaClient(max_retries=1, retry_delay=0)
        invalid = Mock()
        invalid.status_code = 200
        invalid.json.return_value = {
            "response": "The model's planning text",
            "done_reason": "stop",
        }
        valid = Mock()
        valid.status_code = 200
        valid.json.return_value = {
            "response": '{"key": "value"}',
            "done_reason": "stop",
        }
        mock_post.side_effect = [invalid, valid]

        assert client.generate_json("Return JSON", seed=42) == {"key": "value"}
        assert mock_post.call_count == 2
        first = mock_post.call_args_list[0].kwargs["json"]
        second = mock_post.call_args_list[1].kwargs["json"]
        assert first["format"] == "json"
        assert "format" not in second
        assert second["think"] is False
        assert first["options"]["seed"] == second["options"]["seed"] == 42

    @patch('requests.post')
    def test_auto_remembers_prompt_mode_after_empty_format_response(self, mock_post):
        """Only the first logical call pays for failed format requests."""
        client = OllamaClient(model="test-model", max_retries=3, retry_delay=0)

        def respond(url, *, json, timeout):
            return fake_response("" if json.get("format") == "json" else '{"ok": true}')

        mock_post.side_effect = respond
        with patch("src.ollama_client.logger.info") as log_info:
            assert client.generate_json("Create an object", seed=42) == {"ok": True}
            assert mock_post.call_count == 4  # three empty requests, one fallback
            assert client.generate_json("Create another object", seed=43) == {"ok": True}
            assert mock_post.call_count == 5
            assert client.generate_json("Create a third object", seed=44) == {"ok": True}
            assert mock_post.call_count == 6

        payloads = [call.kwargs["json"] for call in mock_post.call_args_list]
        assert [p.get("format") for p in payloads] == ["json"] * 3 + [None] * 3
        assert all(p["think"] is False for p in payloads[3:])
        assert [p["options"]["seed"] for p in payloads[3:]] == [42, 43, 44]
        transitions = [call.args[0] for call in log_info.call_args_list
                       if "JSON request mode switched" in call.args[0]]
        assert transitions == [
            "JSON request mode switched from format to prompt for model: test-model"
        ]

    @pytest.mark.parametrize("mode", ["prompt", "format"])
    @pytest.mark.parametrize("text", ['{"ok": true}', "not JSON", ""])
    @patch('requests.post')
    def test_fixed_json_modes_never_try_the_other_mode(self, mock_post, mode, text):
        client = OllamaClient(json_mode=mode, max_retries=2, retry_delay=0)
        mock_post.return_value = fake_response(text)

        for _ in range(2):
            result = client.generate_json("Create an object", think=True)
            assert result == ({"ok": True} if text.startswith("{") else None)

        assert mock_post.call_count == (4 if text == "" else 2)
        for call in mock_post.call_args_list:
            payload = call.kwargs["json"]
            assert payload.get("format") == ("json" if mode == "format" else None)
            assert payload["think"] is (mode == "format")
            assert "JSON" in payload["prompt"]
            assert "json_mode" not in payload["options"]

    @patch('requests.post')
    def test_auto_keeps_format_when_format_succeeds(self, mock_post):
        client = OllamaClient(max_retries=1, retry_delay=0)
        mock_post.return_value = fake_response('{"ok": true}')

        assert client.generate_json("JSON") == {"ok": True}
        assert client.generate_json("JSON") == {"ok": True}
        assert mock_post.call_count == 2
        assert all(call.kwargs["json"]["format"] == "json"
                   for call in mock_post.call_args_list)

    @patch('requests.post')
    def test_auto_does_not_learn_from_a_failed_fallback(self, mock_post):
        client = OllamaClient(max_retries=1, retry_delay=0)
        mock_post.side_effect = [fake_response(text) for text in
                                 ["", "invalid", "", '{"ok": true}', '{"ok": true}']]

        assert client.generate_json("JSON") is None
        assert client.generate_json("JSON") == {"ok": True}
        assert client.generate_json("JSON") == {"ok": True}
        payloads = [call.kwargs["json"] for call in mock_post.call_args_list]
        assert [p.get("format") for p in payloads] == ["json", None, "json", None, None]

    @pytest.mark.parametrize("failure", ["", "not JSON"])
    @patch('requests.post')
    def test_auto_reverts_after_consecutive_prompt_failures(self, mock_post, failure):
        client = OllamaClient(model="test-model", max_retries=1, retry_delay=0)
        mock_post.side_effect = [fake_response(text) for text in
                                 ["", '{"ok": true}', failure, failure,
                                  '{"ok": true}', '{"ok": true}']]

        with patch("src.ollama_client.logger.info") as log_info:
            assert client.generate_json("JSON", think=True) == {"ok": True}
            assert client.generate_json("JSON", think=True) is None
            assert mock_post.call_count == 3
            assert client.generate_json("JSON", think=True) == {"ok": True}
            assert client.generate_json("JSON", think=True) == {"ok": True}

        payloads = [call.kwargs["json"] for call in mock_post.call_args_list]
        assert [p.get("format") for p in payloads] == ["json", None, None, None, "json", "json"]
        assert [p["think"] for p in payloads] == [True, False, False, False, True, True]
        transitions = [call.args[0] for call in log_info.call_args_list
                       if "JSON request mode switched" in call.args[0]]
        assert transitions == [
            "JSON request mode switched from format to prompt for model: test-model",
            "JSON request mode switched from prompt to format for model: test-model",
        ]

    @patch('requests.post')
    def test_auto_prompt_success_resets_consecutive_failures(self, mock_post):
        client = OllamaClient(max_retries=1, retry_delay=0)
        mock_post.side_effect = [fake_response(text) for text in
                                 ["", '{"ok": true}', "invalid", '{"ok": true}',
                                  "invalid", '{"ok": true}']]

        assert client.generate_json("JSON") == {"ok": True}
        assert client.generate_json("JSON") is None
        assert client.generate_json("JSON") == {"ok": True}
        assert client.generate_json("JSON") is None
        assert client.generate_json("JSON") == {"ok": True}
        payloads = [call.kwargs["json"] for call in mock_post.call_args_list]
        assert [p.get("format") for p in payloads] == ["json"] + [None] * 5

    @patch('requests.post')
    def test_auto_learns_per_model_and_per_client(self, mock_post):
        client = OllamaClient(model="first-model", max_retries=1, retry_delay=0)

        def respond(url, *, json, timeout):
            return fake_response("" if json.get("format") == "json" else '{"ok": true}')

        mock_post.side_effect = respond
        assert client.generate_json("JSON") == {"ok": True}
        client.model = "second-model"
        assert client.generate_json("JSON") == {"ok": True}
        client.model = "first-model"
        assert client.generate_json("JSON") == {"ok": True}
        fresh = OllamaClient(model="first-model", max_retries=1, retry_delay=0)
        assert fresh.generate_json("JSON") == {"ok": True}

        payloads = [call.kwargs["json"] for call in mock_post.call_args_list]
        assert [p.get("format") for p in payloads] == ["json", None, "json", None, None, "json", None]
        assert [p["model"] for p in payloads] == [
            "first-model", "first-model", "second-model", "second-model",
            "first-model", "first-model", "first-model",
        ]

    @patch('requests.post')
    def test_auto_fallback_preserves_generation_options(self, mock_post):
        client = OllamaClient(max_retries=1, retry_delay=0)
        mock_post.side_effect = [fake_response(""), fake_response('{"ok": true}')]
        assert client.generate_json(
            "Create an object", system_prompt="Follow the schema",
            temperature=0.2, max_tokens=100, images=[b"image"],
            num_ctx=1024, seed=42, top_p=0.8, think=True,
        ) == {"ok": True}

        first, second = [call.kwargs["json"] for call in mock_post.call_args_list]
        assert first["think"] is True
        assert second["think"] is False
        assert first["format"] == "json"
        assert "format" not in second
        assert first["options"] == second["options"] == {
            "temperature": 0.2, "num_predict": 100, "num_ctx": 1024,
            "seed": 42, "top_p": 0.8,
        }
        assert first["prompt"] == second["prompt"]
        assert first["prompt"].startswith("Follow the schema\n\nCreate an object")
        assert first["images"] == second["images"] == [base64.b64encode(b"image").decode("ascii")]

    @patch('requests.post')
    def test_validate_false_does_not_trigger_compatibility_retry(self, mock_post):
        client = OllamaClient(max_retries=1, retry_delay=0)
        mock_post.return_value = fake_response('```json\n{"ok": true}\n```')

        assert client.generate_json("JSON", validate=False) is None
        assert mock_post.call_count == 1
        assert mock_post.call_args.kwargs["json"]["format"] == "json"

    @patch('requests.post')
    def test_generate_forwards_top_level_think(self, mock_post):
        client = OllamaClient()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "ok"}
        mock_post.return_value = mock_response

        assert client.generate("Test", think=False) == "ok"
        payload = mock_post.call_args.kwargs["json"]
        assert payload["think"] is False

    @patch('requests.post')
    def test_generate_with_local_image_and_context_window(self, mock_post):
        """Images must be sent as base64 and num_ctx must reach Ollama."""
        client = OllamaClient()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "Image context"}
        mock_post.return_value = mock_response

        result = client.generate(
            "Describe this image",
            images=[b"image-bytes"],
            num_ctx=8192,
        )

        assert result == "Image context"
        payload = mock_post.call_args.kwargs["json"]
        assert payload["images"] == [base64.b64encode(b"image-bytes").decode("ascii")]
        assert payload["options"]["num_ctx"] == 8192

    @patch('requests.post')
    def test_generate_forwards_sampling_options_and_seed(self, mock_post):
        """Sampling controls must be present in the Ollama options payload."""
        client = OllamaClient()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "ok"}
        mock_post.return_value = mock_response

        assert client.generate(
            "Test",
            top_p=0.8,
            top_k=20,
            repeat_penalty=1.2,
            seed=42,
        ) == "ok"

        options = mock_post.call_args.kwargs["json"]["options"]
        assert options["top_p"] == 0.8
        assert options["top_k"] == 20
        assert options["repeat_penalty"] == 1.2
        assert options["seed"] == 42

    def test_generate_long_text_continues_after_token_limit(self):
        """Long local output should request a continuation only after truncation."""
        client = OllamaClient()
        calls = []

        def fake_generate_text(*args, **kwargs):
            calls.append(args[0])
            client.last_response_meta = {
                "done_reason": "length" if len(calls) == 1 else "stop"
            }
            return "first" if len(calls) == 1 else "second"

        with patch.object(client, "generate_text", side_effect=fake_generate_text):
            result = client.generate_long_text("Write", max_continuations=2)

        assert result == "first\n\nsecond"
        assert len(calls) == 2

    def test_generate_long_text_uses_continuation_seed_factory(self):
        """Continuation calls can receive deterministic per-part seeds."""
        client = OllamaClient()
        seeds = []

        def fake_generate_text(*args, **kwargs):
            seeds.append(kwargs["seed"])
            client.last_response_meta = {
                "done_reason": "length" if len(seeds) == 1 else "stop"
            }
            return "part"

        with patch.object(client, "generate_text", side_effect=fake_generate_text):
            client.generate_long_text(
                "Write",
                max_continuations=1,
                seed_factory=lambda index: 100 + index,
            )

        assert seeds == [100, 101]

    @patch('requests.post')
    def test_generate_retry_on_timeout(self, mock_post):
        """Test retry mechanism on timeout"""
        client = OllamaClient(max_retries=2, retry_delay=0)

        # First call times out, second succeeds
        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {
            "response": "Success"
        }

        mock_post.side_effect = [
            requests.exceptions.Timeout("Connection timed out"),
            mock_response_success,
        ]

        result = client.generate("Test prompt")
        assert result == "Success"
        assert mock_post.call_count == 2

    @patch('requests.post')
    def test_generate_retry_on_empty_response(self, mock_post):
        """Test retry on empty response from model"""
        client = OllamaClient(max_retries=2, retry_delay=0)

        mock_response_empty = Mock()
        mock_response_empty.json.return_value = {"response": ""}

        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {
            "response": "Success"
        }

        mock_post.side_effect = [mock_response_empty, mock_response_success]

        result = client.generate("Test prompt")
        assert result == "Success"
        assert mock_post.call_count == 2

    @patch('requests.post')
    def test_generate_all_retries_fail(self, mock_post):
        """Test that None is returned when all retries are exhausted"""
        client = OllamaClient(max_retries=2, retry_delay=0)

        mock_post.side_effect = requests.exceptions.Timeout("Connection timed out")

        result = client.generate("Test prompt")
        assert result is None
        assert mock_post.call_count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
