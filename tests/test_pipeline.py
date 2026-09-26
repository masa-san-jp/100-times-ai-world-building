"""Tests for Pipeline module."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.pipeline import Pipeline


class TestPipeline:
    @pytest.fixture
    def mock_config(self, tmp_path):
        return {
            "server": {
                "host": "http://localhost",
                "port": 11434,
                "timeout": 300,
                "max_retries": 3,
                "retry_delay": 5,
            },
            "model": {"name": "gpt-oss:20b"},
            "checkpointing": {
                "output_dir": "./output/checkpoints",
                "auto_save": True,
                "compression": False,
            },
            "output": {"base_dir": str(tmp_path)},
            "phases": {
                "phase1_expansion": {
                    "temperature": 0.8,
                    "num_predict": 4096,
                    "plottype_items_per_request": 10,
                }
            },
        }

    @pytest.fixture
    def mock_prompts(self):
        return {
            "desire_list": {
                "system": "System prompt",
                "user": "Generate desires from: {user_context}",
            }
        }

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_initialization(self, mock_load_prompts, mock_load_config, mock_config, mock_prompts):
        mock_load_config.return_value = mock_config
        mock_load_prompts.return_value = mock_prompts

        pipeline = Pipeline()

        assert pipeline.config == mock_config
        assert pipeline.prompts == mock_prompts
        assert pipeline.client is not None
        assert pipeline.checkpoint_manager is not None

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_default_model_is_gpt_oss_20b(self, mock_load_prompts, mock_load_config, mock_config, mock_prompts):
        mock_load_config.return_value = mock_config
        mock_load_prompts.return_value = mock_prompts

        assert Pipeline().client.model == "gpt-oss:20b"

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_anthropic_requires_a_model_setting_or_override(
        self, mock_load_prompts, mock_load_config, mock_config, mock_prompts
    ):
        mock_config["backend"] = "anthropic"
        mock_config["anthropic"] = {"request_options": {"max_tokens": 1}}
        mock_load_config.return_value = mock_config
        mock_load_prompts.return_value = mock_prompts

        with pytest.raises(ValueError, match="requires a model"):
            Pipeline(run_id="missing_anthropic_model")

    @patch("src.pipeline.build_backend_clients")
    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_anthropic_model_and_request_options_are_recorded(
        self,
        mock_load_prompts,
        mock_load_config,
        mock_build_clients,
        mock_config,
        mock_prompts,
        tmp_path,
    ):
        mock_config["backend"] = "anthropic"
        mock_config["anthropic"] = {
            "model": "configured-model",
            "request_options": {"max_tokens": 64000},
        }
        mock_config["output"]["base_dir"] = str(tmp_path)
        mock_load_config.return_value = mock_config
        mock_load_prompts.return_value = mock_prompts
        fake_client = Mock(model="configured-model")
        mock_build_clients.return_value = {
            role: fake_client
            for role in ("structured", "story", "reference", "vision")
        }

        pipeline = Pipeline(run_id="anthropic_manifest")

        assert pipeline.model_names["structured"] == "configured-model"
        assert pipeline.manifest.data["backend"] == "anthropic"
        assert pipeline.manifest.data["model"] == "configured-model"
        assert mock_build_clients.call_args.args[3]["request_options"] == {
            "max_tokens": 64000
        }

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_model_override(self, mock_load_prompts, mock_load_config, mock_config, mock_prompts):
        mock_load_config.return_value = mock_config
        mock_load_prompts.return_value = mock_prompts

        for model_name in ("gpt-oss:20b-q8", "gpt-oss:20b-q4", "gpt-oss:120b"):
            assert Pipeline(model=model_name).client.model == model_name

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_role_specific_models(self, mock_load_prompts, mock_load_config, mock_config, mock_prompts):
        mock_load_config.return_value = mock_config
        mock_load_prompts.return_value = mock_prompts

        pipeline = Pipeline(
            structured_model="local-json",
            story_model="local-story",
            reference_model="local-reference",
            vision_model="local-vision",
        )

        assert pipeline.clients["structured"].model == "local-json"
        assert pipeline.clients["story"].model == "local-story"
        assert pipeline.clients["reference"].model == "local-reference"
        assert pipeline.clients["vision"].model == "local-vision"

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_per_run_output_directory(
        self, mock_load_prompts, mock_load_config, mock_config, mock_prompts, tmp_path
    ):
        mock_load_config.return_value = mock_config
        mock_load_prompts.return_value = mock_prompts

        p1 = Pipeline(run_id="20260101_000000")
        p2 = Pipeline(run_id="20260101_000001")

        assert p1.base_dir == str(tmp_path / "world_20260101_000000")
        assert p2.base_dir == str(tmp_path / "world_20260101_000001")
        assert p1.base_dir != p2.base_dir

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_output_dir_override(self, mock_load_prompts, mock_load_config, mock_config, mock_prompts, tmp_path):
        mock_load_config.return_value = mock_config
        mock_load_prompts.return_value = mock_prompts

        pipeline = Pipeline(run_id="curated", output_dir=tmp_path / "examples" )

        assert pipeline.base_dir_path == tmp_path / "examples" / "world_curated"
        assert pipeline.checkpoint_manager.checkpoint_dir == (
            tmp_path / "examples" / "world_curated" / "checkpoints"
        )

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_world_package_contains_input_intermediate_and_final_dirs(
        self, mock_load_prompts, mock_load_config, mock_config, mock_prompts, tmp_path
    ):
        mock_load_config.return_value = mock_config
        mock_load_prompts.return_value = mock_prompts

        pipeline = Pipeline(run_id="organized", output_dir=tmp_path)

        assert pipeline.base_dir_path == tmp_path / "world_organized"
        assert (pipeline.base_dir_path / "input").is_dir()
        assert (pipeline.base_dir_path / "intermediate").is_dir()
        assert (pipeline.base_dir_path / "final" / "novels").is_dir()
        assert (pipeline.base_dir_path / "final" / "references").is_dir()
        assert (pipeline.base_dir_path / "checkpoints").is_dir()

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_legacy_run_package_remains_resumable(
        self, mock_load_prompts, mock_load_config, mock_config, mock_prompts, tmp_path
    ):
        mock_load_config.return_value = mock_config
        mock_load_prompts.return_value = mock_prompts
        (tmp_path / "run_legacy").mkdir()

        pipeline = Pipeline(run_id="legacy", output_dir=tmp_path)

        assert pipeline.legacy_layout is True
        assert pipeline.base_dir_path == tmp_path / "run_legacy"
        assert pipeline.novels_dir == tmp_path / "run_legacy" / "novels"

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_run_id_is_set(self, mock_load_prompts, mock_load_config, mock_config, mock_prompts):
        mock_load_config.return_value = mock_config
        mock_load_prompts.return_value = mock_prompts

        assert Pipeline(run_id="test_run_42").run_id == "test_run_42"

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_run_seed_is_persisted_and_reused_on_resume(
        self, mock_load_prompts, mock_load_config, mock_config, mock_prompts, tmp_path
    ):
        mock_config["output"]["base_dir"] = str(tmp_path)
        mock_load_config.return_value = mock_config
        mock_load_prompts.return_value = mock_prompts

        first = Pipeline(run_id="seed_policy", seed=12345)
        resumed = Pipeline(run_id="seed_policy")

        assert first.run_seed == 12345
        assert resumed.run_seed == 12345
        manifest = Path(first.base_dir) / "run_manifest.json"
        assert '"run_seed": 12345' in manifest.read_text(encoding="utf-8")

        with pytest.raises(ValueError, match="does not match existing run seed"):
            Pipeline(run_id="seed_policy", seed=99999)

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_generation_options_merge_config_and_derive_seed(
        self, mock_load_prompts, mock_load_config, mock_config, mock_prompts, tmp_path
    ):
        mock_config["output"]["base_dir"] = str(tmp_path)
        mock_config["model"]["generation"] = {
            "temperature": 0.7,
            "top_p": 0.9,
            "top_k": 40,
            "repeat_penalty": 1.1,
            "num_predict": 4096,
        }
        mock_config["phases"]["phase1_expansion"] = {
            "temperature": 0.4,
            "top_p": 0.6,
            "num_predict": 1234,
            "think": False,
        }
        mock_load_config.return_value = mock_config
        mock_load_prompts.return_value = mock_prompts

        pipeline = Pipeline(run_id="options_test", seed=7)
        options = pipeline._generation_options(
            mock_config["phases"]["phase1_expansion"], "phase1_desire_list"
        )

        assert options["temperature"] == 0.4
        assert options["top_p"] == 0.6
        assert options["top_k"] == 40
        assert options["repeat_penalty"] == 1.1
        assert options["num_predict"] == 1234
        assert options["think"] is False
        assert options["seed"] == pipeline._derive_seed("phase1_desire_list")
        assert pipeline.manifest.data["requests"]["phase1_desire_list"] == options

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_resume_validation_parses_yaml_checkpoint_values(
        self, mock_load_prompts, mock_load_config, mock_config, mock_prompts, tmp_path
    ):
        mock_config["output"]["base_dir"] = str(tmp_path)
        mock_load_config.return_value = mock_config
        mock_load_prompts.return_value = mock_prompts

        pipeline = Pipeline(run_id="yaml_resume", seed=11)
        yaml_value = "desires:\n" + "".join(
            f"  - desire-{index}\n" for index in range(100)
        )

        assert pipeline._resume_json_is_valid("desire_list", yaml_value)

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_checkpoint_dir_uses_run_id(
        self, mock_load_prompts, mock_load_config, mock_config, mock_prompts, tmp_path
    ):
        mock_load_config.return_value = mock_config
        mock_load_prompts.return_value = mock_prompts

        pipeline = Pipeline(run_id="abc")

        assert pipeline.checkpoint_manager.checkpoint_dir == tmp_path / "world_abc" / "checkpoints"

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    @patch.object(Pipeline, "check_prerequisites")
    def test_check_prerequisites_success(
        self, mock_check_prereq, mock_load_prompts, mock_load_config, mock_config, mock_prompts
    ):
        mock_load_config.return_value = mock_config
        mock_load_prompts.return_value = mock_prompts
        mock_check_prereq.return_value = True

        assert Pipeline().check_prerequisites() is True

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_run_phase1_expansion(self, mock_load_prompts, mock_load_config, mock_config, mock_prompts):
        mock_load_config.return_value = mock_config
        mock_prompts.update({
            "ability_list": {"system": "System prompt", "user": "Generate abilities from: {user_context}"},
            "role_list": {"system": "System prompt", "user": "Generate roles from: {user_context}"},
            "plottype_list": {"system": "System prompt", "user": "Generate plot types"},
            "plottype_selection": {"system": "System prompt", "user": "Select from: {plottype_list}"},
        })
        mock_load_prompts.return_value = mock_prompts

        pipeline = Pipeline()
        pipeline.client.generate_json = Mock(side_effect=[
            {"desires": [f"desire{i}" for i in range(100)]},
            {"abilities": [f"ability{i}" for i in range(100)]},
            {"roles": [f"role{i}" for i in range(100)]},
            {"plot_types": [{"plot_type": f"plot{i}"} for i in range(10)]},
            {"selected_plottype": {"plot_type": "plot0"}},
        ])

        results = pipeline.run_phase1_expansion("Test context")

        assert "desire_list" in results
        assert pipeline.client.generate_json.called

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_phase1_chunks_large_lists_and_records_absolute_batch_keys(
        self, mock_load_prompts, mock_load_config, mock_config, mock_prompts, tmp_path
    ):
        mock_config["output"]["base_dir"] = str(tmp_path)
        mock_config["phases"]["phase1_expansion"] = {
            "items_per_request": 20,
            "num_predict": 256,
            "plottype_items_per_request": 10,
        }
        mock_load_config.return_value = mock_config
        mock_prompts.update({
            "ability_list": {"system": "System", "user": "abilities {user_context}"},
            "role_list": {"system": "System", "user": "roles {user_context}"},
            "plottype_list": {"system": "System", "user": "plot types"},
            "plottype_selection": {"system": "System", "user": "select {plottype_list}"},
        })
        mock_load_prompts.return_value = mock_prompts

        pipeline = Pipeline(run_id="chunked", seed=17)
        responses = []
        for field, prefix in (("desires", "desire"), ("abilities", "ability"), ("roles", "role")):
            for batch in range(5):
                responses.append({field: [f"{prefix}-{batch}-{index}" for index in range(20)]})
        responses.extend([
            {"plot_types": [{"plot_type": f"plot-{index}"} for index in range(10)]},
            {"selected_plottype": {"plot_type": "plot-0"}},
        ])
        pipeline.client.generate_json = Mock(side_effect=responses)

        result = pipeline.run_phase1_expansion("Test context")

        assert set(result) == {
            "desire_list", "ability_list", "role_list", "plottype_list", "plottype"
        }
        request_keys = pipeline.manifest.data["requests"]
        assert all(
            all(f"phase1_{field}_batch_{batch}" in request_keys for batch in range(1, 6))
            for field in ("desire_list", "ability_list", "role_list")
        )

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_phase1_refills_short_batch_with_new_stable_key(
        self, mock_load_prompts, mock_load_config, mock_config, mock_prompts, tmp_path
    ):
        """A short model response is supplemented instead of accepted as 100 items."""
        mock_config["output"]["base_dir"] = str(tmp_path)
        mock_config["phases"]["phase1_expansion"] = {
            "items_per_request": 20,
            "plottype_items_per_request": 10,
        }
        mock_load_config.return_value = mock_config
        mock_prompts.update({
            "ability_list": {"system": "System", "user": "abilities {user_context}"},
            "role_list": {"system": "System", "user": "roles {user_context}"},
            "plottype_list": {"system": "System", "user": "plot types"},
            "plottype_selection": {"system": "System", "user": "select {plottype_list}"},
        })
        mock_load_prompts.return_value = mock_prompts

        pipeline = Pipeline(run_id="short_batch", seed=18)
        responses = [{"desires": [f"desire-{i}" for i in range(19)]}]
        responses.extend({"desires": [f"desire-{batch}-{i}" for i in range(20)]} for batch in range(4))
        responses.append({"desires": ["desire-final"]})
        responses.extend(
            {field: [f"{field}-{i}" for i in range(20)]}
            for field in ("abilities", "roles")
            for _ in range(5)
        )
        responses.extend([
            {"plot_types": [{"plot_type": f"plot-{i}"} for i in range(10)]},
            {"selected_plottype": {"plot_type": "plot-0"}},
        ])
        pipeline.client.generate_json = Mock(side_effect=responses)

        result = pipeline.run_phase1_expansion("Test context")

        assert set(result) == {
            "desire_list", "ability_list", "role_list", "plottype_list", "plottype"
        }
        assert "phase1_desire_list_batch_6" in pipeline.manifest.data["requests"]

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_phase3_chunks_people_list_and_persists_batches(
        self, mock_load_prompts, mock_load_config, mock_config, mock_prompts, tmp_path
    ):
        mock_config["output"]["base_dir"] = str(tmp_path)
        mock_config["phases"]["phase3_world"] = {
            "people_items_per_request": 2,
            "num_predict": 256,
        }
        mock_load_config.return_value = mock_config
        mock_prompts.update({
            "people_list": {
                "system": "System",
                "user": "people {events} {observation} {interpretation} {media} "
                "{important_past_events} {social_structure} {living_environment} {social_groups}",
            }
        })
        mock_load_prompts.return_value = mock_prompts

        pipeline = Pipeline(run_id="people_chunked")
        pipeline._validate_phase_state = Mock()
        pipeline.client.generate_json = Mock(
            side_effect=[
                {
                    "people": [
                        {
                            "name": f"person-{batch}-{item}",
                            "age": 20 + item,
                            "gender": "不詳",
                            "residence": "東京",
                            "role": "市民",
                        }
                        for item in range(2)
                    ]
                }
                for batch in range(50)
            ]
        )

        result = pipeline.run_phase3_world_building({})

        assert "people_list" in result
        assert len(pipeline.client.generate_json.call_args_list) == 50
        request_keys = pipeline.manifest.data["requests"]
        assert "phase3_people_list_batch_1" in request_keys
        assert "phase3_people_list_batch_50" in request_keys

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_phase0_accepts_supplied_context(self, mock_load_prompts, mock_load_config, mock_config, mock_prompts):
        mock_load_config.return_value = mock_config
        mock_load_prompts.return_value = mock_prompts

        context = "context:\n  theme: local-only\n"
        assert Pipeline(run_id="phase0_test").run_phase0_context_extraction(context) == context

    @patch("src.pipeline.load_config")
    @patch("src.pipeline.load_prompts")
    def test_resume_full_pipeline_reuses_run_context(
        self, mock_load_prompts, mock_load_config, mock_config, mock_prompts
    ):
        mock_load_config.return_value = mock_config
        mock_load_prompts.return_value = mock_prompts

        pipeline = Pipeline(run_id="resume_test")
        pipeline.checkpoint_manager.save_checkpoint(
            "phase0_context", {"user_context": "context: local\n"}
        )
        with (
            patch.object(pipeline, "check_prerequisites", return_value=True),
            patch.object(pipeline, "run_phase1_expansion", return_value={"phase1": "ok"}) as phase1,
            patch.object(pipeline, "run_phase2_characters", return_value="characters") as phase2,
            patch.object(pipeline, "run_phase3_world_building", return_value={"events": "events"}) as phase3,
            patch.object(pipeline, "run_phase4_plot_generation", return_value={"plot": "plot"}) as phase4,
            patch.object(pipeline, "run_phase5_novel_generation", return_value={"story_1": "story"}) as phase5,
            patch.object(pipeline, "run_phase6_reference_generation", return_value={"plot.md": "reference"}) as phase6,
            patch.object(pipeline, "_validate_phase_state"),
        ):
            result = pipeline.resume_full_pipeline()

        assert result["user_context"] == "context: local\n"
        assert result["characters_list"] == "characters"
        assert result["novels"] == {"story_1": "story"}
        phase1.assert_called_once_with("context: local\n")
        phase2.assert_called_once()
        phase3.assert_called_once()
        phase4.assert_called_once()
        phase5.assert_called_once()
        phase6.assert_called_once()
