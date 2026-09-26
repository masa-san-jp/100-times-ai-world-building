#!/usr/bin/env python3
"""
Setup Check Script
Verify that all prerequisites are met for running the local version
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
        "src",
        "tests",
        "examples",
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


def check_required_files():
    """Check if required files exist"""
    required_files = [
        "config/ollama_config.yaml",
        "config/prompts/expansion.yaml",
        "config/prompts/world_building.yaml",
        "config/prompts/plot_generation.yaml",
        "config/prompts/story_generation.yaml",
        "example_run.py",
        "src/__init__.py",
        "src/ollama_client.py",
        "src/llm/__init__.py",
        "src/llm/factory.py",
        "src/llm/anthropic_client.py",
        "src/checkpoint_manager.py",
        "src/utils.py",
        "src/pipeline.py",
        "src/batch.py",
        "src/output_layout.py",
        "src/run_manifest.py",
        "src/validation.py",
        "local-v2.0.ipynb",
        "README_LOCAL.md",
        "DESIGN_SPEC_LOCAL.md",
        "requirements-local.txt",
        ".gitignore",
    ]

    all_exist = True
    for file_path in required_files:
        path = Path(file_path)
        if path.exists():
            print(f"✓ {file_path}")
        else:
            print(f"✗ {file_path} (missing)")
            all_exist = False

    return all_exist


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
        "psutil",  # Optional notebook/system-monitoring support.
        "jupyter",
    ]
    if backend != "anthropic":
        optional_packages.append("anthropic")

    print("\nChecking Python packages required by the CLI...")
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

    print("\nChecking optional notebook packages...")
    for package in optional_packages:
        try:
            __import__(package)
            print(f"✓ {package}")
        except ImportError:
            print(f"⚠ {package} (optional; install for notebook/system extras)")

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


def check_ollama_server():
    """Check if Ollama server is accessible"""
    try:
        import requests

        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            print("✓ Ollama server is running")
            return True
        else:
            print(f"✗ Ollama server returned status {response.status_code}")
            return False
    except ImportError:
        print("⚠ Cannot check Ollama server (requests not installed)")
        return False
    except requests.exceptions.ConnectionError:
        print("✗ Ollama server is not running")
        print("  Start it with: ollama serve")
        return False
    except Exception as e:
        print(f"✗ Error checking Ollama server: {e}")
        return False


def check_ollama_models():
    """Check if required models are available"""
    try:
        import requests

        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            models = data.get("models", [])
            model_names = [m.get("name", "") for m in models]

            target_models = ["gpt-oss:20b", "gpt-oss:20b-q4", "gpt-oss:20b-q8"]
            found = False

            for target in target_models:
                if target in model_names:
                    print(f"✓ Model found: {target}")
                    found = True
                    break

            if not found:
                print("✗ No required models found")
                print("  Download with: ollama pull gpt-oss:20b")
                return False

            return True
        else:
            print("✗ Cannot check models (server not responding)")
            return False
    except Exception as e:
        print(f"⚠ Cannot check models: {e}")
        return False


def main():
    """Main check routine"""
    parser = argparse.ArgumentParser(description="Check pipeline setup")
    parser.add_argument("--backend", choices=("ollama", "anthropic"))
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
        print("\n" + "=" * 60)
        print("Ollama Setup")
        print("=" * 60)
        checks["Ollama Server"] = check_ollama_server()
        checks["Ollama Models"] = check_ollama_models()

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
        print("1. Run a quick Phase 1 check: python example_run.py --choice 1")
        print("2. Run the complete pipeline: python example_run.py --choice 2")
        print("3. For the notebook workflow, open local-v2.0.ipynb")
    else:
        print("✗ Some checks failed. Please fix the issues above.")
        print("\nCommon fixes:")
        print("- Install dependencies: pip install -r requirements-local.txt")
        print("- Start Ollama: ollama serve")
        print("- Download model: ollama pull gpt-oss:20b")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
