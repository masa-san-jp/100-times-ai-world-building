#!/usr/bin/env python3
"""
Setup Check Script
Verify that all prerequisites are met for running the world engine
"""

import argparse
import os
import sys
from pathlib import Path


def check_python_version():
    """Check Python version"""
    version = sys.version_info
    print(f"Python version: {version.major}.{version.minor}.{version.micro}")

    if version.major > 3 or (version.major == 3 and version.minor >= 10):
        print("✓ Python version OK (3.10+)")
        return True
    else:
        print("✗ Python version too old (required: 3.10+)")
        return False


def check_directory_structure():
    """Check if required directories exist"""
    required_dirs = [
        "config",
        "config/prompts",
        "config/world",
        "src",
        "src/world",
        "tests",
    ]

    all_exist = True
    for dir_path in required_dirs:
        path = Path(dir_path)
        if path.exists():
            print(f"✓ {dir_path}/")
        else:
            print(f"✗ {dir_path}/ (missing)")
            all_exist = False

    return all_exist


ENGINE_FILES = [
    "config/ollama_config.yaml",
    "config/prompts/input_brief.yaml",
    "config/prompts/world_axes.yaml",
    "config/prompts/world/operators.yaml",
    "config/world/domains.yaml",
    "config/world/explore.yaml",
    "config/world/language_rules.yaml",
    "config/world/render_labels.yaml",
    "config/world/reward.yaml",
    "config/world/quality.yaml",
    "example_run.py",
    "src/__init__.py",
    "src/pipeline.py",
    "src/batch.py",
    "src/quality.py",
    "src/compare.py",
    "src/ollama_client.py",
    "src/llm/__init__.py",
    "src/llm/factory.py",
    "src/llm/anthropic_client.py",
    "src/checkpoint_manager.py",
    "src/run_manifest.py",
    "src/world/input.py",
    "src/world/axes.py",
    "src/world/graph.py",
    "src/world/operators.py",
    "src/world/verify.py",
    "src/world/reward.py",
    "src/world/builder.py",
    "config/prompts/world/steps.yaml",
    "config/world/criteria.yaml",
    "src/world/explore.py",
    "src/world/render.py",
    "README.md",
    "README_LOCAL.md",
    "DESIGN_SPEC_LOCAL.md",
    "requirements-local.txt",
    ".gitignore",
]


def check_required_files():
    """Check if the engine's code and configuration files exist"""
    all_exist = True
    for file_path in ENGINE_FILES:
        path = Path(file_path)
        if path.exists():
            print(f"✓ {file_path}")
        else:
            print(f"✗ {file_path} (missing)")
            all_exist = False

    return all_exist


def check_engine_config(config_path="config/ollama_config.yaml"):
    """Check that the engine's configuration and prompts load and are usable"""
    ok = True
    try:
        import yaml

        config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        print(f"✓ {config_path} parses")
    except Exception as exc:
        print(f"✗ {config_path} could not be loaded: {exc}")
        return False

    try:
        from src.world.explore import load_explore_config

        explore = load_explore_config(
            overrides=(config.get("engine") or {}).get("explore") or {}
        )
        budget = explore.get("budget", {})
        print(
            "✓ exploration config "
            f"(max_iterations={budget.get('max_iterations')}, "
            f"max_wall_seconds={budget.get('max_wall_seconds')}, "
            f"max_generation_calls={budget.get('max_generation_calls')})"
        )
    except Exception as exc:
        print(f"✗ exploration config: {exc}")
        ok = False

    try:
        from src.world.axes import load_catalog
        from src.world.operators import load_prompts
        from src.world.builder import EntityBuilder
        from src.world.reward import load_reward_config

        load_catalog()
        load_prompts()
        EntityBuilder(object())
        load_reward_config()
        print("✓ domain catalog, operator/step prompts and deterministic parameters load")
    except Exception as exc:
        print(f"✗ engine resources: {exc}")
        ok = False

    backend = config.get("backend", "ollama")
    if backend == "ollama" and not (config.get("model") or {}).get("name"):
        print("✗ model.name is not set (the model is taken from the config or --model)")
        ok = False
    return ok


def check_dependencies(backend="ollama"):
    """Check if required Python packages are installed"""
    required_packages = [
        "yaml",
        "requests",
        "tqdm",
        "loguru",
    ]
    optional_packages = [
        "ollama",  # Optional SDK; the CLI uses the Ollama HTTP API directly.
    ]
    if backend != "anthropic":
        optional_packages.append("anthropic")

    print("\nChecking Python packages required by the engine...")
    all_installed = True

    for package in required_packages:
        try:
            if package == "yaml":
                __import__("yaml")
            else:
                __import__(package)
            print(f"✓ {package}")
        except ImportError:
            print(f"✗ {package} (not installed)")
            all_installed = False

    print("\nChecking optional packages...")
    for package in optional_packages:
        try:
            __import__(package)
            print(f"✓ {package}")
        except ImportError:
            print(f"⚠ {package} (optional)")

    return all_installed


def check_anthropic(config):
    """Check SDK/auth and retrieve configured model capabilities."""
    try:
        import anthropic
    except ImportError:
        print("✗ anthropic (not installed; install requirements-cloud.txt)")
        return False

    print("✓ anthropic SDK")
    try:
        # Construction performs only local credential/profile resolution.
        client = anthropic.Anthropic()
        print("✓ Anthropic authentication information found")
    except Exception as exc:
        if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            print(f"✗ Anthropic authentication could not be initialized: {exc}")
        else:
            print("✗ Anthropic authentication information not found")
            print("  Set ANTHROPIC_API_KEY or configure the SDK auth profile.")
        return False

    llm_config = config.get("llm", {})
    anthropic_config = llm_config.get("anthropic", {}) or config.get(
        "anthropic", {}
    )
    model = anthropic_config.get("model")
    if not model:
        print("✗ Anthropic model is not configured")
        print("  Set anthropic.model in the selected configuration file.")
        return False

    request_options = anthropic_config.get("request_options", {})
    try:
        model_info = client.models.retrieve(model)
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        if status_code in {401, 403}:
            print(f"✗ Anthropic authentication failed while retrieving model {model}: {exc}")
        elif status_code == 404:
            print(f"✗ Anthropic model does not exist or is unavailable: {model}")
        else:
            print(f"✗ Could not retrieve Anthropic model {model}: {exc}")
        return False

    def field(name):
        if isinstance(model_info, dict):
            return model_info.get(name)
        return getattr(model_info, name, None)

    max_input_tokens = field("max_input_tokens")
    model_max_tokens = field("max_tokens")
    print(f"✓ Anthropic model: {model}")
    print(f"  max_input_tokens: {max_input_tokens}")
    print(f"  max_tokens: {model_max_tokens}")

    configured_max_tokens = request_options.get("max_tokens")
    if (
        configured_max_tokens is not None
        and model_max_tokens is not None
        and configured_max_tokens > model_max_tokens
    ):
        print(
            "⚠ request_options.max_tokens exceeds the model max_tokens "
            f"({configured_max_tokens} > {model_max_tokens})"
        )
    return True


def selected_backend(cli_backend=None, config_path="config/ollama_config.yaml"):
    """Resolve the setup check backend from CLI first, then configuration."""
    if cli_backend:
        return cli_backend
    try:
        import yaml

        config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        return config.get("backend", config.get("llm", {}).get("backend", "ollama"))
    except Exception:
        return "ollama"


def _ollama_url(config):
    server = config.get("server", {}) or {}
    return f"{server.get('host', 'http://localhost')}:{server.get('port', 11434)}"


def check_ollama_server(config=None):
    """Check if Ollama server is accessible"""
    url = _ollama_url(config or {})
    try:
        import requests

        response = requests.get(f"{url}/api/tags", timeout=5)
        if response.status_code == 200:
            print(f"✓ Ollama server is running ({url})")
            return True
        else:
            print(f"✗ Ollama server returned status {response.status_code}")
            return False
    except ImportError:
        print("⚠ Cannot check Ollama server (requests not installed)")
        return False
    except requests.exceptions.ConnectionError:
        print(f"✗ Ollama server is not running ({url})")
        print("  Start it with: ollama serve")
        return False
    except Exception as e:
        print(f"✗ Error checking Ollama server: {e}")
        return False


def check_ollama_models(config=None, model=None):
    """Check that the configured generation model is available locally.

    The model name comes from ``--model`` or ``model.name`` in the config;
    ``models.vision`` is reported separately because it is only needed for
    image input.
    """
    config = config or {}
    target = model or (config.get("model", {}) or {}).get("name")
    if not target:
        print("✗ No model configured (set model.name or pass --model)")
        return False
    try:
        import requests

        response = requests.get(f"{_ollama_url(config)}/api/tags", timeout=5)
        if response.status_code != 200:
            print("✗ Cannot check models (server not responding)")
            return False
        names = [m.get("name", "") for m in response.json().get("models", [])]
        found = target in names or f"{target}:latest" in names
        if found:
            print(f"✓ Model found: {target}")
        else:
            print(f"✗ Model not found: {target}")
            print(f"  Download with: ollama pull {target}")
        vision = (config.get("models", {}) or {}).get("vision")
        if vision:
            if vision in names or f"{vision}:latest" in names:
                print(f"✓ Vision model found: {vision}")
            else:
                print(f"⚠ Vision model not found: {vision} (only needed for --image)")
        return found
    except Exception as e:
        print(f"⚠ Cannot check models: {e}")
        return False


def main():
    """Main check routine"""
    parser = argparse.ArgumentParser(description="Check world engine setup")
    parser.add_argument("--backend", choices=("ollama", "anthropic"))
    parser.add_argument("--model", help="Model to check (default: from the config)")
    parser.add_argument("--config", default="config/ollama_config.yaml")
    args = parser.parse_args()
    backend = selected_backend(args.backend, args.config)

    print("=" * 60)
    print("100 TIMES AI WORLD BUILDING - Setup Check")
    print("=" * 60)
    print(f"Backend: {backend}")
    print()

    checks = {
        "Python Version": check_python_version(),
    }

    print("\n" + "=" * 60)
    print("Directory Structure")
    print("=" * 60)
    checks["Directory Structure"] = check_directory_structure()

    print("\n" + "=" * 60)
    print("Required Files")
    print("=" * 60)
    checks["Required Files"] = check_required_files()

    print("\n" + "=" * 60)
    print("Python Dependencies")
    print("=" * 60)
    checks["Dependencies"] = check_dependencies(backend)

    print("\n" + "=" * 60)
    print("Engine Configuration")
    print("=" * 60)
    checks["Engine Configuration"] = check_engine_config(args.config)

    if backend == "anthropic":
        print("\n" + "=" * 60)
        print("Anthropic Setup (SDK/auth + model capability check)")
        print("=" * 60)
        try:
            import yaml

            config = yaml.safe_load(
                Path(args.config).read_text(encoding="utf-8")
            ) or {}
        except Exception as exc:
            print(f"✗ Could not load configuration for Anthropic setup: {exc}")
            config = {}
        checks["Anthropic SDK/Auth/Model"] = check_anthropic(config)
    else:
        try:
            import yaml

            ollama_config = yaml.safe_load(
                Path(args.config).read_text(encoding="utf-8")
            ) or {}
        except Exception:
            ollama_config = {}
        print("\n" + "=" * 60)
        print("Ollama Setup")
        print("=" * 60)
        checks["Ollama Server"] = check_ollama_server(ollama_config)
        checks["Ollama Models"] = check_ollama_models(ollama_config, args.model)

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    all_passed = True
    for check_name, passed in checks.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {check_name}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("✓ All checks passed! You're ready to start.")
        print("\nNext steps:")
        print("1. Try a short run: python example_run.py "
              "--context-file path/to/your_input.yaml --max-iterations 5 --yes")
        print("2. Run the full engine: python example_run.py "
              "--context-file path/to/your_input.yaml --yes")
        print("3. Use --max-iterations / --max-minutes / --max-calls to set the budget")
    else:
        print("✗ Some checks failed. Please fix the issues above.")
        print("\nCommon fixes:")
        print("- Install dependencies: pip install -r requirements-local.txt")
        print("- Start Ollama: ollama serve")
        print("- Download the configured model: ollama pull <model.name from config>")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
