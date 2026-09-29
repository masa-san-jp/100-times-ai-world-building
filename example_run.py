#!/usr/bin/env python3
"""
Example Run Script
Demonstrates how to use the pipeline from Python code
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src import Pipeline, load_config, run_batch, setup_logging

# ---------------------------------------------------------------------------
# Local model options
# ---------------------------------------------------------------------------
LOCAL_MODELS = [
    {
        "name": "gpt-oss:20b",
        "label": "gpt-oss:20b (standard – recommended)",
        "description": "Full-precision 20B model. Best quality for most machines with ≥32 GB RAM or ≥16 GB VRAM.",
    },
    {
        "name": "gpt-oss:20b-q8",
        "label": "gpt-oss:20b-q8 (8-bit quantized)",
        "description": "8-bit quantized 20B model. Balanced quality / memory trade-off (16–24 GB VRAM).",
    },
    {
        "name": "gpt-oss:20b-q4",
        "label": "gpt-oss:20b-q4 (4-bit quantized)",
        "description": "4-bit quantized 20B model. Lowest memory footprint (8–16 GB VRAM).",
    },
    {
        "name": "gpt-oss:120b",
        "label": "gpt-oss:120b (high-end – powerful machines only)",
        "description": "120B model. Highest generation quality. Requires ≥60 GB VRAM or very large RAM.",
    },
]


class ContextInputError(ValueError):
    """Raised when no usable user input was supplied."""


def load_context(args, prompt=input, allow_images_only: bool = False) -> str:
    """Load the user's input from a local text/YAML/JSON file.

    There is intentionally no built-in default input: every world must be
    generated from what the user supplies. In the interactive menu the file
    path is asked for; non-interactive runs must pass ``--context-file``.
    """
    path = args.context_file
    images_only_allowed = allow_images_only and bool(getattr(args, "image", None))
    if not path and args.choice is None:
        hint = "（画像だけで生成する場合は空欄）" if images_only_allowed else ""
        path = prompt(f"入力ファイルのパス（テキスト/YAML/JSON）{hint}: ").strip()
    if not path and images_only_allowed:
        return ""
    if not path:
        raise ContextInputError(
            "No input supplied. Pass --context-file with your own text/YAML/JSON file; "
            "there is no built-in default input."
        )
    context_path = Path(path).expanduser()
    if not context_path.is_file():
        raise ContextInputError(f"Input file not found: {context_path}")
    text = context_path.read_text(encoding="utf-8")
    if not text.strip():
        raise ContextInputError(f"Input file is empty: {context_path}")
    return text


def make_pipeline(
    args,
    model: str = None,
    run_id: str = None,
    output_dir: str = None,
) -> Pipeline:
    """Create a pipeline with the selected backend and role models."""
    kwargs = {
        "model": model or args.model,
        "run_id": run_id or args.run_id,
        "seed": args.seed,
        "output_dir": output_dir if output_dir is not None else args.output_dir,
        "structured_model": args.structured_model,
        "story_model": args.story_model,
        "reference_model": args.reference_model,
        "vision_model": args.vision_model,
    }
    if getattr(args, "backend", None) is not None:
        kwargs["backend"] = args.backend
    return Pipeline(**kwargs)


def select_model_for_backend(args) -> str:
    """Select a local model only when the Ollama backend is in use."""
    if args.model:
        return args.model
    backend = getattr(args, "backend", None)
    if backend is None:
        try:
            config = load_config("config/ollama_config.yaml")
            backend = config.get("backend", config.get("llm", {}).get("backend"))
        except Exception:
            backend = None
    if backend == "anthropic":
        return None
    return select_model()


def _pipeline_model(args) -> str:
    """Return the CLI model override without prompting Anthropic users."""
    return select_model_for_backend(args)


def select_model() -> str:
    """Interactive model selection menu.

    Returns the chosen model name string.
    """
    print("\n--- Model Selection ---")
    for i, m in enumerate(LOCAL_MODELS, 1):
        print(f"{i}. {m['label']}")
        print(f"   {m['description']}")
    print()

    while True:
        try:
            raw = input("Select model [1]: ").strip()
            if raw == "":
                return LOCAL_MODELS[0]["name"]
            idx = int(raw) - 1
            if 0 <= idx < len(LOCAL_MODELS):
                return LOCAL_MODELS[idx]["name"]
        except ValueError:
            pass
        print(f"Please enter a number between 1 and {len(LOCAL_MODELS)}.")


def run_phase1_only(args):
    """Run only Phase 1 (100x expansion) for quick testing"""
    print("=" * 60)
    print("Running Phase 1 (100x Expansion) Only")
    print("=" * 60)

    user_context = load_context(args)

    # Model selection
    model = _pipeline_model(args)

    # Setup logging
    setup_logging(log_level="INFO", console=True)

    # Initialize pipeline (a new run_id is generated automatically)
    pipeline = make_pipeline(args, model=model)

    # Check prerequisites
    if not pipeline.check_prerequisites():
        print("\n✗ Prerequisites not met. Please check the errors above.")
        return 1


    # Run Phase 1
    print("\nStarting Phase 1...")
    pipeline.manifest.set_status("running")
    try:
        results = pipeline.run_phase1_expansion(user_context)
    except KeyboardInterrupt:
        pipeline.manifest.set_status("cancelled")
        raise
    except Exception as exc:
        pipeline.manifest.set_status("failed", error=str(exc))
        raise
    pipeline.manifest.set_status("completed")

    print("\n" + "=" * 60)
    print("Phase 1 Complete!")
    print("=" * 60)
    print(f"Generated {len(results)} outputs:")
    for key in results.keys():
        print(f"  - {key}")

    print(f"\nOutputs saved to: {pipeline.base_dir}/intermediate/")
    print(f"Run ID: {pipeline.run_id}")
    return 0


def run_full_pipeline(args):
    """Run the complete pipeline (WARNING: Takes several hours)"""
    print("=" * 60)
    print("Running Full Pipeline")
    print("WARNING: This will take 2-10 hours depending on your hardware")
    print("=" * 60)

    user_context = load_context(args, allow_images_only=True)

    response = "yes" if args.yes else input("\nAre you sure you want to continue? (yes/no): ")
    if response.lower() != "yes":
        print("Cancelled.")
        return 0

    # Model selection
    model = _pipeline_model(args)

    # Setup logging
    setup_logging(
        log_level="INFO",
        log_file="./logs/full_pipeline.log",
        console=True
    )

    # Initialize pipeline (a new run_id is generated automatically)
    pipeline = make_pipeline(args, model=model)

    # Check prerequisites
    if not pipeline.check_prerequisites():
        print("\n✗ Prerequisites not met. Please check the errors above.")
        return 1


    # Run full pipeline
    print("\nStarting full pipeline...")
    results = pipeline.run_full_pipeline(
        user_context,
        context_images=args.image,
        extract_context=args.extract_context,
    )

    print("\n" + "=" * 60)
    print("Full Pipeline Complete!")
    print("=" * 60)
    print(f"\nRun ID: {pipeline.run_id}")
    print(f"Generated outputs (all under {pipeline.base_dir}/):")
    print(f"  - Novels:            {pipeline.base_dir}/final/novels/")
    print(f"  - References:        {pipeline.base_dir}/final/references/")
    print(f"  - Intermediate data: {pipeline.base_dir}/intermediate/")
    print(f"  - Checkpoints:       {pipeline.base_dir}/checkpoints/")

    return 0


def run_batch_pipeline(args):
    """Run several independent full pipelines and persist a batch summary."""
    print("=" * 60)
    print(f"Running Full Pipeline {args.runs} Times")
    print("Each run gets its own output directory and run seed.")
    print("=" * 60)

    user_context = load_context(args, allow_images_only=True)

    response = "yes" if args.yes else input(
        "\nAre you sure you want to continue? (yes/no): "
    )
    if response.lower() != "yes":
        print("Cancelled.")
        return 0

    model = _pipeline_model(args)
    setup_logging(
        log_level="INFO",
        log_file="./logs/batch_pipeline.log",
        console=True,
    )
    pipeline_kwargs = {
        "model": model,
        "output_dir": args.output_dir,
        "structured_model": args.structured_model,
        "story_model": args.story_model,
        "reference_model": args.reference_model,
        "vision_model": args.vision_model,
    }
    if getattr(args, "backend", None) is not None:
        pipeline_kwargs["backend"] = args.backend
    summary = run_batch(
        user_context=user_context,
        runs=args.runs,
        seed=args.seed,
        pipeline_kwargs=pipeline_kwargs,
        context_images=args.image,
        extract_context=args.extract_context,
    )
    print("\n" + "=" * 60)
    print("Batch Complete")
    print("=" * 60)
    print(f"Batch ID: {summary['batch_id']}")
    print(f"Completed: {summary.get('completed_runs', 0)}")
    print(f"Failed: {summary.get('failed_runs', 0)}")
    print(f"Summary: {summary['summary_path']}")
    return 0 if summary.get("failed_runs", 0) == 0 else 1


def discover_run_packages(output_root: Path):
    """Find current and legacy world packages, including batch children."""
    packages = []

    def add(path: Path):
        if not path.is_dir():
            return
        if path.name.startswith("world_"):
            run_id = path.name[len("world_"):]
        elif path.name.startswith("run_"):
            run_id = path.name[len("run_"):]
        else:
            return
        packages.append({"run_id": run_id, "path": path, "output_dir": path.parent})

    if output_root.is_dir():
        for path in output_root.iterdir():
            add(path)
        for batch_dir in output_root.glob("batch_*"):
            for worlds_dir in (batch_dir / "worlds", batch_dir / "runs"):
                if worlds_dir.is_dir():
                    for path in worlds_dir.iterdir():
                        add(path)
    return sorted(packages, key=lambda item: item["path"].stat().st_mtime, reverse=True)


def resume_from_phase(args):
    """Resume the selected run from its latest available checkpoint."""
    print("=" * 60)
    print("Resume from Checkpoint")
    print("=" * 60)

    # Keep the model stored in the run manifest unless an explicit override
    # was supplied. This preserves the original generation environment.
    model = args.model

    # Setup logging
    setup_logging(log_level="INFO", console=True)

    output_root = Path(args.output_dir or "./output")
    packages = discover_run_packages(output_root)
    selected_package = None
    if args.run_id:
        run_id = args.run_id
        for package in packages:
            if package["run_id"] == run_id:
                selected_package = package
                break
    elif packages:
        print("\nAvailable runs:")
        for i, package in enumerate(packages[:10], 1):
            print(f"{i}. {package['run_id']} ({package['path']})")
        selected = input("Select run [1]: ").strip() or "1"
        try:
            selected_package = packages[int(selected) - 1]
            run_id = selected_package["run_id"]
        except (ValueError, IndexError):
            print("Invalid run selection.")
            return 1
    else:
        print("\n✗ No previous runs found.")
        return 1

    pipeline = make_pipeline(
        args,
        model=model,
        run_id=run_id,
        output_dir=(
            str(selected_package["output_dir"])
            if selected_package is not None
            else None
        ),
    )

    # List available checkpoints for the selected run
    checkpoints = pipeline.checkpoint_manager.list_checkpoints()

    if not checkpoints:
        print("\n✗ No checkpoints found.")
        return 1

    print("\nAvailable checkpoints:")
    for i, cp in enumerate(checkpoints[:10], 1):
        print(f"{i}. {Path(cp).name}")

    if pipeline.resume_full_pipeline():
        print(f"\n✓ Successfully resumed run {run_id}")
        print(f"Outputs saved to: {pipeline.base_dir}/")
        return 0
    else:
        print(f"\n✗ Failed to resume run {run_id}")
        return 1


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the fully local 100 TIMES AI WORLD BUILDING pipeline."
    )
    parser.add_argument(
        "--choice", choices=("1", "2", "3", "4"),
        help="1=Phase 1, 2=full pipeline, 3=resume, 4=exit",
    )
    parser.add_argument(
        "--context-file",
        help="Your own text/YAML/JSON input file (required; there is no default input)",
    )
    parser.add_argument(
        "--backend",
        choices=("ollama", "anthropic"),
        default=None,
        help="LLM backend (default: config value, otherwise ollama)",
    )
    parser.add_argument("--model", help="Use this backend model for all roles")
    parser.add_argument("--structured-model", help="Ollama model for JSON/world-building phases")
    parser.add_argument("--story-model", help="Ollama model for novel chapters")
    parser.add_argument("--reference-model", help="Ollama model for reference documents")
    parser.add_argument("--vision-model", help="Ollama vision model for image context")
    parser.add_argument(
        "--image", action="append", default=[],
        help="Local image path; may be specified more than once",
    )
    parser.add_argument(
        "--extract-context", action="store_true",
        help="Use a local model to normalize text context into structured YAML",
    )
    parser.add_argument("--run-id", help="Run ID, especially useful with --choice 3")
    parser.add_argument(
        "--output-dir",
        help="Root directory for generated world packages (default: ./output; e.g. examples)",
    )
    parser.add_argument("--seed", type=int, help="Fixed seed (optional)")
    parser.add_argument(
        "--runs", type=int, default=1,
        help="Number of independent full runs when --choice 2 is selected",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Skip the long-running execution confirmation prompt",
    )
    return parser.parse_args()


def main():
    """Main entry point"""
    args = parse_args()

    if args.choice is None:
        print("\n100 TIMES AI WORLD BUILDING - Example Run\n")
        print("Select an option:")
        print("1. Run Phase 1 only (quick test, ~15-90 min)")
        print("2. Run full pipeline (complete generation, ~2-10 hours)")
        print("3. Resume from checkpoint")
        print("4. Exit")

    try:
        choice = args.choice or input("\nEnter your choice (1-4): ").strip()

        if choice == "1":
            return run_phase1_only(args)
        elif choice == "2":
            if args.runs < 1:
                print("--runs must be at least 1.")
                return 1
            if args.runs > 1:
                if args.run_id:
                    print("--run-id cannot be used with --runs greater than 1.")
                    return 1
                return run_batch_pipeline(args)
            return run_full_pipeline(args)
        elif choice == "3":
            return resume_from_phase(args)
        elif choice == "4":
            print("Goodbye!")
            return 0
        else:
            print("Invalid choice.")
            return 1

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        return 1
    except ContextInputError as e:
        print(f"\n✗ {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
