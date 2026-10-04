"""Output-language helpers shared by the brief, axes and prompts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
DEFAULT_LANGUAGES_PATH = CONFIG_DIR / "world" / "languages.yaml"
DEFAULT_RULES_PATH = CONFIG_DIR / "world" / "language_rules.yaml"

FALLBACK_LANGUAGE = "en"


def load_language_rules(path: Any = None) -> Dict[str, Any]:
    return yaml.safe_load(
        Path(path or DEFAULT_RULES_PATH).read_text(encoding="utf-8")) or {}


def rules_for(rules: Mapping[str, Any], language: str) -> Dict[str, Any]:
    """Grammar shared by normalization and verification, with default fallback."""
    code = str(language or "").split("-")[0].split("_")[0].lower()
    merged = dict(rules.get("default") or {})
    merged.update(rules.get(code) or {})
    return merged


def load_language_names(path: Any = None) -> Dict[str, str]:
    data = yaml.safe_load(
        Path(path or DEFAULT_LANGUAGES_PATH).read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in data.items()}


def language_name(code: Optional[str],
                  names: Optional[Mapping[str, str]] = None) -> str:
    """Name to put in a prompt for language ``code`` (``und`` = the input's)."""
    names = names if names is not None else load_language_names()
    code = (code or "und").split("-")[0].split("_")[0].lower() or "und"
    return names.get(code) or (names.get("und", code) if code == "und" else code)


def localized(value: Any, language: Optional[str],
              fallback: str = FALLBACK_LANGUAGE) -> str:
    """Pick the text for ``language`` from ``{code: text}`` (or a plain string).

    Falls back to ``fallback`` (``en``), then to any entry.
    """
    if isinstance(value, Mapping):
        code = (language or "").split("-")[0].split("_")[0].lower()
        for key in (code, fallback):
            if value.get(key):
                return str(value[key])
        for v in value.values():
            if v:
                return str(v)
        return ""
    return "" if value is None else str(value)


__all__ = ["FALLBACK_LANGUAGE", "language_name", "load_language_names",
           "localized", "load_language_rules", "rules_for"]
