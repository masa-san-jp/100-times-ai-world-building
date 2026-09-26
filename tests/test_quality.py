"""Tests for world package quality reports."""

import json
from pathlib import Path

from src.quality import (
    analyze_duplicates,
    character_ngrams,
    create_quality_reports,
    generate_quality_report,
    jaccard,
    normalize_item,
)


def _write_world(
    tmp_path: Path,
    include_all_chapters: bool = True,
    truncated_last: bool = False,
    trailing_separator: bool = False,
) -> Path:
    world_dir = tmp_path / "world_fixture"
    intermediate = world_dir / "intermediate"
    novels = world_dir / "final" / "novels"
    intermediate.mkdir(parents=True)
    novels.mkdir(parents=True)

    (intermediate / "01_desire_list.yaml").write_text(
        "desires:\n  - Same\n  - Same\n  - Hello!\n  - hello\n",
        encoding="utf-8",
    )
    (intermediate / "02_ability_list.yaml").write_text(
        "abilities:\n  - One\n",
        encoding="utf-8",
    )
    (intermediate / "03_role_list.yaml").write_text(
        "roles:\n  - Role\n",
        encoding="utf-8",
    )
    (intermediate / "18_people_list.yaml").write_text(
        "people:\n  - name: Person\n",
        encoding="utf-8",
    )
    (intermediate / "06_characters_list.yaml").write_text(
        "characters:\n"
        "  - type: protagonist\n"
        "    name: Alice\n"
        "    description: Main character\n"
        "  - type: supporter\n"
        "    name: Bob\n"
        "    description: Missing from the novel\n",
        encoding="utf-8",
    )

    chapter_count = 10 if include_all_chapters else 9
    for chapter_number in range(1, chapter_count + 1):
        plot_path = intermediate / (
            f"{20 + chapter_number:02d}_plot_{chapter_number}.yaml"
        )
        plot_path.write_text(
            f"chapter_{chapter_number}:\n"
            "  situation: Situation\n"
            "  events: Events\n"
            "  protagonist_actions: Actions\n"
            "  situation_change: Change\n",
            encoding="utf-8",
        )
        novel = "Alice appears here。" if chapter_number == 1 else "A chapter。"
        if truncated_last and chapter_number == 10:
            novel = "A chapter"
        if trailing_separator and chapter_number == 10:
            novel = "本文は確信したのだった。\n\n***\n"
        (novels / f"chapter_{chapter_number:02d}.txt").write_text(
            novel,
            encoding="utf-8",
        )
    return world_dir


def test_normalization_removes_nfkc_whitespace_punctuation_and_symbols():
    assert normalize_item(" ＡＢ！　") == "ab"


def test_ngram_helpers_are_public():
    grams = character_ngrams("abcd")
    assert grams == {"abc", "bcd"}
    assert jaccard(grams, grams) == 1.0


def test_duplicate_metrics_include_exact_normalized_and_near_duplicates():
    metrics = analyze_duplicates(
        [
            "Same",
            "Same",
            "Hello!",
            " hello ",
            "abcdefghijklmnopqrst",
            "abcdefghijklmnopqrsu",
        ]
    )

    assert metrics["exact_duplicate_count"] == 1
    assert metrics["normalized_duplicate_count"] == 2
    assert metrics["near_duplicate_pair_count"] == 1
    assert metrics["unique_count"] == 4


def test_report_warns_for_unseen_character_and_short_or_truncated_chapters(
    tmp_path,
):
    world_dir = _write_world(tmp_path, truncated_last=True)
    report = generate_quality_report(
        world_dir,
        config={"quality": {"min_chapter_characters": 100}},
    )

    assert report["status"] == "warn"
    character_check = report["checks"]["character_consistency"]
    assert character_check["unseen_in_plot"] == ["Alice", "Bob"]
    assert character_check["unseen_in_novel"] == ["Bob"]
    assert character_check["characters"][0]["novel_chapters"] == [1]

    novel_check = report["checks"]["novel_text"]
    assert novel_check["summary"]["below_minimum_chapters"] == [
        f"{chapter:02d}" for chapter in range(1, 11)
    ]
    assert novel_check["summary"]["truncated_suspected_chapters"] == ["10"]


def test_character_matching_uses_name_parts(tmp_path):
    world_dir = _write_world(tmp_path)
    characters_path = world_dir / "intermediate" / "06_characters_list.yaml"
    characters_path.write_text(
        characters_path.read_text(encoding="utf-8").replace(
            "name: Alice", "name: カエデ・アキラ (19歳)"
        ),
        encoding="utf-8",
    )
    (world_dir / "final" / "novels" / "chapter_03.txt").write_text(
        "カエデは歩き出した。",
        encoding="utf-8",
    )

    report = generate_quality_report(world_dir)

    character = report["checks"]["character_consistency"]["characters"][0]
    assert character["novel_chapters"] == [3]


def test_ending_check_ignores_trailing_separator_lines(tmp_path):
    world_dir = _write_world(tmp_path, trailing_separator=True)
    report = generate_quality_report(world_dir)

    novel_check = report["checks"]["novel_text"]
    assert novel_check["summary"]["truncated_suspected_chapters"] == []
    assert novel_check["chapters"]["10"]["status"] == "warn"


def test_structure_check_fails_when_a_chapter_is_missing(tmp_path):
    world_dir = _write_world(tmp_path, include_all_chapters=False)
    report = generate_quality_report(world_dir)

    structure = report["checks"]["chapter_structure"]
    assert structure["status"] == "fail"
    assert structure["plot_chapter_count"] == 9
    assert structure["novel_chapter_count"] == 9
    assert structure["chapters"]["10"]["status"] == "fail"


def test_reports_are_written_in_both_formats(tmp_path):
    world_dir = _write_world(tmp_path)
    report, json_path, markdown_path = create_quality_reports(world_dir)

    desire_metrics = report["checks"]["duplicates"]["lists"]["01_desire_list"]
    assert desire_metrics["exact_duplicate_count"] == 1
    assert desire_metrics["normalized_duplicate_count"] == 2
    assert json_path == world_dir / "quality_report.json"
    assert markdown_path == world_dir / "quality_report.md"
    assert (
        json.loads(json_path.read_text(encoding="utf-8"))["status"]
        == report["status"]
    )
    assert "# Quality Report" in markdown_path.read_text(encoding="utf-8")
