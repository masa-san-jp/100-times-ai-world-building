"""Accept user material without imposing a fixed creative schema.

This module is intentionally limited to intake.  It preserves the supplied
material, optionally adds a vision description, and records only explicit
statements plus unresolved questions and constraints returned by the backend.
It does not construct a setting, people, plot, or prose.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Union,
)

from ..llm import LLMBackend
from .schemas import load_schema
from .structured import generate_structured, StructuredFailure
from .graph import guess_language
from .language import language_name


RawInput = Union[str, bytes, Path]
ImageInput = Union[str, bytes, Path]


class InputSourceError(ValueError):
    """Raised when supplied input cannot be preserved or decoded."""


@dataclass(frozen=True)
class InputBriefResult:
    """The persisted brief and the source passed to the brief generator."""

    brief: Dict[str, Any]
    raw_source: str
    source_for_brief: str
    brief_path: Path
    raw_path: Path

    def to_dict(self) -> Dict[str, Any]:
        """Return a copy suitable for APIs and checkpoints."""
        return json.loads(json.dumps(self.brief, ensure_ascii=False))


class InputBriefBuilder:
    """Persist raw input and create a citation-checked input brief."""

    DEFAULT_SYSTEM_PROMPT = (
        "You extract information from supplied material. "
        "Return JSON only. Preserve uncertainty and do not add facts."
    )
    DEFAULT_USER_PROMPT = """SOURCE MATERIAL:
{source_text}

Return an object with exactly these arrays:
- statements: explicit claims in the source. Each item has text and quote.
- open_questions: points the source leaves unresolved and that later design may need to decide.
- constraints: requirements or prohibitions explicitly stated by the source.

For every statement, quote an exact contiguous substring of SOURCE MATERIAL.
Do not infer facts, classifications, causes, or requirements. A person or
group mentioned in the source is only a statement unless the source says more.
Do not write narrative prose or answer the open questions.

open_questions and constraints are arrays of plain strings. Do not output
ids; ids are assigned by the caller.

OUTPUT LANGUAGE: write the text of every statement, open question and
constraint in {language_name} (language code "{language}"). The one exception
is quote: it must stay exactly as written in SOURCE MATERIAL, never translated.
"""
    DEFAULT_VISION_SYSTEM_PROMPT = (
        "Describe only directly observable information from the supplied "
        "image. "
        "Return JSON only and do not infer context or intent."
    )
    DEFAULT_VISION_USER_PROMPT = "Describe directly observable information concisely."

    def __init__(
        self,
        backend: LLMBackend,
        input_dir: Union[str, Path],
        vision_backend: Optional[LLMBackend] = None,
        prompt: Optional[Mapping[str, str]] = None,
        vision_prompt: Optional[Mapping[str, str]] = None,
        language: Optional[str] = None,
        max_attempts: int = 3,
    ) -> None:
        self.max_attempts = max_attempts
        self.language = language
        self.backend = backend
        self.vision_backend = vision_backend or backend
        self.input_dir = Path(input_dir)
        self.prompt = dict(prompt or {})
        self.vision_prompt = dict(vision_prompt or {})

    def build(
        self,
        raw_input: RawInput = "",
        images: Optional[Sequence[ImageInput]] = None,
        source_name: Optional[str] = None,
    ) -> InputBriefResult:
        """Save original material and write a citation-checked brief."""
        raw_text, raw_bytes = self._read_raw_input(raw_input)
        self.input_dir.mkdir(parents=True, exist_ok=True)
        raw_path = self._write_raw(raw_text, raw_bytes, source_name)

        image_values = list(images or [])
        image_paths = self._save_images(image_values)
        source_for_brief = raw_text
        if image_values:
            description = self._describe_images(image_paths)
            if description:
                source_for_brief = self._append_image_description(
                    raw_text, description
                )
                (self.input_dir / "source_for_brief.txt").write_text(
                    source_for_brief, encoding="utf-8"
                )

        prompt_template = self.prompt.get("user", self.DEFAULT_USER_PROMPT)
        lang = self.language or guess_language(raw_text or source_for_brief)
        prompt = prompt_template.format(
            source_text=source_for_brief, language=lang,
            language_name=language_name(lang))
        result = generate_structured(
            self.backend, prompt, load_schema("input_brief"),
            task="input_brief", max_attempts=self.max_attempts,
            system_prompt=self.prompt.get(
                "system", self.DEFAULT_SYSTEM_PROMPT
            ),
        )
        if result.data is None:
            raise StructuredFailure("input_brief", result)
        brief = self._normalize_brief(result.data, source_for_brief)
        brief_path = self.input_dir / "input_brief.json"
        brief_path.write_text(
            json.dumps(brief, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return InputBriefResult(
            brief=brief,
            raw_source=raw_text,
            source_for_brief=source_for_brief,
            brief_path=brief_path,
            raw_path=raw_path,
        )

    accept = build

    def _read_raw_input(
        self, raw_input: RawInput
    ) -> tuple[str, Optional[bytes]]:
        if isinstance(raw_input, Path):
            if not raw_input.is_file():
                raise InputSourceError(f"Input file not found: {raw_input}")
            raw_bytes = raw_input.read_bytes()
            try:
                return raw_bytes.decode("utf-8"), raw_bytes
            except UnicodeDecodeError as exc:
                raise InputSourceError(
                    "Input file must be UTF-8 text"
                ) from exc
        if isinstance(raw_input, bytes):
            try:
                return raw_input.decode("utf-8"), raw_input
            except UnicodeDecodeError as exc:
                raise InputSourceError(
                    "Byte input must be UTF-8 text"
                ) from exc
        if not isinstance(raw_input, str):
            raise InputSourceError(
                "Input must be text, UTF-8 bytes, or a file path"
            )
        return raw_input, raw_input.encode("utf-8")

    def _write_raw(
        self,
        raw_text: str,
        raw_bytes: Optional[bytes],
        source_name: Optional[str],
    ) -> Path:
        if source_name:
            name = Path(source_name).name
            if not name:
                raise InputSourceError("source_name must contain a filename")
            raw_path = self.input_dir / name
        else:
            raw_path = self.input_dir / "user_input.txt"
        if raw_bytes is None:
            raw_path.write_text(raw_text, encoding="utf-8")
        else:
            raw_path.write_bytes(raw_bytes)
        return raw_path

    def _save_images(self, images: Iterable[ImageInput]) -> List[Path]:
        image_dir = self.input_dir / "images"
        paths: List[Path] = []
        for index, image in enumerate(images, start=1):
            if isinstance(image, Path) or isinstance(image, str):
                source = Path(image)
                if not source.is_file():
                    raise InputSourceError(f"Image file not found: {source}")
                destination = image_dir / source.name
                image_dir.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            elif isinstance(image, bytes):
                image_dir.mkdir(parents=True, exist_ok=True)
                destination = image_dir / f"image_{index}.bin"
                destination.write_bytes(image)
            else:
                raise InputSourceError("Images must be file paths or bytes")
            paths.append(destination)
        return paths

    def _describe_images(self, image_paths: Sequence[Path]) -> str:
        result = generate_structured(
            self.vision_backend,
            self.vision_prompt.get("user", self.DEFAULT_VISION_USER_PROMPT),
            load_schema("image_description"), task="image_description",
            max_attempts=self.max_attempts,
            system_prompt=self.vision_prompt.get("system", self.DEFAULT_VISION_SYSTEM_PROMPT),
            images=list(image_paths))
        if result.data is None:
            raise StructuredFailure("image_description", result)
        return result.data["description"].strip()

    @staticmethod
    def _append_image_description(raw_text: str, description: str) -> str:
        if raw_text:
            return f"{raw_text}\n\n[Image description]\n{description}"
        return f"[Image description]\n{description}"

    @staticmethod
    def _normalize_brief(
        response: Optional[Mapping[str, Any]], source_text: str
    ) -> Dict[str, Any]:
        statements: List[Dict[str, str]] = []
        raw_statements = response.get("statements", [])
        if isinstance(raw_statements, list):
            for item in raw_statements:
                text = item["text"].strip()
                quote = item.get("quote")
                if not text or not isinstance(quote, str):
                    continue
                if not quote.strip() or quote not in source_text:
                    continue
                statements.append(
                    {
                        "id": f"s{len(statements) + 1}",
                        "text": text,
                        "quote": quote,
                    }
                )

        return {
            "statements": statements,
            "open_questions": InputBriefBuilder._identified_list(
                response.get("open_questions", []), "q"
            ),
            "constraints": InputBriefBuilder._identified_list(
                response.get("constraints", []), "c"
            ),
        }

    @staticmethod
    def _identified_list(value: Any, prefix: str) -> List[Dict[str, str]]:
        return [{"id": f"{prefix}{index}", "text": text.strip()}
                for index, text in enumerate((t for t in value if t.strip()), 1)]


__all__ = ["InputBriefBuilder", "InputBriefResult", "InputSourceError"]
