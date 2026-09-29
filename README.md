# 100 TIMES AI WORLD BUILDING

[![Tests](https://github.com/masa-san-jp/100-times-ai-world-building/actions/workflows/tests.yml/badge.svg)](https://github.com/masa-san-jp/100-times-ai-world-building/actions/workflows/tests.yml)

[日本語](#日本語) | [English](#english)

## 日本語

### 概要

このプロジェクトは、AI を使って奥行きのある物語世界を生成するための世界観構築ワークフローです。
オリジナルの**クラウド版ノートブック**（OpenAI / Anthropic API）と、創作インプットを外部 API に送らずに
Ollama 上で動く**ローカルパイプライン**を収録しています。

このプロジェクトは**反復的な探索**を前提に設計されています。コンテキストやモデルを変えて何度も実行し、
生成された世界はそれぞれ独立した出力パッケージとして保存されるため、過去の結果が上書きされることはありません。

パイプラインのバックエンドは選択式です。既定は Ollama で、Phase / チェックポイント / 検証のパイプラインを
変えずに、公式の Anthropic Python SDK 経由で Claude を使うこともできます。

### ドキュメント

| ファイル | 役割 | 言語 |
|---|---|---|
| [`README.md`](README.md) | 入口・概要・クイックスタート | 日本語 / 英語 |
| [`README_LOCAL.md`](README_LOCAL.md) | ローカル版ユーザーガイド | 日本語 |
| [`DESIGN_SPEC.md`](DESIGN_SPEC.md) | クラウド版（ノートブック）設計 | 日本語 |
| [`DESIGN_SPEC_LOCAL.md`](DESIGN_SPEC_LOCAL.md) | ローカル版設計 | 日本語 |
| [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) | 実装・検証状況と残タスク | 日本語 |
| [`examples/README.md`](examples/README.md) | サンプルの選定方針 | 日本語 |

### まず見る場所

`output/` は生成された世界パッケージの置き場です。

| パス | 意味 | 閲覧者向け |
|------|------|------------|
| [`examples/`](examples/README.md) | レビュー済みの生成物の見本（閲覧用。仕組みの入力ではない） | まずここから |
| `output/world_<run_id>/` | 入力・中間データ・チェックポイント・最終ファイルを含む 1 つの世界出力 | パッケージを 1 つ開く |
| `output/batch_<batch_id>/` | 複数の世界出力とバッチマニフェストを含む 1 つのバッチ | 複数回実行の作業時に開く |

`output/` はローカルで生成されるため、意図的に Git 管理から除外しています。単なる作業用の置き場ではなく、
各 `world_<run_id>/` が 1 回分の（完了または途中の）生成に対応し、その生成に属するファイルはすべてその中にあります。
現在検証済みの完全なサンプルは [`examples/README.md`](examples/README.md) に掲載しています。

ローカル実装の現状：Phase 0〜6 と、エンドツーエンドの完全なサンプル 1 件をローカルの Ollama 環境で検証済みです。
繰り返しのバッチ生成は実装済みですが、10 回実行のバッチは未検証です。所要時間は選択したモデルとハードウェアに大きく左右されます。

### 関連リポジトリ

以下のリポジトリが、100 TIMES AI の創作ワークフローを構成しています。

| リポジトリ | 用途 |
|------------|------|
| [100 TIMES AI HEROES](https://github.com/masa-san-jp/100-times-ai-heroes) | 願い・能力・役割を多数のキャラクター案と画像生成プロンプトに展開する。 |
| [100 TIMES AI HERO'S JOURNEY](https://github.com/masa-san-jp/100-times-ai-heros-journey) | 書き手の自己物語をヒーローズ・ジャーニーの構造、キャラクター、プロット、物語に変換する。 |
| [100 TIMES AI WORLD BUILDING](https://github.com/masa-san-jp/100-times-ai-world-building) | 本リポジトリ：物語を構造化された物語世界・プロット・章・参考資料に展開する。 |
| [100 TIMES AI MANGA DRAWING](https://github.com/masa-san-jp/100-times-ai-manga-drawing) | 生成 AI による漫画制作プロセスの高速化を記録・実験する。 |

各リポジトリは関連していますが、依存関係を共有する 1 つのパッケージではありません。
探索したい創作段階に合ったものから始めてください。

### クラウド版

- **セットアップ**：OpenAI または Anthropic の API キーを設定し、`20250601-100-TIMES-AI-WORLD-BUILDING-v1.2.ipynb` を実行します。
- **使い方**：ノートブックを開き、創作コンテキストを記入して、セルを順に実行します。

### ローカル版

> 詳細なドキュメント：[README_LOCAL.md](README_LOCAL.md)

#### クイックスタート

```bash
# 1. Ollama をインストールし、既定モデルを取得
ollama pull gpt-oss:20b

# 2. Ollama サーバーを起動
ollama serve

# 3. Python の依存関係をインストール
pip install -r requirements-local.txt

# 4. 対話型 CLI を実行
python example_run.py
```

入力は自分で用意します（テキスト・YAML・JSON、形式は自由）。既定の入力はなく、
`--context-file` を省くと対話メニューでファイルのパスを尋ねます。
対話なしで完全な世界出力を 1 つ作成する場合（`path/to/your_input.yaml` は自分の入力ファイルに置き換え）：

```bash
python example_run.py --choice 2 --yes \
  --context-file path/to/your_input.yaml \
  --model gpt-oss:20b \
  --output-dir output
```

サンプルの選定方針は [examples/README.md](examples/README.md) を参照してください。

#### Anthropic バックエンド

オプションのクラウド用依存関係をインストールし、Anthropic SDK の通常の環境変数 / プロファイル解決で
認証情報を渡します。API キーがこのリポジトリに保存されることはありません。

```bash
python -m pip install -r requirements-cloud.txt
python setup_check.py --backend anthropic
python example_run.py --choice 2 --yes --backend anthropic \
  --context-file path/to/your_input.yaml \
  --output-dir output
```

モデルの初期値は `anthropic.model` で設定します（サンプル設定では現在 `claude-opus-5`）。変更はそこで行うか
`--model` で指定します。`max_tokens`、`thinking`、`output_config`、フォールバック設定など、モデルに依存する
Messages API のパラメータは `anthropic.request_options` にまとめています。モデル世代を変えるときはこれらの設定を
見直してください。`setup_check.py --backend anthropic` は Models API から設定中モデルの性能上限を取得し、
`request_options.max_tokens` が過大な場合に警告します。CLI フラグなしで選択するには
`config/ollama_config.yaml` で `backend: anthropic` を設定します。

`--choice 1` は高速な Phase 1 の展開のみを実行します。`--choice 2` は Phase 0〜6 の完全なパイプラインを実行します。
choice 2 で `--runs N` を指定すると、1 つのバッチの下に N 個の独立した世界パッケージを作成します。

#### モデルの選択肢

| モデル | 説明 | 必要環境 |
|-------|------|----------|
| `gpt-oss:20b` | **既定** – フル精度の 20B モデル | VRAM 16 GB 以上 または RAM 32 GB 以上 |
| `gpt-oss:20b-q8` | 8bit 量子化 – バランス型 | VRAM 16〜24 GB |
| `gpt-oss:20b-q4` | 4bit 量子化 – 最小メモリ | VRAM 8〜16 GB |
| `gpt-oss:120b` | ハイエンド – 最高品質 | VRAM 60 GB 以上 |

CLI は実行のたびにモデルの選択を求めます。

#### 実行ごとの出力ディレクトリ

実行のたびに、設定された出力ルートの下にタイムスタンプ付きの世界パッケージが 1 つ作られるため、
繰り返し実行しても互いに上書きされません。

```
output/
├── world_<run_id>/           ← 1 つの世界出力
│   ├── input/
│   ├── intermediate/
│   ├── checkpoints/
│   └── final/
│       ├── novels/
│       └── references/
├── world_<run_id>/           ← 別の世界出力
└── batch_<batch_id>/         ← 複数回実行のパッケージ
    ├── batch_manifest.json
    └── worlds/
```

レビュー済みのサンプルを作るには、`output/` に生成し、完全な `world_<run_id>/` パッケージを確認してから、
選んだパッケージを `examples/` の下に分かりやすい名前で置きます。
[`examples/README.md`](examples/README.md) を参照してください。

#### Python API

```python
from src import Pipeline

# 既定モデル（gpt-oss:20b）、run_id は自動生成
pipeline = Pipeline()

# 量子化版を選ぶ
pipeline = Pipeline(model="gpt-oss:20b-q4")

# 高性能マシンでハイエンドモデルを使う
pipeline = Pipeline(model="gpt-oss:120b")

# 再現性のために run_id を固定する
pipeline = Pipeline(run_id="experiment_01")

print(pipeline.base_dir)  # ./output/world_YYYYMMDD_HHMMSS
```

#### 出力パッケージ

各実行の成果物はひとまとめに保存され、確認や再開ができます。

```text
output/world_<run_id>/
├── run_manifest.json    # モデル、シード、設定のハッシュ、ステータス
├── input/               # コピーまたは抽出したユーザーコンテキスト
├── intermediate/        # 各 Phase で生成された YAML
├── checkpoints/         # 再開可能な Phase の状態
└── final/
    ├── novels/          # chapter_01.txt ...
    └── references/      # 生成された Markdown の参考資料
```

複数回実行する場合は `output/batch_<batch_id>/` を使います。`batch_manifest.json` と、`worlds/` 以下の
個々の世界が含まれます。生成された `output/` の内容は Git で無視され、レビュー済みのパッケージは
[`examples/`](examples/README.md) に置きます。

### テストの実行

軽量な開発用依存関係をインストールし、既定のテストスイートを実行します。外部サービスを必要とする
テストは `integration` マークが付いており、既定では除外されます。

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

---

## English

### Overview

This project provides an AI-assisted world-building workflow for generating rich narrative universes.
It contains the original **cloud notebook** (OpenAI / Anthropic API) and a **local pipeline**
that runs through Ollama without sending your creative input to an external API.

The project is designed for **iterative exploration**: you run it multiple times with different contexts
or models, and each generated world is saved as a self-contained output package so previous results are
never overwritten.

The pipeline backend is selectable: Ollama is the default, and Claude can be used through the official
Anthropic Python SDK without changing the phase/checkpoint/validation pipeline.

### Documents

| File | Role | Language |
|---|---|---|
| [`README.md`](README.md) | Entry point, overview, and quick start | Japanese / English |
| [`README_LOCAL.md`](README_LOCAL.md) | Local version user guide | Japanese |
| [`DESIGN_SPEC.md`](DESIGN_SPEC.md) | Cloud version (notebook) design | Japanese |
| [`DESIGN_SPEC_LOCAL.md`](DESIGN_SPEC_LOCAL.md) | Local version design | Japanese |
| [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) | Implementation, verification status, and remaining tasks | Japanese |
| [`examples/README.md`](examples/README.md) | Example curation policy | Japanese |

### Where to look first

`output/` is the collection of generated world packages:

| Path | Meaning | For visitors |
|------|---------|--------------|
| [`examples/`](examples/README.md) | Reviewed output samples for reading (not inputs to the pipeline) | Start here |
| `output/world_<run_id>/` | One world output with its input, intermediate data, checkpoints, and final files | Open one package |
| `output/batch_<batch_id>/` | One batch containing several world outputs and its batch manifest | Open for multi-run work |

`output/` is intentionally excluded from Git because it is generated locally. It is not a flat
scratch dump: every `world_<run_id>/` is one complete or partial generation, and all files belonging
to that generation live inside it. The currently verified complete example is listed in
[`examples/README.md`](examples/README.md).

Current local implementation status: Phase 0–6 and one complete end-to-end example have been
verified on a local Ollama setup. Repeated batch generation is implemented, but the 10-run batch
has not been verified; its time depends heavily on the selected model and hardware.

### Related repositories

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

### Cloud Version

- **Setup**: Configure your OpenAI or Anthropic API key and run `20250601-100-TIMES-AI-WORLD-BUILDING-v1.2.ipynb`.
- **Usage**: Open the notebook, fill in your creative context, and execute cells in order.

---

### Local Version

> Full documentation: [README_LOCAL.md](README_LOCAL.md)

#### Quick Start

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

You supply your own input (text, YAML, or JSON; free form). There is no built-in default input;
without `--context-file` the interactive menu asks for a file path.
To create one complete world output non-interactively (replace `path/to/your_input.yaml` with your file):

```bash
python example_run.py --choice 2 --yes \
  --context-file path/to/your_input.yaml \
  --model gpt-oss:20b \
  --output-dir output
```

See [examples/README.md](examples/README.md) for the curation policy.

#### Anthropic backend

Install the optional cloud dependency and provide credentials through the Anthropic SDK's normal
environment/profile resolution. The API key is never stored in this repository.

```bash
python -m pip install -r requirements-cloud.txt
python setup_check.py --backend anthropic
python example_run.py --choice 2 --yes --backend anthropic \
  --context-file path/to/your_input.yaml \
  --output-dir output
```

The initial model value is configured as `anthropic.model` (currently `claude-opus-5` in the sample
configuration); change it there or with `--model`. Model-dependent Messages API parameters such as
`max_tokens`, `thinking`, `output_config`, and fallback options are kept in `anthropic.request_options`.
Review those settings when changing model generations. `setup_check.py --backend anthropic` retrieves
the configured model's capability limits through the Models API and warns about an excessive
`request_options.max_tokens` value. Set `backend: anthropic` in `config/ollama_config.yaml` to select
it without a CLI flag.

`--choice 1` runs only the fast Phase 1 expansion. `--choice 2` runs the complete Phase 0–6
pipeline. Use `--runs N` with choice 2 to create N independent world packages under one batch.

#### Model Options

| Model | Description | Requirement |
|-------|-------------|-------------|
| `gpt-oss:20b` | **Default** – full-precision 20B model | ≥16 GB VRAM or ≥32 GB RAM |
| `gpt-oss:20b-q8` | 8-bit quantized – balanced | 16–24 GB VRAM |
| `gpt-oss:20b-q4` | 4-bit quantized – lowest memory | 8–16 GB VRAM |
| `gpt-oss:120b` | High-end – best quality | ≥60 GB VRAM |

The CLI will prompt you to choose a model before each run.

#### Per-Run Output Directories

Every execution creates one timestamped world package under the configured output root so repeated
runs never overwrite each other:

```
output/
├── world_<run_id>/           ← one world output
│   ├── input/
│   ├── intermediate/
│   ├── checkpoints/
│   └── final/
│       ├── novels/
│       └── references/
├── world_<run_id>/           ← another world output
└── batch_<batch_id>/         ← a multi-run package
    ├── batch_manifest.json
    └── worlds/
```

For a reviewed example, generate into `output/`, inspect the complete `world_<run_id>/` package,
then give the selected package a human-readable name under `examples/`. See
[`examples/README.md`](examples/README.md).

#### Python API

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

#### Output package

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

### Running Tests

Install the lightweight development dependencies and run the default test suite. Tests that
require external services are marked as `integration` and excluded by default.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests/ -q
```
