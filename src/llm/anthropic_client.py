"""Anthropic backend for the world-building pipeline.

The ``anthropic`` package is deliberately imported only when this backend is
constructed so Ollama-only installations can import the project unchanged.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

from loguru import logger


ImageInput = Union[str, Path, bytes]


class AnthropicClient:
    """Generate text through the official Anthropic Python SDK."""

    backend_name = "anthropic"
    schema_always_constrained = True

    def __init__(
        self,
        model: str,
        timeout: float = 900.0,
        max_retries: int = 2,
        request_options: Optional[Mapping[str, Any]] = None,
        client: Any = None,
    ):
        """Initialize the SDK client without accepting or storing credentials."""
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "The Anthropic backend requires the optional 'anthropic' package. "
                "Install requirements-cloud.txt to use it."
            ) from exc

        self._anthropic = anthropic
        self.model = model
        self.timeout = float(timeout)
        self.max_retries = max(0, int(max_retries))
        if request_options is None or "max_tokens" not in request_options:
            raise ValueError(
                "Anthropic request_options.max_tokens must be configured"
            )
        self.request_options = dict(request_options)
        self.last_response_meta: Dict[str, Any] = {}
        # Anthropic() resolves credentials using the SDK's normal environment
        # and profile mechanisms. No key is accepted as a constructor option.
        self.client = (
            client
            if client is not None
            else anthropic.Anthropic(
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
        )

        logger.info(
            f"Initialized AnthropicClient: model={self.model}, "
            f"request_options={sorted(self.request_options)}"
        )

    def check_ready(self) -> bool:
        """Check local SDK/authentication setup without making an API request."""
        return self.client is not None

    def generate_text(
        self,
        prompt: str,
        temperature: float = 1.0,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        images: Optional[List[ImageInput]] = None,
        format: Optional[Union[str, Dict[str, Any]]] = None,
        think: Optional[bool] = None,
        num_ctx: Optional[int] = None,
        seed: Optional[int] = None,
        **kwargs: Any,
    ) -> Optional[str]:
        """Generate text through a streaming Messages API call."""
        ignored = {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "format": format,
            "think": think,
            "num_ctx": num_ctx,
            "seed": seed,
            **kwargs,
        }
        self._log_ignored_options(ignored)

        request = dict(self.request_options)
        request["model"] = self.model
        request["messages"] = [
            {"role": "user", "content": self._message_content(prompt, images)}
        ]
        if system_prompt:
            request["system"] = system_prompt

        try:
            message = self._stream_message(request)
            return self._message_text(message)
        except self._anthropic.RateLimitError as exc:
            self._record_exception(exc, "rate_limit")
            return None
        except self._anthropic.BadRequestError as exc:
            self._record_exception(exc, "bad_request")
            return None
        except self._anthropic.APIStatusError as exc:
            status_code = getattr(exc, "status_code", 0) or 0
            self._record_exception(
                exc,
                "server_error" if status_code >= 500 else "api_error",
            )
            return None
        except self._anthropic.APIConnectionError as exc:
            self._record_exception(exc, "connection_error")
            return None
        except self._anthropic.AnthropicError as exc:
            self._record_exception(exc, "anthropic_error")
            return None
        except Exception as exc:
            self._record_exception(exc, "unexpected_error")
            return None

    def generate_schema(self, prompt, schema, *, system_prompt=None, images=None,
                        constrained=True, **kwargs):
        """Force a single tool call and return its input as raw JSON."""
        request = dict(self.request_options)
        request.update(model=self.model,
                       messages=[{"role": "user", "content": self._message_content(prompt, images)}],
                       tools=[{"name": "structured_output", "description": "Return the requested structured output",
                               "input_schema": schema}],
                       tool_choice={"type": "tool", "name": "structured_output"})
        if system_prompt:
            request["system"] = system_prompt
        try:
            message = self._stream_message(request)
            if self.last_response_meta.get("stop_reason") in {"max_tokens", "refusal"}:
                return None
            for block in self._value(message, "content", []) or []:
                if self._value(block, "type") == "tool_use" and self._value(block, "name") == "structured_output":
                    return json.dumps(self._value(block, "input"), ensure_ascii=False)
            return None
        except Exception as exc:
            self._record_exception(exc, "structured_error")
            return None

    def generate_long_text(
        self,
        prompt: str,
        temperature: float = 1.0,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        max_continuations: int = 3,
        **kwargs: Any,
    ) -> Optional[str]:
        """Generate long text in one streaming request up to max_tokens."""
        # The configured request options determine the long-form limit. If the
        # response reaches it, metadata records truncation for the pipeline.
        return self.generate_text(
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            **kwargs,
        )

    def _stream_message(self, request: Dict[str, Any]) -> Any:
        """Get the final message from the SDK streaming context manager."""
        stream_api = (
            self.client.beta.messages.stream
            if "betas" in request
            else self.client.messages.stream
        )
        with stream_api(**request) as stream:
            message = stream.get_final_message()
        return self._record_message(message)

    def _record_message(self, message: Any) -> Any:
        stop_reason = self._value(message, "stop_reason")
        stop_details = self._value(message, "stop_details")
        self.last_response_meta = {
            "stop_reason": stop_reason,
        }
        if stop_details is not None:
            self.last_response_meta["stop_details"] = self._plain_value(stop_details)

        if stop_reason == "max_tokens":
            self.last_response_meta["truncated"] = True
            logger.warning(
                "Anthropic response reached max_tokens; treating it as truncated"
            )
        elif stop_reason == "refusal":
            self.last_response_meta["failed"] = True
            logger.error(
                f"Anthropic model refused the request: "
                f"{self.last_response_meta.get('stop_details', {})}"
            )
        return message

    def _message_text(self, message: Any) -> Optional[str]:
        if self.last_response_meta.get("stop_reason") == "refusal":
            return None
        parts = []
        for block in self._value(message, "content", []) or []:
            if self._value(block, "type") != "text":
                continue
            text = self._value(block, "text")
            if text:
                parts.append(text)
        result = "".join(parts)
        return result or None

    def _record_exception(self, exc: Exception, category: str) -> None:
        self.last_response_meta = {
            "error": str(exc),
            "error_type": category,
        }
        logger.warning(f"Anthropic {category}: {exc}")

    @staticmethod
    def _value(value: Any, key: str, default: Any = None) -> Any:
        if isinstance(value, dict):
            return value.get(key, default)
        return getattr(value, key, default)

    @classmethod
    def _plain_value(cls, value: Any) -> Any:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, dict):
            return {key: cls._plain_value(item) for key, item in value.items()}
        return {
            key: cls._plain_value(getattr(value, key))
            for key in ("category", "explanation")
            if hasattr(value, key)
        } or str(value)

    @staticmethod
    def _message_content(prompt: str, images: Optional[List[ImageInput]]) -> Any:
        if not images:
            return prompt
        content: List[Dict[str, Any]] = []
        for image in images:
            if isinstance(image, bytes):
                raw = image
                media_type = "image/png"
            else:
                path = Path(image)
                raw = path.read_bytes()
                media_type = mimetypes.guess_type(path.name)[0] or "image/png"
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.b64encode(raw).decode("ascii"),
                    },
                }
            )
        content.append({"type": "text", "text": prompt})
        return content

    @staticmethod
    def _log_ignored_options(options: Dict[str, Any]) -> None:
        ignored = {key: value for key, value in options.items() if value is not None}
        if ignored:
            logger.debug(
                "Ignoring Ollama-only generation parameters in Anthropic backend: "
                f"{sorted(ignored)}"
            )
