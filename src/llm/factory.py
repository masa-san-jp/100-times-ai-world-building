"""Backend construction kept outside the pipeline orchestration layer."""

from __future__ import annotations

from typing import Dict, Mapping, Optional

from . import LLMBackend


def build_backend_clients(
    backend_name: str,
    model_names: Mapping[str, str],
    server_config: Mapping[str, object],
    anthropic_config: Mapping[str, object],
    injected_backend: Optional[LLMBackend] = None,
) -> Dict[str, LLMBackend]:
    """Build one backend instance for each configured model/role."""
    if injected_backend is not None:
        return {role: injected_backend for role in model_names}

    if backend_name == "ollama":
        # Import lazily so importing the interface never creates a concrete
        # backend dependency cycle.
        from ..ollama_client import OllamaClient

        client_kwargs = {
            "host": server_config.get("host", "http://localhost"),
            "port": server_config.get("port", 11434),
            "timeout": server_config.get("timeout", 300),
            "max_retries": server_config.get("max_retries", 3),
            "retry_delay": server_config.get("retry_delay", 5),
            "call_deadline_seconds": server_config.get("call_deadline_seconds", 1800),
        }
        return {
            role: OllamaClient(model=model_name, **client_kwargs)
            for role, model_name in model_names.items()
        }

    if backend_name == "anthropic":
        from .anthropic_client import AnthropicClient

        common = {
            "timeout": anthropic_config.get("timeout", 900.0),
            "max_retries": anthropic_config.get("max_retries", 2),
            "request_options": anthropic_config.get("request_options"),
        }
        clients: Dict[str, LLMBackend] = {}
        by_model: Dict[str, LLMBackend] = {}
        for role, model_name in model_names.items():
            if model_name not in by_model:
                by_model[model_name] = AnthropicClient(model=model_name, **common)
            clients[role] = by_model[model_name]
        return clients

    raise ValueError(f"Unsupported LLM backend: {backend_name}")
