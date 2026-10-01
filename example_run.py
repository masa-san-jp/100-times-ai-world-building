#!/usr/bin/env python3
"""Run the world-building engine from the command line.

Give it your own input file (text, YAML or JSON; any shape) and a budget; it
generates a world reference (``final/world.json``, ``final/world_bible/``,
``final/world_report.md``) without asking anything else.  There is no built-in
default input.

    python example_run.py --context-file path/to/your_input.yaml --yes
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src import Pipeline, load_config, run_batch, setup_logging  # noqa: E402


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


def budget_from_args(args) -> dict:
    """Translate the CLI budget arguments to engine budget keys."""
    budget = {}
    if getattr(args, "max_iterations", None) is not None:
        budget["max_iterations"] = args.max_iterations
    if getattr(args, "max_minutes", None) is not None:
        budget["max_wall_seconds"] = args.max_minutes * 60.0
    if getattr(args, "max_calls", None) is not None:
        budget["max_generation_calls"] = args.max_calls
    return budget


def make_pipeline(args, run_id=None, output_dir=None, backend=None) -> Pipeline:
    """Create a pipeline from the CLI arguments."""
    kwargs = {
        "config_path": args.config,
        "model": args.model,
        "run_id": run_id or args.run_id,
        "seed": args.seed,
        "output_dir": output_dir if output_dir is not None else args.output_dir,
        "vision_model": args.vision_model,
        "budget": budget_from_args(args),
    }
    chosen = backend if backend is not None else getattr(args, "backend", None)
    if chosen is not None:
        kwargs["backend"] = chosen
    return Pipeline(**kwargs)


def _setup_logging(args, log_name: str) -> None:
    logging_config = (load_config(args.config) or {}).get("logging", {})
    setup_logging(
        log_level=logging_config.get("level", "INFO"),
        log_file=logging_config.get("file") or f"./logs/{log_name}.log",
        console=logging_config.get("console", True),
    )


def _print_outputs(pipeline, result) -> None:
    root = pipeline.package_dir
    print(f"\nRun ID: {pipeline.run_id}")
    print(f"Stop reason: {result.stop_reason} "
          f"({result.iterations} iterations)")
    print(f"Outputs (all under {root}/):")
    print(f"  - World data:     {root}/final/world.json")
    print(f"  - World bible:    {root}/final/world_bible/README.md")
    print(f"  - World report:   {root}/final/world_report.md")
    print(f"  - Quality report: {root}/quality_report.md")
    print(f"  - Preference log: {root}/world/preferences.jsonl")
    print(f"  - Checkpoints:    {root}/checkpoints/")


def _confirm(args) -> bool:
    response = "yes" if args.yes else input(
        "\nThis runs until the budget or a stop condition is reached. "
        "Continue? (yes/no): ")
    if response.lower() != "yes":
        print("Cancelled.")
        return False
    return True


def run_generate(args, backend=None):
    """Generate one world from the input file."""
    print("=" * 60)
    print("Generating a world")
    print("=" * 60)

    user_input = load_context(args, allow_images_only=True)
    if not _confirm(args):
        return 0

    _setup_logging(args, "world_engine")
    pipeline = make_pipeline(args, backend=backend)
    if not pipeline.check_prerequisites(include_vision=bool(args.image)):
        print("\n✗ Prerequisites not met. Please check the errors above.")
        return 1

    print("\nStarting the engine...")
    result = pipeline.run(
        user_input, images=args.image or None,
        source_name=Path(args.context_file).name if args.context_file else None,
    )
    print("\n" + "=" * 60)
    print("World generation complete")
    print("=" * 60)
    _print_outputs(pipeline, result)
    return 0


def run_batch_generate(args, backend=None):
    """Generate several independent worlds from the same input."""
    print("=" * 60)
    print(f"Generating {args.runs} independent worlds")
    print("Each world gets its own package and seed.")
    print("=" * 60)

    user_input = load_context(args, allow_images_only=True)
    if not _confirm(args):
        return 0

    _setup_logging(args, "world_batch")
    pipeline_kwargs = {
        "config_path": args.config,
        "model": args.model,
        "output_dir": args.output_dir,
        "vision_model": args.vision_model,
    }
    chosen = backend if backend is not None else getattr(args, "backend", None)
    if chosen is not None:
        pipeline_kwargs["backend"] = chosen
    summary = run_batch(
        raw_input=user_input,
        runs=args.runs,
        seed=args.seed,
        pipeline_kwargs=pipeline_kwargs,
        images=args.image or None,
        source_name=Path(args.context_file).name if args.context_file else None,
        budget=budget_from_args(args),
    )
    print("\n" + "=" * 60)
    print("Batch complete")
    print("=" * 60)
    print(f"Batch ID: {summary['batch_id']}")
    print(f"Completed: {summary.get('completed_runs', 0)}")
    print(f"Failed: {summary.get('failed_runs', 0)}")
    print(f"Summary: {summary['summary_path']}")
    if summary.get("comparison_path"):
        print(f"Comparison: {summary['comparison_path']}")
    return 0 if summary.get("failed_runs", 0) == 0 else 1


def discover_run_packages(output_root: Path):
    """Find world packages under the output root, including batch children."""
    packages = []

    def add(path: Path):
        if path.is_dir() and path.name.startswith("world_") \
                and (path / "run_manifest.json").is_file():
            packages.append({"run_id": path.name[len("world_"):],
                             "path": path, "output_dir": path.parent})

    if output_root.is_dir():
        for path in output_root.iterdir():
            add(path)
        for batch_dir in output_root.glob("batch_*"):
            worlds_dir = batch_dir / "worlds"
            if worlds_dir.is_dir():
                for path in worlds_dir.iterdir():
                    add(path)
    return sorted(packages, key=lambda item: item["path"].stat().st_mtime,
                  reverse=True)


def resume_run(args, backend=None):
    """Continue a previous run from its last checkpoint."""
    print("=" * 60)
    print("Resume a previous run")
    print("=" * 60)

    _setup_logging(args, "world_engine")
    output_root = Path(args.output_dir or "./output")
    packages = discover_run_packages(output_root)
    selected = None
    if args.run_id:
        selected = next(
            (p for p in packages if p["run_id"] == args.run_id), None)
        if selected is None:
            print(f"\n✗ Run not found: {args.run_id}")
            return 1
    elif packages:
        print("\nAvailable runs:")
        for i, package in enumerate(packages[:10], 1):
            print(f"{i}. {package['run_id']} ({package['path']})")
        choice = input("Select run [1]: ").strip() or "1"
        try:
            selected = packages[int(choice) - 1]
        except (ValueError, IndexError):
            print("Invalid run selection.")
            return 1
    else:
        print("\n✗ No previous runs found.")
        return 1

    pipeline = make_pipeline(
        args, run_id=selected["run_id"],
        output_dir=str(selected["output_dir"]), backend=backend)
    if not pipeline.check_prerequisites(include_vision=bool(args.image)):
        print("\n✗ Prerequisites not met. Please check the errors above.")
        return 1
    result = pipeline.resume()
    print(f"\n✓ Resumed run {pipeline.run_id}")
    _print_outputs(pipeline, result)
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate a world reference from your own input "
        "with the autonomous world-building engine."
    )
    parser.add_argument(
        "--choice", choices=("1", "2", "3"),
        help="1=generate a world, 2=resume a run, 3=exit "
        "(default with --context-file or --yes: 1)",
    )
    parser.add_argument(
        "--context-file",
        help="Your own text/YAML/JSON input file (required; there is no default input)",
    )
    parser.add_argument(
        "--config", default="config/ollama_config.yaml",
        help="Backend/engine configuration file",
    )
    parser.add_argument(
        "--backend",
        choices=("ollama", "anthropic"),
        default=None,
        help="LLM backend (default: config value, otherwise ollama)",
    )
    parser.add_argument(
        "--model",
        help="Generation model (default: model.name / anthropic.model from the config)",
    )
    parser.add_argument(
        "--vision-model",
        help="Model that reads --image files (Ollama; default: models.vision)",
    )
    parser.add_argument(
        "--image", action="append", default=[],
        help="Local image path; may be specified more than once",
    )
    parser.add_argument("--run-id", help="Run ID, especially useful with --choice 2")
    parser.add_argument(
        "--output-dir",
        help="Root directory for generated world packages (default: output.base_dir)",
    )
    parser.add_argument("--seed", type=int, help="Fixed seed (optional)")
    parser.add_argument(
        "--runs", type=int, default=1,
        help="Number of independent worlds to generate from the same input",
    )
    parser.add_argument(
        "--max-iterations", type=int,
        help="Budget: exploration iterations (default: config/world/explore.yaml)",
    )
    parser.add_argument(
        "--max-minutes", type=float,
        help="Budget: wall-clock minutes of exploration (default: unlimited)",
    )
    parser.add_argument(
        "--max-calls", type=int,
        help="Budget: generation calls (default: unlimited)",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Skip the long-running execution confirmation prompt",
    )
    return parser.parse_args(argv)


def main(argv=None, backend=None):
    """Main entry point. ``backend`` injects a backend object (tests)."""
    args = parse_args(argv)

    choice = args.choice
    if choice is None and (args.context_file or args.yes):
        choice = args.choice = "1"
    if choice is None:
        print("\n100 TIMES AI WORLD BUILDING\n")
        print("Select an option:")
        print("1. Generate a world from your input")
        print("2. Resume a previous run")
        print("3. Exit")

    try:
        choice = choice or input("\nEnter your choice (1-3): ").strip()

        if choice == "1":
            if args.runs < 1:
                print("--runs must be at least 1.")
                return 1
            if args.runs > 1:
                if args.run_id:
                    print("--run-id cannot be used with --runs greater than 1.")
                    return 1
                return run_batch_generate(args, backend=backend)
            return run_generate(args, backend=backend)
        elif choice == "2":
            return resume_run(args, backend=backend)
        elif choice == "3":
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
