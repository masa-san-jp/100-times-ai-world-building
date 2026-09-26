"""Small backend interface used by the world-building pipeline."""

from typing import Any, Dict, List, Optional, Protocol, Union, runtime_checkable
from pathlib import Path

from .anthropic_client import AnthropicClient


@runtime_checkable
class LLMBackend(Protocol):
    """Operations required by :class:`src.pipeline.Pipeline`."""

    model: str

    def check_ready(self) -> bool:
        """Return whether this backend can accept generation requests."""

    def generate_text(
        self,
        prompt: str,
        temperature: float = 1.0,
        max_tokens: Optional[int] = 4096,
        system_prompt: Optional[str] = None,
        images: Optional[List[Union[str, Path, bytes]]] = None,
        **kwargs: Any,
    ) -> Optional[str]:
        """Generate free-form text."""

    def generate_json(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = 4096,
        system_prompt: Optional[str] = None,
        validate: bool = True,
        images: Optional[List[Union[str, Path, bytes]]] = None,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        """Generate and parse a JSON response."""

    def generate_long_text(
        self,
        prompt: str,
        temperature: float = 1.0,
        max_tokens: Optional[int] = 4096,
        system_prompt: Optional[str] = None,
        max_continuations: int = 3,
        **kwargs: Any,
    ) -> Optional[str]:
        """Generate long-form text, allowing backend-specific continuation."""


__all__ = ["LLMBackend", "AnthropicClient"]
