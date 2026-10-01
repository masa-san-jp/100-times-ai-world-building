"""
Ollama Client Module
Handles all interactions with Ollama API
"""

import base64
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
import requests
from loguru import logger

from .llm import LLMBackend


class OllamaClient(LLMBackend):
    """Client for interacting with Ollama API"""

    backend_name = "ollama"

    def __init__(
        self,
        host: str = "http://localhost",
        port: int = 11434,
        model: Optional[str] = None,
        timeout: int = 300,
        max_retries: int = 3,
        retry_delay: int = 5,
    ):
        """
        Initialize Ollama client

        Args:
            host: Ollama server host
            port: Ollama server port
            model: Model name to use (taken from the configuration; no default)
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries on failure
            retry_delay: Delay between retries in seconds
        """
        self.base_url = f"{host}:{port}"
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.last_response_meta: Dict[str, Any] = {}

        logger.info(f"Initialized OllamaClient: {self.base_url}, model: {self.model}")

    def check_server(self) -> bool:
        """
        Check if Ollama server is running

        Returns:
            True if server is accessible, False otherwise
        """
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                logger.info("Ollama server is running")
                return True
            logger.warning(f"Ollama server returned status {response.status_code}")
            return False
        except requests.exceptions.ConnectionError:
            logger.error("Cannot connect to Ollama server")
            return False
        except Exception as e:
            logger.error(f"Error checking Ollama server: {e}")
            return False

    def list_models(self) -> List[Dict[str, Any]]:
        """
        List available models

        Returns:
            List of model information dictionaries
        """
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=10)
            response.raise_for_status()
            data = response.json()
            models = data.get("models", [])
            logger.info(f"Found {len(models)} models")
            return models
        except Exception as e:
            logger.error(f"Error listing models: {e}")
            return []

    def check_model_available(self, model_name: Optional[str] = None) -> bool:
        """
        Check if a specific model is available

        Args:
            model_name: Model name to check (uses self.model if None)

        Returns:
            True if model is available, False otherwise
        """
        if model_name is None:
            model_name = self.model

        models = self.list_models()
        model_names = [m.get("name", "") for m in models]

        if model_name in model_names:
            logger.info(f"Model {model_name} is available")
            return True

        logger.warning(f"Model {model_name} is not available")
        return False

    def pull_model(self, model_name: Optional[str] = None) -> bool:
        """
        Pull (download) a model from Ollama registry

        Args:
            model_name: Model name to pull (uses self.model if None)

        Returns:
            True if successful, False otherwise
        """
        if model_name is None:
            model_name = self.model

        logger.info(f"Pulling model: {model_name}")

        try:
            response = requests.post(
                f"{self.base_url}/api/pull",
                json={"name": model_name},
                stream=True,
                timeout=self.timeout,
            )
            response.raise_for_status()

            # Stream progress updates
            for line in response.iter_lines():
                if line:
                    data = json.loads(line)
                    status = data.get("status", "")
                    if status:
                        logger.info(f"Pull status: {status}")

            logger.info(f"Model {model_name} pulled successfully")
            return True

        except Exception as e:
            logger.error(f"Error pulling model {model_name}: {e}")
            return False

    def ensure_model_ready(self) -> bool:
        """
        Ensure the configured model is ready to use
        Downloads it if not available

        Returns:
            True if model is ready, False otherwise
        """
        if self.check_model_available():
            return True

        logger.info(f"Model {self.model} not found, attempting to pull...")
        return self.pull_model()

    def check_ready(self) -> bool:
        """Check the Ollama server and make this client's model available."""
        return self.check_server() and self.ensure_model_ready()

    def generate(
        self,
        prompt: str,
        format: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
        images: Optional[List[Union[str, Path, bytes]]] = None,
        num_ctx: Optional[int] = None,
        think: Optional[bool] = None,
        **kwargs,
    ) -> Optional[str]:
        """
        Generate text using Ollama API

        Args:
            prompt: Input prompt
            format: Output format ("json" or "" for free text)
            temperature: Generation temperature (0.0-2.0)
            max_tokens: Maximum tokens to generate
            system_prompt: Optional system prompt
            think: Whether to request a separate reasoning trace from models
                that support Ollama's top-level ``think`` option.
            **kwargs: Additional options to pass to Ollama

        Returns:
            Generated text, or None on failure
        """
        # Combine system prompt with user prompt if provided
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"
        else:
            full_prompt = prompt

        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                **kwargs,
            },
        }

        if num_ctx is not None:
            payload["options"]["num_ctx"] = num_ctx

        if images:
            payload["images"] = [self._encode_image(image) for image in images]

        # Add format if specified
        if format:
            payload["format"] = format
        if think is not None:
            # ``think`` is an Ollama request field, not a sampling option.
            payload["think"] = think

        for attempt in range(self.max_retries):
            try:
                logger.debug(f"Generating (attempt {attempt + 1}/{self.max_retries})")

                response = requests.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()

                data = response.json()
                generated_text = data.get("response", "")
                self.last_response_meta = data

                if generated_text:
                    logger.debug(f"Generated {len(generated_text)} characters")
                    return generated_text

                logger.warning("Empty response from Ollama")

            except requests.exceptions.Timeout:
                logger.warning(f"Request timeout (attempt {attempt + 1})")
            except requests.exceptions.RequestException as e:
                logger.error(f"Request error: {e}")
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
            except Exception as e:
                logger.error(f"Unexpected error: {e}")

            # Wait before retry
            if attempt < self.max_retries - 1:
                logger.info(f"Retrying in {self.retry_delay} seconds...")
                time.sleep(self.retry_delay)

        logger.error("All retry attempts failed")
        return None

    @staticmethod
    def _encode_image(image: Union[str, Path, bytes]) -> str:
        """Convert a local image path or bytes to Ollama's base64 format."""
        if isinstance(image, bytes):
            raw = image
        else:
            raw = Path(image).read_bytes()
        return base64.b64encode(raw).decode("ascii")

    def generate_json(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
        validate: bool = True,
        images: Optional[List[Union[str, Path, bytes]]] = None,
        num_ctx: Optional[int] = None,
        **kwargs,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate JSON output

        Args:
            prompt: Input prompt
            temperature: Generation temperature
            max_tokens: Maximum tokens to generate
            system_prompt: Optional system prompt
            validate: Whether to validate JSON output

        Returns:
            Parsed JSON dictionary, or None on failure
        """
        # Ensure prompt explicitly requests JSON
        if "JSON" not in prompt and "json" not in prompt:
            prompt = f"{prompt}\n\n重要: 必ず有効なJSON形式で出力してください。"

        response = self.generate(
            prompt=prompt,
            format="json",
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            images=images,
            num_ctx=num_ctx,
            **kwargs,
        )

        if response is None:
            return None

        parsed = self._parse_json(response, validate=validate)
        if parsed is not None:
            return parsed

        # Some local reasoning models may accept
        # ``format=json`` but return their planning text instead of a JSON
        # document. Preserve the configured structured-format request above,
        # then make one explicit compatibility fallback. The same kwargs,
        # including the request seed, are reused for this logical retry.
        if validate:
            logger.warning(
                "Structured JSON response was invalid; retrying with prompt-"
                "constrained JSON and thinking disabled"
            )
            fallback_kwargs = dict(kwargs)
            fallback_kwargs.pop("think", None)
            fallback = self.generate(
                prompt=prompt,
                format="",
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
                images=images,
                num_ctx=num_ctx,
                think=False,
                **fallback_kwargs,
            )
            if fallback:
                parsed = self._parse_json(fallback, validate=True)
                if parsed is not None:
                    logger.info("JSON compatibility fallback succeeded")
                    return parsed

        logger.error("Failed to parse JSON after all retries")
        return None

    @staticmethod
    def _parse_json(
        response: str,
        validate: bool = True,
    ) -> Optional[Union[Dict[str, Any], List[Any]]]:
        """Parse JSON, including common fenced-output wrappers."""
        candidate = response
        for attempt in range(3 if validate else 1):
            try:
                data = json.loads(candidate)
                logger.debug("Successfully parsed JSON")
                return data
            except json.JSONDecodeError as exc:
                logger.warning(f"JSON parse error (attempt {attempt + 1}): {exc}")

                if validate and attempt < 2:
                    candidate = candidate.strip()
                    if not candidate.startswith("{") and not candidate.startswith("["):
                        if "```json" in candidate:
                            candidate = candidate.split("```json", 1)[1].split("```", 1)[0]
                        elif "```" in candidate:
                            candidate = candidate.split("```", 1)[1].split("```", 1)[0]
                    else:
                        break
                else:
                    break
        return None

    def generate_text(
        self,
        prompt: str,
        temperature: float = 1.0,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
        images: Optional[List[Union[str, Path, bytes]]] = None,
        num_ctx: Optional[int] = None,
        format: Optional[Union[str, Dict[str, Any]]] = None,
        think: Optional[bool] = None,
        **kwargs,
    ) -> Optional[str]:
        """
        Generate free-form text (descriptions, documents)

        Args:
            prompt: Input prompt
            temperature: Generation temperature (higher = more creative)
            max_tokens: Maximum tokens to generate
            system_prompt: Optional system prompt

        Returns:
            Generated text, or None on failure
        """
        return self.generate(
            prompt=prompt,
            format=format,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            images=images,
            num_ctx=num_ctx,
            think=think,
            **kwargs,
        )

    def generate_long_text(
        self,
        prompt: str,
        temperature: float = 1.0,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
        max_continuations: int = 3,
        continuation_tail_chars: int = 6000,
        num_ctx: Optional[int] = None,
        seed: Optional[int] = None,
        seed_factory=None,
        **kwargs,
    ) -> Optional[str]:
        """Generate long text over multiple local calls when Ollama hits its limit.

        Ollama reports ``done_reason=length`` when a response reaches
        ``num_predict``.  Only then is a continuation requested, so normal
        short outputs still use a single call.
        """
        resolve_seed = seed_factory or (lambda _index: seed)
        first = self.generate_text(
            prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            num_ctx=num_ctx,
            seed=resolve_seed(0),
            **kwargs,
        )
        if not first:
            return first

        parts = [first]
        for continuation_index in range(1, max(0, max_continuations) + 1):
            if self.last_response_meta.get("done_reason") not in {"length", "max_tokens"}:
                break

            continuation_prompt = (
                "以下の小説本文の続きを執筆してください。"
                "すでに書かれた文章を繰り返さず、物語本文だけを続けてください。\n\n"
                f"直前の本文:\n{''.join(parts)[-continuation_tail_chars:]}"
            )
            continuation = self.generate_text(
                continuation_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
                num_ctx=num_ctx,
                seed=resolve_seed(continuation_index),
                **kwargs,
            )
            if not continuation:
                break
            parts.append(continuation)

        return "\n\n".join(parts)
