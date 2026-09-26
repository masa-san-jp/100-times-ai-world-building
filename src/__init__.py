"""
100 TIMES AI WORLD BUILDING - Local Version
Core modules for local execution with Ollama + gpt-oss:20b
"""

__version__ = "2.0.0-local"
__author__ = "masa-jp-art"

from .ollama_client import OllamaClient
from .llm import LLMBackend, AnthropicClient
from .checkpoint_manager import CheckpointManager
from .utils import load_config, load_prompts, data_to_markdown, rich_print, setup_logging
from .pipeline import Pipeline
from .batch import BatchRunner, run_batch
from .run_manifest import RunManifest

__all__ = [
    "OllamaClient",
    "AnthropicClient",
    "LLMBackend",
    "CheckpointManager",
    "Pipeline",
    "BatchRunner",
    "run_batch",
    "RunManifest",
    "load_config",
    "load_prompts",
    "data_to_markdown",
    "rich_print",
    "setup_logging",
]
