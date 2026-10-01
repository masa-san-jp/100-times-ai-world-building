"""
100 TIMES AI WORLD BUILDING
Autonomous engine that grows world-setting material from free-form input.
"""

__version__ = "3.0.0"
__author__ = "masa-jp-art"

from .ollama_client import OllamaClient
from .llm import LLMBackend, AnthropicClient
from .world import (
    ExplorationResult, InputBriefBuilder, InputBriefResult, InputSourceError,
    render_world_package, run_world_engine,
)
from .checkpoint_manager import CheckpointManager
from .utils import load_config, data_to_markdown, rich_print, setup_logging
from .pipeline import Pipeline
from .batch import BatchRunner, run_batch
from .run_manifest import RunManifest

__all__ = [
    "OllamaClient",
    "AnthropicClient",
    "LLMBackend",
    "ExplorationResult",
    "InputBriefBuilder",
    "InputBriefResult",
    "InputSourceError",
    "render_world_package",
    "run_world_engine",
    "CheckpointManager",
    "Pipeline",
    "BatchRunner",
    "run_batch",
    "RunManifest",
    "load_config",
    "data_to_markdown",
    "rich_print",
    "setup_logging",
]
