"""Tests for generated artifact contracts."""

import pytest

from src.validation import (
    OutputValidationError, assert_valid_artifact, validate_artifact,
)
from src.world.graph import new_graph


def test_empty_graph_is_a_valid_entity_graph():
    assert validate_artifact("entity_graph", new_graph("en")) == []


def test_non_object_is_rejected():
    assert validate_artifact("entity_graph", 3)


def test_assert_raises_with_the_artifact_name():
    with pytest.raises(OutputValidationError, match="entity_graph"):
        assert_valid_artifact("entity_graph", "[]")
