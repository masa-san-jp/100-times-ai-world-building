"""Deterministic LLM backend for unit tests and local development.

The fake deliberately does not inspect or rewrite prompts.  Callers provide
the responses they want to exercise, which keeps tests independent from a
real model and makes repeated runs reproducible.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


ResponseSource = Union[
    Mapping[str, Any],
    Iterable[Mapping[str, Any]],
    Callable[[str], Mapping[str, Any]],
]


class FakeLLMBackend:
    """A small deterministic implementation of :class:`LLMBackend`.

    ``json_responses`` may be a mapping, a finite iterable, or a callable.
    Iterable responses are consumed in order.  A missing response produces an
    empty input-brief-shaped object, which is useful for tests that only need
    to exercise persistence.
    """

    model = "fake"
    backend_name = "fake"

    def __init__(
        self,
        json_responses: Optional[ResponseSource] = None,
        text_responses: Optional[Iterable[str]] = None,
    ) -> None:
        self._json_source = json_responses
        self._json_iterator = (
            iter(json_responses)
            if json_responses is not None
            and not isinstance(json_responses, Mapping)
            and not callable(json_responses)
            else None
        )
        self._text_iterator = iter(text_responses or ())
        self.json_prompts: List[str] = []
        self.text_prompts: List[str] = []
        self.last_response_meta: Dict[str, Any] = {}

    def check_ready(self) -> bool:
        return True

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
        del temperature, max_tokens, system_prompt, validate, images, kwargs
        self.json_prompts.append(prompt)
        source = self._json_source
        if callable(source):
            response = source(prompt)
        elif isinstance(source, Mapping):
            response = source
        elif self._json_iterator is not None:
            try:
                response = next(self._json_iterator)
            except StopIteration:
                response = None
        else:
            response = None
        if response is None:
            return {"statements": [], "open_questions": [], "constraints": []}
        return copy.deepcopy(dict(response))

    def generate_text(
        self,
        prompt: str,
        temperature: float = 1.0,
        max_tokens: Optional[int] = 4096,
        system_prompt: Optional[str] = None,
        images: Optional[List[Union[str, Path, bytes]]] = None,
        **kwargs: Any,
    ) -> Optional[str]:
        del temperature, max_tokens, system_prompt, images, kwargs
        self.text_prompts.append(prompt)
        try:
            return next(self._text_iterator)
        except StopIteration:
            return ""

    def generate_long_text(
        self,
        prompt: str,
        temperature: float = 1.0,
        max_tokens: Optional[int] = 4096,
        system_prompt: Optional[str] = None,
        max_continuations: int = 3,
        **kwargs: Any,
    ) -> Optional[str]:
        del max_continuations
        return self.generate_text(
            prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            **kwargs,
        )


DeterministicFakeBackend = FakeLLMBackend


__all__ = ["FakeLLMBackend", "DeterministicFakeBackend"]
