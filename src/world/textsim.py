"""Text normalisation and character n-gram similarity helpers."""

from __future__ import annotations

import json
import re
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


def is_cjk_char(ch: str) -> bool:
    """Kana, Han ideographs and Hangul (scripts written without spaces)."""
    o = ord(ch)
    return (0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x4DBF
            or 0x4E00 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7AF
            or 0xFF66 <= o <= 0xFF9F)


def _is_hiragana(ch: str) -> bool:
    return 0x3040 <= ord(ch) <= 0x309F


def is_cjk_text(text: str) -> bool:
    """True when most letters of ``text`` are CJK."""
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(is_cjk_char(c) for c in letters) * 2 >= len(letters)


def ngrams_of(text: Any, size: int = 3) -> Set[str]:
    """Character n-grams of the normalized ``text``."""
    return character_ngrams(normalize_item(text), size)


def echo_coverage(text: Any, reference: Any, min_len: int = 2) -> float:
    """Share of ``text`` that is made of wording found in ``reference``.

    CJK text is matched by character runs of at least ``min_len`` that are
    not hiragana-only (particles match everywhere); other scripts are
    matched word by word (words of 3+ letters).  The result is in [0, 1];
    1 means the text is built entirely from the reference's own words.
    """
    ref = normalize_item(reference)
    norm = normalize_item(text)
    if not norm or not ref:
        return 0.0
    if is_cjk_text(norm):
        covered, i = 0, 0
        while i < len(norm):
            best = 0
            for j in range(len(norm), i + min_len - 1, -1):
                seg = norm[i:j]
                if all(_is_hiragana(c) for c in seg):
                    continue
                if seg in ref:
                    best = j - i
                    break
            if best:
                covered += best
                i += best
            else:
                i += 1
        return covered / len(norm)
    ref_words = set(re.findall(r"[^\W\d_]{3,}", unicodedata.normalize(
        "NFKC", str(reference)).lower()))
    words = re.findall(r"[^\W\d_]{3,}", unicodedata.normalize(
        "NFKC", str(text)).lower())
    total = sum(len(w) for w in words)
    if not total:
        return 0.0
    return sum(len(w) for w in words if w in ref_words) / total
