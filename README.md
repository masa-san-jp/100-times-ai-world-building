# 100 TIMES AI WORLD BUILDING

[![Tests](https://github.com/masa-san-jp/100-times-ai-world-building/actions/workflows/tests.yml/badge.svg)](https://github.com/masa-san-jp/100-times-ai-world-building/actions/workflows/tests.yml)

## Overview

This project provides an AI-assisted world-building workflow for generating rich narrative universes.
It contains the original **cloud notebook** (OpenAI / Anthropic API) and a **local pipeline**
that runs through Ollama without sending your creative input to an external API.

The project is designed for **iterative exploration**: you run it multiple times with different contexts
or models, and each generated world is saved as a self-contained output package so previous results are
never overwritten.

## Where to look first

`output/` is the collection of generated world packages:

| Path | Meaning | For visitors |
|------|---------|--------------|
| [`examples/`](examples/README.md) | Reviewed, readable examples and reusable inputs | Start here |
| `output/world_<id>/` | One world output with its input, intermediate data, checkpoints, and final files | Open one package |
| `output/batch_<id>/` | One batch containing several world outputs and its batch manifest | Open for multi-run work |

`output/` is intentionally excluded from Git because it is generated locally. It is not a flat
scratch dump: every `world_<id>/` is one complete or partial generation, and all files belonging
to that generation live inside it. The currently verified complete example is listed in
[`examples/README.md`](examples/README.md).

Current local implementation status: Phase 0–6 and one complete end-to-end example have been
verified on a local Ollama setup. Repeated batch generation is implemented, but the time required
for a 10-run batch depends heavily on the selected model and hardware and has not been validated
as a universal benchmark.

## Related repositories

These repositories form the surrounding 100 TIMES AI creative workflow:

| Repository | What it is for |
|------------|----------------|
| [100 TIMES AI HEROES](https://github.com/masa-san-jp/100-times-ai-heroes) | Expands wishes, abilities, and roles into many character concepts and image-generation prompts. |
| [100 TIMES AI HERO'S JOURNEY](https://github.com/masa-san-jp/100-times-ai-heros-journey) | Turns a writer's self-narrative into a Hero's Journey structure, characters, plot, and story. |
| [100 TIMES AI WORLD BUILDING](https://github.com/masa-san-jp/100-times-ai-world-building) | This repository: expands a narrative into a structured story world, plot, chapters, and reference materials. |
| [100 TIMES AI MANGA DRAWING](https://github.com/masa-san-jp/100-times-ai-manga-drawing) | Documents and experiments with speeding up the manga-making process using generative AI. |

The repositories are related, but they are not a single package with shared dependencies. Start with
the one matching the stage of creation you want to explore.

---

## Cloud Version

- **Setup**: Configure your OpenAI or Anthropic API key and run `20250601-100-TIMES-AI-WORLD-BUILDING-v1.2.ipynb`.
- **Usage**: Open the notebook, fill in your creative context, and execute cells in order.

---

## Local Version

> Full documentation: [README_LOCAL.md](README_LOCAL.md)

### Quick Start

```bash
# 1. Install Ollama and pull the default model
ollama pull gpt-oss:20b

# 2. Start Ollama server
ollama serve

# 3. Install Python dependencies
pip install -r requirements-local.txt

# 4. Run the interactive CLI
python example_run.py
```

To create one complete world output non-interactively:

```bash
python example_run.py --choice 2 --yes \
  --context-file examples/neo_tokyo_complete/input/user_context.yaml \
  --model gpt-oss:20b \
  --output-dir output
```

See [examples/README.md](examples/README.md) for the curation policy.

`--choice 1` runs only the fast Phase 1 expansion. `--choice 2` runs the complete Phase 0–6
pipeline. Use `--runs N` with choice 2 to create N independent world packages under one batch.

### Model Options

| Model | Description | Requirement |
|-------|-------------|-------------|
| `gpt-oss:20b` | **Default** – full-precision 20B model | ≥16 GB VRAM or ≥32 GB RAM |
| `gpt-oss:20b-q8` | 8-bit quantized – balanced | 16–24 GB VRAM |
| `gpt-oss:20b-q4` | 4-bit quantized – lowest memory | 8–16 GB VRAM |
| `gpt-oss:120b` | High-end – best quality | ≥60 GB VRAM |

The CLI will prompt you to choose a model before each run.

### Per-Run Output Directories

Every execution creates one timestamped world package under the configured output root so repeated
runs never overwrite each other:

```
output/
├── world_20260101_120000/   ← one world output
│   ├── input/
│   ├── intermediate/
│   ├── checkpoints/
│   └── final/
│       ├── novels/
│       └── references/
├── world_20260102_093000/   ← another world output
└── batch_20260103_150500/   ← a multi-run package
    ├── batch_manifest.json
    └── worlds/
```

For a reviewed example, generate into `output/`, inspect the complete `world_<id>/` package,
then give the selected package a human-readable name under `examples/`. See
[`examples/README.md`](examples/README.md).

### Python API

```python
from src import Pipeline

# Default model (gpt-oss:20b), auto-generated run_id
pipeline = Pipeline()

# Choose a quantized variant
pipeline = Pipeline(model="gpt-oss:20b-q4")

# Use the high-end model on a powerful machine
pipeline = Pipeline(model="gpt-oss:120b")

# Fix the run_id for reproducibility
pipeline = Pipeline(run_id="experiment_01")

print(pipeline.base_dir)  # ./output/world_YYYYMMDD_HHMMSS
```

### Output package

Each execution is kept together so it can be inspected or resumed:

```text
output/world_<run_id>/
├── run_manifest.json    # model, seed, configuration hashes, and status
├── input/               # copied or extracted user context
├── intermediate/        # YAML artifacts produced during the phases
├── checkpoints/         # resumable phase state
└── final/
    ├── novels/          # chapter_01.txt ...
    └── references/      # generated Markdown reference materials
```

For multiple runs, use `output/batch_<batch_id>/`. It contains a
`batch_manifest.json` and the individual worlds under `worlds/`. Generated `output/` content is
ignored by Git; reviewed packages belong under [`examples/`](examples/README.md).

---

## Running Tests

Install the lightweight development dependencies and run the default test suite. Tests that
require external services are marked as `integration` and excluded by default.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests/ -q
```
