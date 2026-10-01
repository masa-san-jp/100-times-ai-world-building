"""Text normalisation and character n-gram similarity helpers."""

from __future__ import annotations

import json
import unicodedata
from typing import Any, Set


def _item_text(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), default=str)
    return str(value)


def normalize_item(value: Any) -> str:
    """Normalize one text for duplicate detection."""
    text = unicodedata.normalize("NFKC", _item_text(value)).lower()
    return "".join(
        c for c in text
        if not c.isspace() and not unicodedata.category(c).startswith(("P", "S")))


def character_ngrams(value: str, size: int = 3) -> Set[str]:
    """Return the character n-grams used by duplicate checks."""
    if len(value) < size:
        return set()
    return {value[i:i + size] for i in range(len(value) - size + 1)}


def jaccard(left: Set[str], right: Set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0
