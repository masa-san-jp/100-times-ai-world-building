"""Quality checks for one generated world package."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
)

import yaml

from .utils import load_config
from .validation import validate_artifact, validate_text


DEFAULT_NEAR_DUPLICATE_THRESHOLD = 0.8
DEFAULT_MIN_CHAPTER_CHARACTERS = 2000
CHAPTER_COUNT = 10
END_OF_SENTENCE_CHARACTERS = set("。！？!?．.」』】〕》〉\"'”’…")
TRAILING_SEPARATOR_LINE = re.compile(r"^[\s*＊\-－=＝#※]+$")

LIST_SPECS = (
    ("01_desire_list", "desires"),
    ("02_ability_list", "abilities"),
    ("03_role_list", "roles"),
    ("18_people_list", "people"),
)


def _item_text(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    return str(value)


def normalize_item(value: Any) -> str:
    """Normalize one list item for duplicate detection."""
    text = unicodedata.normalize("NFKC", _item_text(value)).lower()
    return "".join(
        character
        for character in text
        if not character.isspace()
        and not unicodedata.category(character).startswith(("P", "S"))
    )


def _character_ngrams(value: str, size: int = 3) -> Set[str]:
    if len(value) < size:
        return set()
    return {
        value[index:index + size] for index in range(len(value) - size + 1)
    }


def _jaccard(left: Set[str], right: Set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def analyze_duplicates(
    items: Sequence[Any],
    threshold: float = DEFAULT_NEAR_DUPLICATE_THRESHOLD,
) -> Dict[str, Any]:
    """Return exact, normalized, and character 3-gram duplicate metrics."""
    values = [_item_text(item) for item in items]
    normalized = [normalize_item(item) for item in values]
    exact_unique_count = len(set(values))
    normalized_unique_count = len(set(normalized))

    near_duplicate_pair_count = 0
    for index, left in enumerate(normalized):
        left_grams = _character_ngrams(left)
        if not left_grams:
            continue
        for right in normalized[index + 1:]:
            if left == right:
                continue
            right_grams = _character_ngrams(right)
            if right_grams and _jaccard(left_grams, right_grams) >= threshold:
                near_duplicate_pair_count += 1

    return {
        "item_count": len(values),
        "exact_duplicate_count": len(values) - exact_unique_count,
        "normalized_duplicate_count": len(values) - normalized_unique_count,
        "near_duplicate_pair_count": near_duplicate_pair_count,
        "exact_unique_count": exact_unique_count,
        "normalized_unique_count": normalized_unique_count,
        "unique_count": normalized_unique_count,
        "valid_count": normalized_unique_count,
    }


def _status_rank(status: str) -> int:
    return {"pass": 0, "warn": 1, "fail": 2}[status]


def _worst_status(statuses: Iterable[str]) -> str:
    return max(statuses, key=_status_rank, default="pass")


def _load_yaml(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")), None
    except OSError as exc:
        return None, str(exc)
    except yaml.YAMLError as exc:
        return None, f"invalid YAML: {exc}"


def _read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        return path.read_text(encoding="utf-8"), None
    except OSError as exc:
        return None, str(exc)


def _quality_config(
    config_path: str = "config/ollama_config.yaml",
    config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    loaded = dict(config) if config is not None else load_config(config_path)
    if isinstance(loaded, dict) and "quality" in loaded:
        quality = loaded.get("quality", {})
    else:
        quality = loaded if isinstance(loaded, dict) else {}
    if not isinstance(quality, dict):
        quality = {}
    threshold = quality.get(
        "near_duplicate_threshold", DEFAULT_NEAR_DUPLICATE_THRESHOLD
    )
    minimum = quality.get(
        "min_chapter_characters",
        quality.get("min_chapter_length", DEFAULT_MIN_CHAPTER_CHARACTERS),
    )
    return {
        "near_duplicate_threshold": float(threshold),
        "min_chapter_characters": int(minimum),
    }


def _list_quality(
    intermediate_dir: Path,
    threshold: float,
) -> Dict[str, Any]:
    lists: Dict[str, Any] = {}
    for filename, key in LIST_SPECS:
        path = intermediate_dir / f"{filename}.yaml"
        if not path.is_file():
            lists[filename] = {
                "status": "fail",
                "items": 0,
                "errors": [f"missing file: {path.name}"],
            }
            continue

        data, error = _load_yaml(path)
        if error:
            lists[filename] = {
                "status": "fail",
                "items": 0,
                "errors": [error],
            }
            continue
        items = data.get(key) if isinstance(data, dict) else None
        if not isinstance(items, list):
            lists[filename] = {
                "status": "fail",
                "items": 0,
                "errors": [f"{key} must be a list"],
            }
            continue

        metrics = analyze_duplicates(items, threshold=threshold)
        status = (
            "warn"
            if any(
                metrics[field] > 0
                for field in (
                    "exact_duplicate_count",
                    "normalized_duplicate_count",
                    "near_duplicate_pair_count",
                )
            )
            else "pass"
        )
        lists[filename] = {"status": status, **metrics}

    return {
        "status": _worst_status(entry["status"] for entry in lists.values()),
        "threshold": threshold,
        "lists": lists,
    }


def _plot_path(world_dir: Path, chapter_number: int) -> Path:
    filename = f"{20 + chapter_number:02d}_plot_{chapter_number}.yaml"
    return world_dir / "intermediate" / filename


def _novel_path(world_dir: Path, chapter_number: int) -> Path:
    filename = f"chapter_{chapter_number:02d}.txt"
    final_path = world_dir / "final" / "novels" / filename
    if final_path.is_file():
        return final_path
    legacy_path = world_dir / "novels" / f"chapter_{chapter_number:02d}.txt"
    return legacy_path if legacy_path.is_file() else final_path


def _character_name_variants(name: str) -> List[str]:
    variants = [name.strip()]
    without_annotation = re.sub(
        r"\s*[（(][^（）()]*[）)]\s*$", "", name
    ).strip()
    if without_annotation and without_annotation not in variants:
        variants.append(without_annotation)
        variants.extend(
            part
            for part in re.split(r"[・･＝=\s]+", without_annotation)
            if len(part) >= 2 and part not in variants
        )
    return variants


def _contains_character(text: str, name: str) -> bool:
    folded_text = text.casefold()
    return any(
        variant.casefold() in folded_text
        for variant in _character_name_variants(name)
    )


def _character_quality(world_dir: Path) -> Dict[str, Any]:
    path = world_dir / "intermediate" / "06_characters_list.yaml"
    if not path.is_file():
        return {
            "status": "fail",
            "characters": [],
            "unseen_in_plot": [],
            "unseen_in_novel": [],
            "errors": [f"missing file: {path.name}"],
        }

    data, error = _load_yaml(path)
    if error:
        return {
            "status": "fail",
            "characters": [],
            "unseen_in_plot": [],
            "unseen_in_novel": [],
            "errors": [error],
        }
    characters = data.get("characters") if isinstance(data, dict) else None
    if not isinstance(characters, list):
        return {
            "status": "fail",
            "characters": [],
            "unseen_in_plot": [],
            "unseen_in_novel": [],
            "errors": ["characters must be a list"],
        }

    plot_texts: Dict[int, str] = {}
    novel_texts: Dict[int, str] = {}
    errors: List[str] = []
    for chapter_number in range(1, CHAPTER_COUNT + 1):
        plot_path = _plot_path(world_dir, chapter_number)
        novel_path = _novel_path(world_dir, chapter_number)
        plot_text, plot_error = _read_text(plot_path)
        novel_text, novel_error = _read_text(novel_path)
        if plot_error is None and plot_text is not None:
            plot_texts[chapter_number] = plot_text
        if novel_error is None and novel_text is not None:
            novel_texts[chapter_number] = novel_text

    results: List[Dict[str, Any]] = []
    unseen_in_plot: List[str] = []
    unseen_in_novel: List[str] = []
    for character in characters:
        if not isinstance(character, dict) or not character.get("name"):
            errors.append("each character must have a name")
            continue
        name = str(character["name"])
        plot_chapters = [
            chapter
            for chapter, text in plot_texts.items()
            if _contains_character(text, name)
        ]
        novel_chapters = [
            chapter
            for chapter, text in novel_texts.items()
            if _contains_character(text, name)
        ]
        character_status = (
            "pass" if plot_chapters and novel_chapters else "warn"
        )
        if not plot_chapters:
            unseen_in_plot.append(name)
        if not novel_chapters:
            unseen_in_novel.append(name)
        results.append(
            {
                "name": name,
                "plot_chapters": plot_chapters,
                "novel_chapters": novel_chapters,
                "plot_chapter_count": len(plot_chapters),
                "novel_chapter_count": len(novel_chapters),
                "status": character_status,
            }
        )

    statuses = [entry["status"] for entry in results]
    if errors:
        statuses.append("fail")
    return {
        "status": _worst_status(statuses),
        "characters": results,
        "unseen_in_plot": unseen_in_plot,
        "unseen_in_novel": unseen_in_novel,
        "errors": errors,
    }


def _last_content_character(text: str) -> Optional[str]:
    lines = text.splitlines()
    while lines:
        line = lines[-1]
        if not line.strip() or TRAILING_SEPARATOR_LINE.fullmatch(line):
            lines.pop()
            continue
        return line.rstrip()[-1] if line.rstrip() else None
    return None


def _novel_quality(world_dir: Path, minimum: int) -> Dict[str, Any]:
    chapters: Dict[str, Any] = {}
    errors: List[str] = []
    existing_lengths: List[int] = []

    for chapter_number in range(1, CHAPTER_COUNT + 1):
        path = _novel_path(world_dir, chapter_number)
        chapter_key = f"{chapter_number:02d}"
        if not path.is_file():
            chapters[chapter_key] = {
                "status": "fail",
                "character_count": 0,
                "errors": [f"missing file: {path.name}"],
            }
            errors.append(f"chapter {chapter_number}: missing file")
            continue

        text, error = _read_text(path)
        if error or text is None:
            message = error or "could not read text"
            chapters[chapter_key] = {
                "status": "fail",
                "character_count": 0,
                "errors": [message],
            }
            errors.append(f"chapter {chapter_number}: {message}")
            continue

        character_count = len(text)
        existing_lengths.append(character_count)
        chapter_errors = validate_text(text)
        warnings: List[str] = []
        if character_count < minimum:
            warnings.append(f"below minimum character count ({minimum})")
        if _last_content_character(text) not in END_OF_SENTENCE_CHARACTERS:
            warnings.append("ending does not look like a sentence ending")
        if chapter_errors:
            errors.extend(
                f"chapter {chapter_number}: {message}"
                for message in chapter_errors
            )
        status = "fail" if chapter_errors else "warn" if warnings else "pass"
        chapters[chapter_key] = {
            "status": status,
            "character_count": character_count,
            "warnings": warnings,
            "errors": chapter_errors,
        }

    summary = {
        "chapter_count": len(existing_lengths),
        "min_character_count": (
            min(existing_lengths) if existing_lengths else None
        ),
        "max_character_count": (
            max(existing_lengths) if existing_lengths else None
        ),
        "average_character_count": (
            sum(existing_lengths) / len(existing_lengths)
            if existing_lengths
            else None
        ),
        "below_minimum_chapters": [
            chapter
            for chapter, result in chapters.items()
            if "below minimum character count"
            in " ".join(result.get("warnings", []))
        ],
        "truncated_suspected_chapters": [
            chapter
            for chapter, result in chapters.items()
            if "ending does not look like a sentence ending"
            in " ".join(result.get("warnings", []))
        ],
    }
    statuses = [result["status"] for result in chapters.values()]
    return {
        "status": _worst_status(statuses),
        "minimum_character_count": minimum,
        "chapters": chapters,
        "summary": summary,
        "errors": errors,
    }


def _chapter_structure_quality(world_dir: Path) -> Dict[str, Any]:
    chapters: Dict[str, Any] = {}
    for chapter_number in range(1, CHAPTER_COUNT + 1):
        chapter_key = f"{chapter_number:02d}"
        plot_path = _plot_path(world_dir, chapter_number)
        novel_path = _novel_path(world_dir, chapter_number)
        errors: List[str] = []

        if not plot_path.is_file():
            errors.append(f"missing plot: {plot_path.name}")
        else:
            plot_data, plot_error = _load_yaml(plot_path)
            if plot_error:
                errors.append(f"plot: {plot_error}")
            else:
                errors.extend(
                    f"plot: {message}"
                    for message in validate_artifact(
                        "plot_chapter",
                        plot_data,
                        chapter_number=chapter_number,
                    )
                )

        if not novel_path.is_file():
            errors.append(f"missing novel: {novel_path.name}")
        else:
            novel_text, novel_error = _read_text(novel_path)
            if novel_error:
                errors.append(f"novel: {novel_error}")
            else:
                errors.extend(
                    f"novel: {message}"
                    for message in validate_text(novel_text)
                )

        chapters[chapter_key] = {
            "status": "fail" if errors else "pass",
            "plot_present": plot_path.is_file(),
            "novel_present": novel_path.is_file(),
            "errors": errors,
        }

    return {
        "status": _worst_status(
            entry["status"] for entry in chapters.values()
        ),
        "expected_chapter_count": CHAPTER_COUNT,
        "plot_chapter_count": sum(
            entry["plot_present"] for entry in chapters.values()
        ),
        "novel_chapter_count": sum(
            entry["novel_present"] for entry in chapters.values()
        ),
        "chapters": chapters,
    }


def generate_quality_report(
    world_dir: Path,
    config_path: str = "config/ollama_config.yaml",
    config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate a quality report without external APIs."""
    world_path = Path(world_dir)
    if not world_path.is_dir():
        raise ValueError(f"World directory does not exist: {world_path}")

    quality_config = _quality_config(config_path=config_path, config=config)
    threshold = quality_config["near_duplicate_threshold"]
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(
            "quality.near_duplicate_threshold must be between 0 and 1"
        )
    minimum = quality_config["min_chapter_characters"]
    if minimum < 0:
        raise ValueError("quality.min_chapter_characters must not be negative")

    checks = {
        "duplicates": _list_quality(world_path / "intermediate", threshold),
        "character_consistency": _character_quality(world_path),
        "novel_text": _novel_quality(world_path, minimum),
        "chapter_structure": _chapter_structure_quality(world_path),
    }
    status = _worst_status(check["status"] for check in checks.values())
    return {
        "world_dir": str(world_path),
        "status": status,
        "overall_status": status,
        "config": quality_config,
        "checks": checks,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact human-readable Markdown report."""
    checks = report["checks"]
    lines = [
        "# Quality Report",
        "",
        f"- World: `{report['world_dir']}`",
        f"- Overall: **{str(report['status']).upper()}**",
        "",
        "## Summary",
        "",
    ]
    for key, check in checks.items():
        lines.append(f"- {key}: **{str(check['status']).upper()}**")

    duplicates = checks["duplicates"]
    lines.extend(["", "## 1. 100-item list duplicates", ""])
    for filename, result in duplicates["lists"].items():
        if result["status"] == "fail":
            lines.append(
                f"- `{filename}`: **FAIL** — {'; '.join(result['errors'])}"
            )
            continue
        lines.append(
            f"- `{filename}`: {result['status']} — "
            f"items={result['item_count']}, "
            f"exact_duplicates={result['exact_duplicate_count']}, "
            f"normalized_duplicates={result['normalized_duplicate_count']}, "
            f"near_pairs={result['near_duplicate_pair_count']}, "
            f"unique={result['unique_count']}"
        )

    characters = checks["character_consistency"]
    lines.extend(["", "## 2. Character consistency", ""])
    for character in characters["characters"]:
        lines.append(
            f"- `{character['name']}`: {character['status']} — "
            f"plot chapters={character['plot_chapters']}, "
            f"novel chapters={character['novel_chapters']}"
        )
    if characters.get("unseen_in_plot"):
        names = "、".join(characters["unseen_in_plot"])
        lines.append(
            "- 章プロットに主要キャラクター名が1件も見つからない"
            f"（{names}）: 章プロットとキャラクター一覧の名前が一致していない可能性"
        )
    for error in characters.get("errors", []):
        lines.append(f"- **Error:** {error}")

    novels = checks["novel_text"]
    summary = novels["summary"]
    lines.extend(
        [
            "",
            "## 3. Novel text",
            "",
            f"- Character counts: min={summary['min_character_count']}, "
            f"max={summary['max_character_count']}, "
            f"average={summary['average_character_count']}",
            f"- Below minimum: `{summary['below_minimum_chapters']}`",
            f"- Truncation suspected: "
            f"`{summary['truncated_suspected_chapters']}`",
        ]
    )
    for chapter, result in novels["chapters"].items():
        warnings = "; ".join(result.get("warnings", []))
        suffix = f" — {warnings}" if warnings else ""
        lines.append(
            f"- chapter_{chapter}: {result['status']}, "
            f"{result['character_count']} characters{suffix}"
        )

    structure = checks["chapter_structure"]
    lines.extend(
        [
            "",
            "## 4. Chapter structure",
            "",
            f"- Plot chapters: {structure['plot_chapter_count']}/"
            f"{structure['expected_chapter_count']}",
            f"- Novel chapters: {structure['novel_chapter_count']}/"
            f"{structure['expected_chapter_count']}",
        ]
    )
    for chapter, result in structure["chapters"].items():
        if result["errors"]:
            lines.append(
                f"- chapter_{chapter}: **FAIL** — "
                f"{'; '.join(result['errors'])}"
            )

    return "\n".join(lines) + "\n"


def write_quality_reports(
    world_dir: Path,
    report: Mapping[str, Any],
) -> Tuple[Path, Path]:
    """Write JSON and Markdown reports and return their paths."""
    world_path = Path(world_dir)
    json_path = world_path / "quality_report.json"
    markdown_path = world_path / "quality_report.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def create_quality_reports(
    world_dir: Path,
    config_path: str = "config/ollama_config.yaml",
    config: Optional[Mapping[str, Any]] = None,
) -> Tuple[Dict[str, Any], Path, Path]:
    """Generate and write both quality report formats."""
    report = generate_quality_report(
        world_dir, config_path=config_path, config=config
    )
    json_path, markdown_path = write_quality_reports(world_dir, report)
    return report, json_path, markdown_path


def _summary_text(
    report: Mapping[str, Any], json_path: Path, markdown_path: Path
) -> str:
    checks = report["checks"]
    lines = [f"Quality: {str(report['status']).upper()}"]
    lines.extend(
        f"- {name}: {str(check['status']).upper()}"
        for name, check in checks.items()
    )
    lines.append(f"JSON: {json_path}")
    lines.append(f"Markdown: {markdown_path}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a world package quality report"
    )
    parser.add_argument("world_dir", type=Path)
    parser.add_argument(
        "--json", action="store_true", help="print the full JSON report"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return exit code 1 when the overall status is fail",
    )
    args = parser.parse_args(argv)

    try:
        report, json_path, markdown_path = create_quality_reports(
            args.world_dir
        )
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_summary_text(report, json_path, markdown_path))
    return 1 if args.strict and report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
