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
        assert not hasattr(client, "generate_json")

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

    @pytest.mark.parametrize("constrained", [True, False])
    @patch('requests.post')
    def test_generate_schema_forwards_schema_and_disables_thinking(self, mock_post, constrained):
        client = OllamaClient(max_retries=3)
        mock_post.return_value = fake_response('{"key":"value"}')
        schema = {"type": "object"}
        assert client.generate_schema("Test", schema, constrained=constrained, think=True,
            seed=42, images=[b"image"], num_ctx=1024, system_prompt="System") == '{"key":"value"}'
        payload = mock_post.call_args.kwargs["json"]
        assert payload.get("format") == (schema if constrained else None)
        assert payload["think"] is False
        assert payload["options"]["seed"] == 42 and payload["options"]["num_ctx"] == 1024
        assert payload["images"] == [base64.b64encode(b"image").decode("ascii")]
        assert payload["prompt"] == "System\n\nTest"
        assert mock_post.call_count == 1

    @patch('requests.post')
    def test_empty_schema_response_is_returned_without_hidden_retries(self, mock_post):
        mock_post.return_value = fake_response("")
        assert OllamaClient(max_retries=3).generate_schema("Test", {}, constrained=True) == ""
        assert mock_post.call_count == 1

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
