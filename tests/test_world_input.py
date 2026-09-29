"""Tests for format-free input acceptance."""

import json

from src.llm import FakeLLMBackend
from src.pipeline import Pipeline
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
            {"text": "水路の維持が焦点", "quote": "焦点は水路の維持"}
        ],
        "open_questions": ["誰が判断を担うか"],
        "constraints": ["判断は共同で行う"],
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


def test_pipeline_phase_zero_persists_brief_with_fake_backend(tmp_path):
    raw = '{"label":"unresolved input"}'
    backend = FakeLLMBackend(
        json_responses={
            "statements": [{"text": "入力にラベルがある", "quote": "\"label\""}],
            "open_questions": ["扱い"],
            "constraints": [],
        }
    )

    pipeline = Pipeline(
        backend=backend,
        run_id="input-brief",
        output_dir=tmp_path,
    )
    assert pipeline.run_phase0_context_extraction(raw) == raw

    brief_path = tmp_path / "world_input-brief" / "input" / "input_brief.json"
    assert json.loads(brief_path.read_text(encoding="utf-8"))["statements"]
