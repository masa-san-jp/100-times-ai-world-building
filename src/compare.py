"""Compare generated world packages without calling external services."""

from __future__ import annotations

import argparse
import json
import re
from itertools import combinations
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

from .quality import (
    LIST_SPECS,
    character_ngrams,
    get_quality_config,
    generate_quality_report,
    jaccard,
    normalize_item,
)


UNKNOWN = "不明"
MAX_CELL_CHARACTERS = 120


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _read_yaml(path: Path) -> Optional[Any]:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None


def _short(value: Any, limit: int = MAX_CELL_CHARACTERS) -> str:
    text = " ".join(str(value).split())
    if not text:
        return UNKNOWN
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _scalar_text(value: Any) -> str:
    if isinstance(value, Mapping):
        for nested in value.values():
            text = _scalar_text(nested)
            if text and text != UNKNOWN:
                return text
        return ""
    if isinstance(value, (list, tuple)):
        for nested in value:
            text = _scalar_text(nested)
            if text and text != UNKNOWN:
                return text
        return ""
    return str(value) if value is not None else ""


def _unwrap(data: Any, key: str) -> Any:
    if isinstance(data, Mapping) and key in data:
        return data[key]
    return data


def _manifest_for(world_dir: Path) -> Dict[str, Any]:
    return _read_json(world_dir / "run_manifest.json") or {}


def _intermediate_dir(world_dir: Path, manifest: Mapping[str, Any]) -> Path:
    paths = manifest.get("paths")
    if isinstance(paths, Mapping) and paths.get("intermediate"):
        candidate = world_dir / str(paths["intermediate"])
        if candidate.is_dir():
            return candidate
    return world_dir / "intermediate"


def _artifact_path(
    world_dir: Path,
    manifest: Mapping[str, Any],
    filename: str,
) -> Path:
    return _intermediate_dir(world_dir, manifest) / filename


def _load_artifact(
    world_dir: Path,
    manifest: Mapping[str, Any],
    filename: str,
) -> Optional[Any]:
    return _read_yaml(_artifact_path(world_dir, manifest, filename))


def _metadata(world_dir: Path, manifest: Mapping[str, Any]) -> Dict[str, str]:
    run_id = manifest.get("run_id")
    if run_id is None:
        run_id = re.sub(r"^(?:world|run)_", "", world_dir.name)

    models = manifest.get("models", manifest.get("model"))
    if isinstance(models, Mapping):
        model_values = [
            str(models[key]) for key in sorted(models) if models[key]
        ]
        if len(set(model_values)) == 1:
            model = model_values[0]
        else:
            model = ", ".join(
                f"{key}={models[key]}" for key in sorted(models) if models[key]
            )
    elif models:
        model = str(models)
    else:
        model = UNKNOWN

    seed = manifest.get("run_seed", manifest.get("seed"))
    if seed is None:
        seed = UNKNOWN

    input_hash = None
    for key in ("user_context_sha256", "input_sha256", "input_hash"):
        if manifest.get(key):
            input_hash = manifest[key]
            break
    if input_hash is None:
        for key in ("input", "inputs"):
            candidate = manifest.get(key)
            if isinstance(candidate, Mapping):
                for hash_key in ("sha256", "hash", "user_context_sha256"):
                    if candidate.get(hash_key):
                        input_hash = candidate[hash_key]
                        break
            elif isinstance(candidate, str) and candidate:
                input_hash = candidate
            if input_hash:
                break

    return {
        "run_id": str(run_id) if run_id is not None else UNKNOWN,
        "model": str(model),
        "seed": str(seed),
        "input_hash": str(input_hash) if input_hash else UNKNOWN,
    }


def _plot_type(data: Any) -> str:
    value = _unwrap(data, "selected_plottype")
    if isinstance(value, Mapping):
        for key in ("plot_type", "name", "title"):
            if value.get(key):
                return _short(value[key])
        value = _scalar_text(value)
    return _short(value) if value else UNKNOWN


def _characters(data: Any) -> str:
    characters = _unwrap(data, "characters")
    if not isinstance(characters, list):
        return UNKNOWN

    rendered: List[str] = []
    for character in characters:
        if not isinstance(character, Mapping):
            rendered.append(_short(character, 60))
            continue
        name = character.get("name") or UNKNOWN
        role = (
            character.get("assigned_role")
            or character.get("role")
            or character.get("type")
            or UNKNOWN
        )
        rendered.append(f"{name}: {role}")
    return "<br>".join(rendered) if rendered else UNKNOWN


def _structure_summary(data: Any) -> str:
    value = data
    if isinstance(value, Mapping) and len(value) == 1:
        value = next(iter(value.values()))
    if not isinstance(value, Mapping):
        return _short(value)

    parts: List[str] = []
    for key, item in value.items():
        text = _scalar_text(item)
        if text:
            parts.append(f"{key}: {text}")
    return _short(" / ".join(parts)) if parts else UNKNOWN


def _future_headings(data: Any) -> str:
    value = _unwrap(data, "scenarios")
    scenarios: Iterable[Tuple[str, Any]]
    if isinstance(value, Mapping):
        scenarios = value.items()
    elif isinstance(value, list):
        scenarios = (
            (str(index), item) for index, item in enumerate(value, start=1)
        )
    else:
        return UNKNOWN

    headings: List[str] = []
    for fallback, scenario in scenarios:
        if isinstance(scenario, Mapping):
            name = (
                scenario.get("scenario_type")
                or scenario.get("name")
                or fallback
            )
            timeline = scenario.get("timeline") or scenario.get("title")
            heading = f"{name}: {timeline}" if timeline else str(name)
        else:
            heading = f"{fallback}: {_scalar_text(scenario)}"
        headings.append(_short(heading, 80))
    return "<br>".join(headings) if headings else UNKNOWN


def _first_sentence(value: Any) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    match = re.search(r"[。！？!?．.]", text)
    return text[: match.end()] if match else text


def _chapter_title(chapter: Any, number: int) -> str:
    if isinstance(chapter, Mapping):
        title = (
            chapter.get("title")
            or chapter.get("chapter_title")
            or chapter.get("name")
        )
        if title:
            return f"第{number}章: {_short(title, 80)}"
        for key in ("situation", "events", "conclusion"):
            if chapter.get(key):
                return (
                    f"第{number}章: "
                    f"{_short(_first_sentence(chapter[key]), 80)}"
                )
    return f"第{number}章"


def _chapters(
    world_dir: Path,
    manifest: Mapping[str, Any],
) -> str:
    data = _load_artifact(world_dir, manifest, "20_plot.yaml")
    value = _unwrap(data, "plot")
    chapters = value.get("chapters") if isinstance(value, Mapping) else None
    chapter_values: List[Any] = chapters if isinstance(chapters, list) else []

    if not chapter_values:
        for number in range(1, 11):
            chapter_data = _load_artifact(
                world_dir, manifest, f"{20 + number:02d}_plot_{number}.yaml"
            )
            if chapter_data is None:
                continue
            if isinstance(chapter_data, Mapping):
                chapter_data = chapter_data.get(
                    f"chapter_{number}", chapter_data.get("plot", chapter_data)
                )
            chapter_values.append(chapter_data)

    titles = []
    for index, chapter in enumerate(chapter_values, start=1):
        number = index
        if isinstance(chapter, Mapping):
            try:
                number = int(chapter.get("chapter", index))
            except (TypeError, ValueError):
                number = index
        titles.append(_chapter_title(chapter, number))
    return "<br>".join(titles) if titles else UNKNOWN


def _list_items(
    world_dir: Path,
    manifest: Mapping[str, Any],
) -> Dict[str, List[Any]]:
    values: Dict[str, List[Any]] = {}
    for filename, key in LIST_SPECS[:3]:
        data = _load_artifact(world_dir, manifest, f"{filename}.yaml")
        items = data.get(key) if isinstance(data, Mapping) else None
        values[key] = items if isinstance(items, list) else []
    return values


def _prepare_lists(
    lists: Mapping[str, Sequence[Any]],
) -> Dict[str, Dict[str, Any]]:
    """Normalize list items and calculate their 3-gram sets once."""
    prepared: Dict[str, Dict[str, Any]] = {}
    for name, items in lists.items():
        normalized = [normalize_item(item) for item in items]
        prepared[name] = {
            "normalized": normalized,
            "normalized_set": set(normalized),
            "ngrams": [character_ngrams(item) for item in normalized],
        }
    return prepared


def _approximate_rate(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    threshold: float,
) -> float:
    """Return the symmetric share of items with a thresholded near match."""
    left_normalized = left["normalized"]
    right_normalized = right["normalized"]
    left_ngrams = left["ngrams"]
    right_ngrams = right["ngrams"]

    def directional(
        source_normalized: Sequence[str],
        source_ngrams: Sequence[Set[str]],
        target_normalized: Sequence[str],
        target_ngrams: Sequence[Set[str]],
        target_exact: Set[str],
    ) -> float:
        if not source_normalized or not target_normalized:
            return 0.0
        matched = 0
        for normalized, ngrams in zip(source_normalized, source_ngrams):
            if normalized in target_exact or any(
                jaccard(ngrams, candidate) >= threshold
                for candidate in target_ngrams
            ):
                matched += 1
        return matched / len(source_normalized)

    left_rate = directional(
        left_normalized,
        left_ngrams,
        right_normalized,
        right_ngrams,
        right["normalized_set"],
    )
    right_rate = directional(
        right_normalized,
        right_ngrams,
        left_normalized,
        left_ngrams,
        left["normalized_set"],
    )
    return (left_rate + right_rate) / 2


def _list_overlap(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    threshold: float,
) -> Dict[str, Any]:
    left_normalized = left["normalized"]
    right_normalized = right["normalized"]
    left_set = left.get("normalized_set")
    if left_set is None:
        left_set = set(left_normalized)
    right_set = right.get("normalized_set")
    if right_set is None:
        right_set = set(right_normalized)
    denominator = max(len(left_set), len(right_set))
    exact_count = len(left_set & right_set)
    exact_rate = exact_count / denominator if denominator else 0.0
    return {
        "exact_count": exact_count,
        "exact_rate": exact_rate,
        "approximate_rate": _approximate_rate(left, right, threshold),
        "left_count": len(left_normalized),
        "right_count": len(right_normalized),
    }


def _divergence(
    worlds: Sequence[Mapping[str, Any]],
    prepared_lists: Sequence[Mapping[str, Mapping[str, Any]]],
    threshold: float,
) -> Dict[str, Any]:
    labels = [str(world["label"]) for world in worlds]
    list_names = [key for _, key in LIST_SPECS[:3]]
    count = len(worlds)
    exact_matrix = [[0.0 for _ in range(count)] for _ in range(count)]
    approximate_matrix = [
        [0.0 for _ in range(count)] for _ in range(count)
    ]
    for index in range(count):
        exact_matrix[index][index] = 1.0
        approximate_matrix[index][index] = 1.0

    pairs: List[Dict[str, Any]] = []
    for left_index, right_index in combinations(range(count), 2):
        left_lists = prepared_lists[left_index]
        right_lists = prepared_lists[right_index]
        categories: Dict[str, Any] = {}
        exact_rates: List[float] = []
        approximate_rates: List[float] = []
        for name in list_names:
            result = _list_overlap(
                left_lists.get(
                    name,
                    {"normalized": [], "normalized_set": set(), "ngrams": []},
                ),
                right_lists.get(
                    name,
                    {"normalized": [], "normalized_set": set(), "ngrams": []},
                ),
                threshold,
            )
            categories[name] = result
            exact_rates.append(result["exact_rate"])
            approximate_rates.append(result["approximate_rate"])
        exact_rate = sum(exact_rates) / len(exact_rates)
        approximate_rate = sum(approximate_rates) / len(approximate_rates)
        exact_matrix[left_index][right_index] = exact_rate
        exact_matrix[right_index][left_index] = exact_rate
        approximate_matrix[left_index][right_index] = approximate_rate
        approximate_matrix[right_index][left_index] = approximate_rate
        pairs.append(
            {
                "left": labels[left_index],
                "right": labels[right_index],
                "exact_rate": exact_rate,
                "approximate_rate": approximate_rate,
                "categories": categories,
            }
        )

    pair_count = len(pairs)
    average_exact = (
        sum(pair["exact_rate"] for pair in pairs) / pair_count
        if pair_count
        else None
    )
    average_approximate = (
        sum(pair["approximate_rate"] for pair in pairs) / pair_count
        if pair_count
        else None
    )
    return {
        "worlds": labels,
        "normalized_exact_matrix": exact_matrix,
        "approximate_matrix": approximate_matrix,
        "near_duplicate_threshold": threshold,
        "pairs": pairs,
        "average_exact_overlap_rate": average_exact,
        "average_approximate_overlap_rate": average_approximate,
    }


def _quality_summary(
    world_dir: Path,
    config_path: str,
    config: Optional[Mapping[str, Any]],
) -> str:
    report: Optional[Mapping[str, Any]] = None
    existing = _read_json(world_dir / "quality_report.json")
    if existing is not None:
        report = existing
    else:
        try:
            report = generate_quality_report(
                world_dir, config_path=config_path, config=config
            )
        except Exception:
            return "—"

    if not isinstance(report, Mapping):
        return "—"
    status = report.get("overall_status", report.get("status"))
    if not status:
        return "—"

    parts = [f"判定: {str(status).upper()}"]
    checks = report.get("checks")
    if not isinstance(checks, Mapping):
        return "; ".join(parts)

    duplicates = checks.get("duplicates")
    if isinstance(duplicates, Mapping):
        metrics = []
        lists = duplicates.get("lists")
        if isinstance(lists, Mapping):
            for name, result in lists.items():
                if not isinstance(result, Mapping):
                    continue
                count = result.get("item_count", result.get("items", 0))
                normalized = result.get("normalized_duplicate_count", 0)
                near = result.get("near_duplicate_pair_count", 0)
                metrics.append(f"{name}: {count}件/重複{normalized}/近似{near}")
        if metrics:
            parts.append("重複: " + ", ".join(metrics))

    character_consistency = checks.get("character_consistency")
    if isinstance(character_consistency, Mapping):
        unseen_in_plot = character_consistency.get("unseen_in_plot", [])
        unseen_in_novel = character_consistency.get("unseen_in_novel", [])
        plot_count = (
            len(unseen_in_plot)
            if isinstance(unseen_in_plot, list)
            else UNKNOWN
        )
        novel_count = (
            len(unseen_in_novel)
            if isinstance(unseen_in_novel, list)
            else UNKNOWN
        )
        parts.append(
            "一貫性: "
            f"{str(character_consistency.get('status', UNKNOWN)).upper()}"
            f"（プロット未登場{plot_count}/本文未登場{novel_count}）"
        )

    novel = checks.get("novel_text")
    if isinstance(novel, Mapping) and isinstance(
        novel.get("summary"), Mapping
    ):
        summary = novel["summary"]
        parts.append(
            "本文: "
            f"{summary.get('chapter_count', UNKNOWN)}章/"
            f"最短{summary.get('min_character_count', UNKNOWN)}/"
            f"平均{summary.get('average_character_count', UNKNOWN)}"
        )

    structure = checks.get("chapter_structure")
    if isinstance(structure, Mapping):
        parts.append(
            "構造: "
            f"plot {structure.get('plot_chapter_count', UNKNOWN)}/"
            f"{structure.get('expected_chapter_count', UNKNOWN)}, "
            f"novel {structure.get('novel_chapter_count', UNKNOWN)}/"
            f"{structure.get('expected_chapter_count', UNKNOWN)}"
        )
    return "; ".join(parts)


def generate_comparison_report(
    world_dirs: Sequence[Path],
    config_path: str = "config/ollama_config.yaml",
    config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a report in memory without writing to world packages."""
    paths = [Path(path) for path in world_dirs]
    if not paths:
        raise ValueError("at least one world directory is required")
    for path in paths:
        if not path.is_dir():
            raise ValueError(f"World directory does not exist: {path}")

    quality_settings = get_quality_config(
        config_path=config_path, config=config
    )
    threshold = quality_settings["near_duplicate_threshold"]
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(
            "quality.near_duplicate_threshold must be between 0 and 1"
        )

    labels: Dict[str, int] = {}
    worlds: List[Dict[str, Any]] = []
    prepared_lists: List[Dict[str, Dict[str, Any]]] = []
    for path in paths:
        base_label = path.name or str(path)
        labels[base_label] = labels.get(base_label, 0) + 1
        label = base_label
        if labels[base_label] > 1:
            label = f"{base_label} ({labels[base_label]})"
        manifest = _manifest_for(path)
        raw_lists = _list_items(path, manifest)
        prepared_lists.append(_prepare_lists(raw_lists))
        worlds.append(
            {
                "label": label,
                "path": str(path),
                "metadata": _metadata(path, manifest),
                "plot_type": _plot_type(
                    _load_artifact(path, manifest, "05_plottype.yaml")
                ),
                "characters": _characters(
                    _load_artifact(path, manifest, "06_characters_list.yaml")
                ),
                "social_structure": _structure_summary(
                    _load_artifact(path, manifest, "15_social_structure.yaml")
                ),
                "living_environment": _structure_summary(
                    _load_artifact(
                        path, manifest, "16_living_environment.yaml"
                    )
                ),
                "future_scenarios": _future_headings(
                    _load_artifact(path, manifest, "19_future_scenarios.yaml")
                ),
                "chapters": _chapters(path, manifest),
                "quality": _quality_summary(path, config_path, config),
                "lists": raw_lists,
            }
        )

    divergence = _divergence(worlds, prepared_lists, threshold)
    return {
        "schema_version": 1,
        "worlds": worlds,
        "divergence": divergence,
    }


def _md_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _rate(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:.1%}"


def _matrix_markdown(
    title: str,
    labels: Sequence[str],
    matrix: Sequence[Sequence[float]],
) -> List[str]:
    lines = [f"### {title}", "", "| 世界 | " + " | ".join(labels) + " |"]
    lines.append("| " + " | ".join(["---"] * (len(labels) + 1)) + " |")
    for label, row in zip(labels, matrix):
        lines.append(
            "| " + " | ".join([label] + [_rate(value) for value in row]) + " |"
        )
    return lines


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render a comparison report as a side-by-side Markdown table."""
    worlds = report.get("worlds", [])
    labels = [str(world.get("label", UNKNOWN)) for world in worlds]
    rows: List[Tuple[str, List[str]]] = []
    for key, title in (
        ("plot_type", "選ばれたプロットタイプ"),
        ("characters", "主要キャラクター（名前・役割）"),
        ("social_structure", "社会構造の要約"),
        ("living_environment", "生活環境の要約"),
        ("future_scenarios", "未来シナリオの見出し"),
        ("chapters", "章タイトル一覧"),
        ("quality", "品質サマリ"),
    ):
        rows.append(
            (title, [_md_cell(world.get(key, UNKNOWN)) for world in worlds])
        )

    condition_cells = []
    for world in worlds:
        metadata = world.get("metadata", {})
        condition_cells.append(
            "<br>".join(
                [
                    f"run_id={metadata.get('run_id', UNKNOWN)}",
                    f"model={metadata.get('model', UNKNOWN)}",
                    f"seed={metadata.get('seed', UNKNOWN)}",
                    f"input_hash={metadata.get('input_hash', UNKNOWN)}",
                ]
            )
        )
    rows.insert(0, ("実行条件", condition_cells))

    lines = ["# World Comparison", "", "## 世界ごとの比較", ""]
    lines.append("| 項目 | " + " | ".join(labels) + " |")
    lines.append("| " + " | ".join(["---"] * (len(labels) + 1)) + " |")
    for title, cells in rows:
        lines.append("| " + " | ".join([title] + cells) + " |")

    divergence = report.get("divergence", {})
    lines.extend(["", "## 分岐度", ""])
    average_exact = divergence.get("average_exact_overlap_rate")
    average_approximate = divergence.get(
        "average_approximate_overlap_rate"
    )
    threshold = divergence.get("near_duplicate_threshold", 0.8)
    if average_exact is None:
        summary = "比較対象となる世界ペアはありません（1世界のみ）。"
    else:
        summary = (
            "同じ入力から生成された世界の平均重なり率は、"
            f"正規化完全一致 {_rate(average_exact)}、"
            f"3-gram近似一致率（Jaccard ≥ {threshold:.2f} の項目割合）"
            f" {_rate(average_approximate)} です。"
            "値が低いほど分岐が大きいことを示します。"
        )
    lines.extend([summary, ""])
    lines.extend(
        _matrix_markdown(
            "正規化後の完全一致率",
            [str(value) for value in divergence.get("worlds", labels)],
            divergence.get("normalized_exact_matrix", []),
        )
    )
    lines.extend([""])
    lines.extend(
        _matrix_markdown(
            f"3-gram Jaccard 近似一致率（Jaccard ≥ {threshold:.2f}）",
            [str(value) for value in divergence.get("worlds", labels)],
            divergence.get("approximate_matrix", []),
        )
    )

    pairs = divergence.get("pairs", [])
    if pairs:
        lines.extend(
            [
                "",
                "### 世界ペア別の内訳",
                "",
                "| 世界A | 世界B | 完全一致率 | 3-gram近似一致率 | 願望 | 能力 | 役割 |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for pair in pairs:
            categories = pair.get("categories", {})
            category_rates = [
                _rate(categories.get(name, {}).get("exact_rate"))
                + " / "
                + _rate(categories.get(name, {}).get("approximate_rate"))
                for name in ("desires", "abilities", "roles")
            ]
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(pair.get("left", UNKNOWN)),
                        str(pair.get("right", UNKNOWN)),
                        _rate(pair.get("exact_rate")),
                        _rate(pair.get("approximate_rate")),
                        *category_rates,
                    ]
                )
                + " |"
            )
    return "\n".join(lines) + "\n"


def create_comparison_report(
    world_dirs: Sequence[Path],
    output_path: Path,
    config_path: str = "config/ollama_config.yaml",
    config: Optional[Mapping[str, Any]] = None,
) -> Tuple[Dict[str, Any], Path]:
    """Generate and write a comparison Markdown report."""
    report = generate_comparison_report(
        world_dirs, config_path=config_path, config=config
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report), encoding="utf-8")
    return report, path


def resolve_batch_worlds(batch_dir: Path) -> List[Path]:
    """Resolve completed world packages listed by a batch manifest."""
    batch_path = Path(batch_dir)
    manifest_path = batch_path / "batch_manifest.json"
    manifest = _read_json(manifest_path)
    if manifest is None:
        raise ValueError(f"Invalid or missing batch manifest: {manifest_path}")

    def resolve_manifest_path(value: Any) -> Path:
        path = Path(str(value))
        if path.is_absolute() or path.is_dir():
            return path
        return batch_path / path

    worlds_dir = resolve_manifest_path(manifest.get("worlds_dir", "worlds"))

    resolved: List[Path] = []
    seen: Set[Path] = set()
    records = manifest.get("runs")
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, Mapping):
                continue
            if record.get("status") not in (None, "completed"):
                continue
            candidate: Optional[Path] = None
            output_dir = record.get("output_dir")
            if output_dir:
                candidate = resolve_manifest_path(output_dir)
            if candidate is None or not candidate.is_dir():
                run_id = record.get("run_id")
                if run_id:
                    for name in (
                        f"world_{run_id}",
                        f"run_{run_id}",
                        str(run_id),
                    ):
                        fallback = worlds_dir / name
                        if fallback.is_dir():
                            candidate = fallback
                            break
            if candidate is not None and candidate.is_dir():
                candidate = candidate.resolve()
                if candidate not in seen:
                    resolved.append(candidate)
                    seen.add(candidate)

    if not resolved and worlds_dir.is_dir():
        resolved = sorted(
            (
                path.resolve()
                for path in worlds_dir.iterdir()
                if path.is_dir() and (path / "run_manifest.json").is_file()
            ),
            key=str,
        )
    return resolved


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a side-by-side comparison of world packages"
    )
    parser.add_argument("world_dirs", nargs="*", type=Path)
    parser.add_argument("--batch", type=Path, help="batch directory")
    parser.add_argument("--out", type=Path, help="output Markdown path")
    args = parser.parse_args(argv)

    if args.batch and args.world_dirs:
        parser.error("world directories and --batch cannot be used together")
    try:
        if args.batch:
            world_dirs = resolve_batch_worlds(args.batch)
            if not world_dirs:
                raise ValueError(
                    f"No completed worlds found in batch: {args.batch}"
                )
            output_path = args.out or (args.batch / "comparison.md")
        else:
            world_dirs = args.world_dirs
            if not world_dirs:
                parser.error("at least one world directory is required")
            output_path = args.out

        if output_path:
            create_comparison_report(world_dirs, output_path)
        else:
            report = generate_comparison_report(world_dirs)
            markdown = render_markdown(report)
            print(markdown, end="")
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
