"""Validation rules for generated pipeline artifacts."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import yaml


class OutputValidationError(ValueError):
    """Raised when a model response violates an artifact contract."""

    def __init__(self, artifact: str, errors: Iterable[str]):
        self.artifact = artifact
        self.errors = list(errors)
        message = "; ".join(self.errors) or "invalid output"
        super().__init__(f"{artifact}: {message}")


def _as_dict(data: Any) -> Optional[Dict[str, Any]]:
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        try:
            parsed = yaml.safe_load(data)
        except yaml.YAMLError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _list_errors(
    container: Dict[str, Any],
    key: str,
    expected: Optional[int] = None,
    maximum: Optional[int] = None,
) -> List[str]:
    value = container.get(key)
    if not isinstance(value, list):
        return [f"{key} must be a list"]
    errors: List[str] = []
    if expected is not None and len(value) != expected:
        errors.append(f"{key} must contain {expected} items (got {len(value)})")
    if maximum is not None and len(value) > maximum:
        errors.append(f"{key} must contain at most {maximum} items (got {len(value)})")
    return errors


def _mapping_errors(container: Dict[str, Any], key: str) -> List[str]:
    if not isinstance(container.get(key), dict):
        return [f"{key} must be an object"]
    return []


def _required_field_errors(value: Dict[str, Any], fields: Iterable[str]) -> List[str]:
    return [field + " is required" for field in fields if not value.get(field)]


def validate_artifact(
    artifact: str,
    data: Any,
    chapter_number: Optional[int] = None,
) -> List[str]:
    """Return contract violations for one generated artifact.

    The rules intentionally validate the structural contract and requested
    cardinality, not prose quality. This keeps the local pipeline strict about
    completeness while allowing different Ollama models to write differently.
    """
    value = _as_dict(data)
    if value is None:
        return ["output must be a mapping"]

    if artifact == "context":
        context = value.get("context", value)
        return [] if isinstance(context, dict) else ["context must be an object"]

    if artifact == "plottype":
        selected = value.get("selected_plottype", value.get("plottype"))
        return [] if isinstance(selected, dict) else ["selected_plottype must be an object"]

    if artifact in {"events", "observation", "interpretation", "media", "social_structure", "living_environment"}:
        return _mapping_errors(value, artifact)

    if artifact in {"desire_list", "ability_list", "role_list"}:
        key = {
            "desire_list": "desires",
            "ability_list": "abilities",
            "role_list": "roles",
        }[artifact]
        return _list_errors(value, key, expected=100)

    if artifact == "plottype_list":
        return _list_errors(value, "plot_types", expected=10)

    if artifact == "characters":
        errors = _list_errors(value, "characters", expected=4)
        characters = value.get("characters")
        if isinstance(characters, list):
            types = {item.get("type") for item in characters if isinstance(item, dict)}
            required_types = {"protagonist", "messenger", "supporter", "adversary"}
            if types != required_types:
                errors.append(
                    "characters must contain protagonist, messenger, supporter, and adversary"
                )
            for index, character in enumerate(characters, start=1):
                if isinstance(character, dict):
                    errors.extend(
                        f"characters[{index}].{error}"
                        for error in _required_field_errors(
                            character,
                            ("type", "name", "description"),
                        )
                    )
        return errors

    if artifact == "important_past_events":
        errors = _list_errors(value, artifact, expected=10)
        items = value.get(artifact)
        if isinstance(items, list):
            for index, item in enumerate(items, start=1):
                if isinstance(item, dict):
                    errors.extend(
                        f"{artifact}[{index}].{error}"
                        for error in _required_field_errors(
                            item,
                            ("event_name", "description", "impact"),
                        )
                    )
        return errors

    if artifact == "social_groups":
        errors = _list_errors(value, artifact, expected=10)
        items = value.get(artifact)
        if isinstance(items, list):
            for index, item in enumerate(items, start=1):
                if isinstance(item, dict):
                    errors.extend(
                        f"{artifact}[{index}].{error}"
                        for error in _required_field_errors(
                            item,
                            ("name", "members", "purpose", "activities"),
                        )
                    )
        return errors

    if artifact == "people_list":
        errors = _list_errors(value, "people", expected=100)
        items = value.get("people")
        if isinstance(items, list):
            for index, item in enumerate(items, start=1):
                if isinstance(item, dict):
                    errors.extend(
                        f"people[{index}].{error}"
                        for error in _required_field_errors(
                            item,
                            ("name", "age", "gender", "residence", "role"),
                        )
                    )
        return errors

    if artifact == "future_scenarios":
        errors = _list_errors(value, "scenarios", expected=3)
        scenarios = value.get("scenarios")
        if isinstance(scenarios, list):
            types = {item.get("scenario_type") for item in scenarios if isinstance(item, dict)}
            if types != {"optimistic", "pessimistic", "moderate"}:
                errors.append(
                    "scenarios must contain optimistic, pessimistic, and moderate"
                )
        return errors

    if artifact == "plot":
        errors = _mapping_errors(value, "plot")
        plot = value.get("plot")
        if isinstance(plot, dict):
            errors.extend(_list_errors(plot, "chapters", expected=10))
            chapters = plot.get("chapters")
            if isinstance(chapters, list):
                numbers = [item.get("chapter") for item in chapters if isinstance(item, dict)]
                if numbers != list(range(1, 11)):
                    errors.append("plot.chapters must contain chapter numbers 1 through 10")
        return errors

    if artifact == "plot_chapter":
        if chapter_number is None:
            return ["chapter_number is required for plot_chapter validation"]
        key = f"chapter_{chapter_number}"
        errors = _mapping_errors(value, key)
        chapter = value.get(key)
        if isinstance(chapter, dict):
            errors.extend(
                f"{key}.{error}"
                for error in _required_field_errors(
                    chapter,
                    ("situation", "events", "protagonist_actions", "situation_change"),
                )
            )
        return errors

    if artifact == "entity_graph":
        from .world.graph import validate_graph

        return validate_graph(value)

    if artifact == "keywords":
        return _list_errors(value, "keywords", maximum=10)

    if artifact == "references":
        return _list_errors(value, "references", maximum=20)

    return []


def assert_valid_artifact(
    artifact: str,
    data: Any,
    chapter_number: Optional[int] = None,
) -> None:
    """Raise :class:`OutputValidationError` when an artifact is invalid."""
    errors = validate_artifact(artifact, data, chapter_number=chapter_number)
    if errors:
        raise OutputValidationError(artifact, errors)


def validate_text(data: Any) -> List[str]:
    """Return errors for a free-form text artifact."""
    if not isinstance(data, str) or not data.strip():
        return ["text output must be non-empty"]
    return []


PHASE3_ARTIFACTS = (
    "events",
    "observation",
    "interpretation",
    "media",
    "important_past_events",
    "social_structure",
    "living_environment",
    "social_groups",
    "people_list",
    "future_scenarios",
)


def validate_phase_state(phase_name: str, data: Any) -> List[str]:
    """Validate a complete phase checkpoint, including required artifacts."""
    errors: List[str] = []
    if not isinstance(data, dict):
        return ["phase state must be a mapping"]

    if phase_name == "phase1_expansion":
        required = (
            "desire_list",
            "ability_list",
            "role_list",
            "plottype_list",
            "plottype",
        )
        for key in required:
            if key not in data:
                errors.append(f"missing {key}")
            else:
                errors.extend(
                    f"{key}: {error}"
                    for error in validate_artifact(key, data[key])
                )
        return errors

    if phase_name == "phase2_characters":
        if "characters_list" not in data:
            return ["missing characters_list"]
        return [
            f"characters: {error}"
            for error in validate_artifact("characters", data["characters_list"])
        ]

    if phase_name == "phase3_world":
        for key in PHASE3_ARTIFACTS:
            if key not in data:
                errors.append(f"missing {key}")
            else:
                errors.extend(
                    f"{key}: {error}"
                    for error in validate_artifact(key, data[key])
                )
        return errors

    if phase_name == "phase4_plot":
        if "plot" not in data:
            errors.append("missing plot")
        else:
            errors.extend(validate_artifact("plot", data["plot"]))
        for chapter_number in range(1, 11):
            for key, artifact in (
                (f"plot_{chapter_number}", "plot_chapter"),
                (f"plot_keywords_{chapter_number}", "keywords"),
                (f"plot_reference_{chapter_number}", "references"),
            ):
                if key not in data:
                    errors.append(f"missing {key}")
                else:
                    errors.extend(
                        f"{key}: {error}"
                        for error in validate_artifact(
                            artifact,
                            data[key],
                            chapter_number=chapter_number,
                        )
                    )
        return errors

    if phase_name == "phase5_novels":
        for chapter_number in range(1, 11):
            key = f"story_{chapter_number}"
            if key not in data:
                errors.append(f"missing {key}")
            else:
                errors.extend(f"{key}: {error}" for error in validate_text(data[key]))
        return errors

    if phase_name == "phase6_references":
        if len(data) != 17:
            errors.append(f"references must contain 17 files (got {len(data)})")
        for filename, content in data.items():
            errors.extend(
                f"{filename}: {error}" for error in validate_text(content)
            )
        return errors

    return errors
