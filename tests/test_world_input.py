"""Tests for format-free input acceptance."""

import json
from pathlib import Path

import yaml

from src.llm import FakeLLMBackend
from src.world import InputBriefBuilder


def test_input_brief_keeps_only_statements_with_verifiable_quotes(tmp_path):
    raw = "焦点は水路の維持。判断は共同で行う。"
    backend = FakeLLMBackend(
        json_responses={
            "statements": [
                {"text": "水路の維持が焦点", "quote": "焦点は水路の維持"},
                {"text": "未提示の事項", "quote": "原文にない引用"},
            ],
            "open_questions": ["誰が判断を担うか"],
            "constraints": ["判断は共同で行う"],
        }
    )

    result = InputBriefBuilder(backend, tmp_path).build(raw)

    assert result.raw_path.read_text(encoding="utf-8") == raw
    assert result.brief == {
        "statements": [
            {
                "id": "s1",
                "text": "水路の維持が焦点",
                "quote": "焦点は水路の維持",
            }
        ],
        "open_questions": [{"id": "q1", "text": "誰が判断を担うか"}],
        "constraints": [{"id": "c1", "text": "判断は共同で行う"}],
    }
    assert (
        json.loads(result.brief_path.read_text(encoding="utf-8"))
        == result.brief
    )


def test_input_brief_is_deterministic_and_has_no_required_story_fields(
    tmp_path,
):
    raw = "記録は公開する。"
    response = {
        "statements": [{"text": "記録を公開する", "quote": "記録は公開する"}],
        "open_questions": [],
        "constraints": [],
    }

    first = InputBriefBuilder(
        FakeLLMBackend(json_responses=response), tmp_path / "one"
    ).build(raw)
    second = InputBriefBuilder(
        FakeLLMBackend(json_responses=response), tmp_path / "two"
    ).build(raw)

    assert first.to_dict() == second.to_dict()
    assert set(first.brief) == {"statements", "open_questions", "constraints"}
    assert "protagonist" not in first.brief
    assert "plot" not in first.brief


def test_image_original_is_saved_and_vision_description_is_source_material(
    tmp_path,
):
    raw = "画像も判断材料にする。"
    image = tmp_path / "source.bin"
    image.write_bytes(b"image bytes")
    backend = FakeLLMBackend(
        json_responses=[
            {"description": "明るい面と細い線が見える"},
            {
                "statements": [
                    {
                        "text": "画像には明るい面と細い線が見える",
                        "quote": "明るい面と細い線が見える",
                    }
                ],
                "open_questions": [],
                "constraints": [],
            },
        ]
    )

    result = InputBriefBuilder(
        backend, tmp_path / "package"
    ).build(raw, images=[image])

    saved_image = tmp_path / "package" / "images" / "source.bin"
    assert saved_image.read_bytes() == image.read_bytes()
    assert "明るい面と細い線が見える" in result.source_for_brief
    assert result.brief["statements"][0]["quote"] in result.source_for_brief
    assert (tmp_path / "package" / "source_for_brief.txt").is_file()


def test_ids_are_assigned_after_schema_repair_and_quote_filtering(tmp_path):
    raw = "甲は乙。丙は丁。戊は己。"
    invalid = {"statements": [{"id": "x9", "text": "a", "quote": "甲は乙"}],
               "open_questions": [{"id": "zz", "text": "q two"}], "constraints": []}
    valid = {"statements": [{"text": "a", "quote": "甲は乙"},
                            {"text": "dropped", "quote": "存在しない"},
                            {"text": "b", "quote": "戊は己"}],
             "open_questions": ["q one", "q two", ""], "constraints": ["c one"]}
    backend = FakeLLMBackend([invalid, valid])
    brief = InputBriefBuilder(backend, tmp_path).build(raw).brief
    assert [s["id"] for s in brief["statements"]] == ["s1", "s2"]
    assert [q["id"] for q in brief["open_questions"]] == ["q1", "q2"]
    assert brief["open_questions"][1]["text"] == "q two"
    assert brief["constraints"] == [{"id": "c1", "text": "c one"}]
    assert len(backend.json_prompts) == 2 and "Additional properties" in backend.json_prompts[1]


def test_blank_or_whitespace_quotes_are_rejected(tmp_path):
    raw = "前 後"
    backend = FakeLLMBackend(
        json_responses={
            "statements": [
                {"text": "blank", "quote": " "},
                {"text": "empty", "quote": ""},
                {"text": "newline", "quote": "\n"},
            ],
            "open_questions": [],
            "constraints": [],
        }
    )

    brief = InputBriefBuilder(backend, tmp_path).build(raw + "\n").brief

    assert brief["statements"] == []


BANNED_TERMS = [
    "protagonist", "主人公", "plot", "プロット", "chapter", "章",
    "novel", "小説", "story", "物語", "dialogue", "台詞", "character arc",
    "future", "未来", "past", "過去", "fantasy", "ファンタジー",
    "sci-fi", "science fiction", "SF", "medieval", "中世", "magic", "魔法",
    "kingdom", "王国", "city", "都市", "robot", "ロボット", "cyberpunk",
]


def _input_prompt_texts():
    config = Path(__file__).resolve().parent.parent / "config" / "prompts"
    data = yaml.safe_load((config / "input_brief.yaml").read_text("utf-8"))
    texts = []
    for section in ("input_brief", "image_description"):
        texts.extend(data[section].values())
    for name in (
        "DEFAULT_SYSTEM_PROMPT", "DEFAULT_USER_PROMPT",
        "DEFAULT_VISION_SYSTEM_PROMPT", "DEFAULT_VISION_USER_PROMPT",
    ):
        texts.append(getattr(InputBriefBuilder, name))
    return texts


def test_input_prompts_have_no_story_or_genre_terms():
    for text in _input_prompt_texts():
        lowered = text.lower()
        for term in BANNED_TERMS:
            assert term.lower() not in lowered, term


def test_default_prompts_match_yaml_config():
    config = Path(__file__).resolve().parent.parent / "config" / "prompts"
    data = yaml.safe_load((config / "input_brief.yaml").read_text("utf-8"))
    norm = lambda t: " ".join(t.split())  # noqa: E731
    pairs = [
        (data["input_brief"]["system"], InputBriefBuilder.DEFAULT_SYSTEM_PROMPT),
        (data["input_brief"]["user"], InputBriefBuilder.DEFAULT_USER_PROMPT),
        (
            data["image_description"]["system"],
            InputBriefBuilder.DEFAULT_VISION_SYSTEM_PROMPT,
        ),
        (
            data["image_description"]["user"],
            InputBriefBuilder.DEFAULT_VISION_USER_PROMPT,
        ),
    ]
    for yaml_text, default in pairs:
        assert norm(yaml_text) == norm(default)
