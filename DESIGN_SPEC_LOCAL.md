# 100 TIMES AI WORLD BUILDING — ローカル版設計仕様書

**バージョン**: v2.1-local
**更新日**: 2026-08-29
**著者**: masa-jp-art
**文書ステータス**: 初版
**対象**: Ollama + gpt-oss:20b によるローカル実行版

---

## 目次

1. [プロジェクト概要](#1-プロジェクト概要)
2. [v1.2からの主要変更点](#2-v12からの主要変更点)
3. [システムアーキテクチャ](#3-システムアーキテクチャ)
4. [技術スタック](#4-技術スタック)
5. [データフロー](#5-データフロー)
6. [パイプライン詳細設計](#6-パイプライン詳細設計)
7. [API設計](#7-api設計)
8. [データ構造](#8-データ構造)
9. [出力仕様](#9-出力仕様)
10. [パフォーマンス最適化](#10-パフォーマンス最適化)
11. [制約事項・前提条件](#11-制約事項前提条件)
12. [移行ガイド](#12-移行ガイド)
13. [将来の拡張性](#13-将来の拡張性)

---

## 1. プロジェクト概要

### 1.1 目的

「100 TIMES AI WORLD BUILDING」のローカル版は、v1.2のクラウドベース実装を完全にローカル環境で動作させることを目的とする。Ollama上でgpt-oss:20bモデルを使用し、外部APIへの依存を排除することで以下を実現する：

- **完全なプライバシー保護**: データが外部サーバーに送信されない
- **コストゼロ運用**: API利用料金が発生しない
- **オフライン動作**: インターネット接続不要（初回モデルダウンロード後）
- **カスタマイズ性**: モデルパラメータの細かい調整が可能

### 1.2 v1.2との互換性

| 項目 | v1.2 (クラウド版) | v2.1 (ローカル版) |
|------|------------------|------------------|
| 主要機能 | 100倍拡張、小説生成、資料集生成 | 同一 |
| データフロー | 同一パイプライン | 同一パイプライン |
| 出力品質 | GPT-4 + Claude 3.7 | gpt-oss:20b (品質トレードオフあり) |
| API呼び出し回数 | 74回 | 91回 (すべてローカル) |
| 実行環境 | Google Colab推奨 | ローカルJupyter + Ollama |

---

## 2. v1.2からの主要変更点

### 2.1 アーキテクチャ変更

```
[v1.2]
Jupyter Notebook → OpenAI API (クラウド)
                 → Anthropic API (クラウド)

[v2.1]
Jupyter Notebook → Ollama (localhost:11434)
                 → gpt-oss:20b (ローカルモデル)
```

### 2.2 削除される機能

- OpenAI API連携
- Anthropic Claude API連携
- 外部カスタムGPTによるコンテクスト抽出（代替実装で対応）

### 2.3 追加される機能

- Ollamaサーバー自動起動確認機能
- モデルダウンロード進捗表示
- ローカル実行に最適化されたプロンプトテンプレート
- バッチ処理オプション（メモリ管理のため）
- 中間データ自動保存機能（長時間実行に対応）

---

## 3. システムアーキテクチャ

### 3.1 全体構成

```
┌─────────────────────────────────────────────────────────┐
│                   ローカル実行環境                        │
│                                                          │
│  ┌──────────┐    ┌──────────────────────────────────┐    │
│  │  ユーザー  │───▶│       メインノートブック            │    │
│  │  入力     │    │  (local-v2.0.ipynb)               │    │
│  └──────────┘    └────────┬──────────────────────────┘    │
│                           │                               │
│                           │ HTTP (localhost:11434)        │
│                           │                               │
│                  ┌────────▼──────────────────────┐        │
│                  │     Ollama Server              │        │
│                  │                                │        │
│                  │  ┌──────────────────────┐     │        │
│                  │  │   gpt-oss:20b        │     │        │
│                  │  │   (20B parameters)    │     │        │
│                  │  │                       │     │        │
│                  │  │ • JSON構造化          │     │        │
│                  │  │ • 長文生成            │     │        │
│                  │  │ • キーワード抽出      │     │        │
│                  │  │ • 小説執筆            │     │        │
│                  │  │ • 資料集作成          │     │        │
│                  │  └──────────────────────┘     │        │
│                  └────────────────────────────────┘        │
│                                                          │
│  ┌──────────────────────────────────────────────────┐    │
│  │          成果物パッケージ永続化                      │    │
│  │   ./output/world_<run_id>/                         │    │
│  │   ├── intermediate/*.yaml                          │    │
│  │   ├── checkpoints/*.json                           │    │
│  │   └── final/{novels,references}/                   │    │
│  └──────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### 3.2 ディレクトリ構成

```
100-times-ai-world-building/
├── local-v2.0.ipynb                      # メインノートブック
├── DESIGN_SPEC_LOCAL.md                  # 本設計仕様書
├── README_LOCAL.md                       # ローカル版README
├── requirements.txt                      # 実行時の最小依存
├── requirements-dev.txt                  # テスト・flake8を含む開発用
├── requirements-local.txt                # CLI・ノートブックを含むローカル用
├── config/
│   ├── ollama_config.yaml               # Ollama設定
│   └── prompts/                          # プロンプトテンプレート集
│       ├── expansion.yaml
│       ├── world_building.yaml
│       ├── plot_generation.yaml
│       └── story_generation.yaml
├── src/
│   ├── __init__.py
│   ├── ollama_client.py                 # Ollama APIクライアント
│   ├── pipeline.py                       # パイプライン制御
│   ├── utils.py                          # ユーティリティ関数
│   └── checkpoint_manager.py            # チェックポイント管理
├── output/
│   ├── world_YYYYMMDD_HHMMSS/            # 1つの世界成果物
│   │   ├── input/                        # 入力コンテキスト
│   │   ├── intermediate/                 # 途中生成物
│   │   ├── checkpoints/                  # 再開用状態
│   │   └── final/                        # 最終成果物
│   │       ├── novels/
│   │       └── references/
│   └── batch_YYYYMMDD_HHMMSS/            # 複数世界の成果物
│       ├── batch_manifest.json
│       └── worlds/
└── tests/
    ├── test_ollama_client.py
    └── test_pipeline.py
```

---

## 4. 技術スタック

### 4.1 言語・フレームワーク

| 技術要素 | 採用技術 | 用途 |
|----------|----------|------|
| プログラミング言語 | Python 3.10+ | ワークフロー制御 |
| 実行環境 | Jupyter Notebook / JupyterLab | インタラクティブ実行 |
| AIモデル | gpt-oss:20b (via Ollama) | すべてのAI処理 |
| モデルサーバー | Ollama v0.1.0+ | ローカルLLMサーバー |

### 4.2 ライブラリ

| ライブラリ | バージョン | 用途 |
|------------|-----------|------|
| `ollama` | 0.3.0+ | Ollama Python クライアント |
| `requests` | 2.31.0+ | HTTP通信（フォールバック用） |
| `pyyaml` | 6.0+ | YAML パース・出力 |
| `json` | 標準ライブラリ | JSON パース |
| `tqdm` | 4.66.0+ | プログレスバー表示 |
| `psutil` | 5.9.0+ | システムリソース監視 |
| `pathlib` | 標準ライブラリ | ファイルパス操作 |

### 4.3 gpt-oss:20bモデルスペック

| 項目 | 仕様 |
|------|------|
| モデル名 | gpt-oss:20b |
| パラメータ数 | 20B (200億) |
| コンテキスト長 | 32,768トークン (現行設定) |
| 出力形式 | JSON対応、Markdown対応 |
| 推奨VRAM | 16GB以上 (量子化版: 12GB) |
| 推奨RAM | 32GB以上 |
| 言語サポート | 多言語（日本語対応） |

モデル選択肢は [`README_LOCAL.md`](README_LOCAL.md) の「モデル選択肢」を参照してください。

---

## 5. データフロー

### 5.1 パイプライン全体フロー

v1.2と同一のパイプライン構造を維持しますが、すべてのAPI呼び出しがOllamaに向けられます。

```
[Phase 0: 前処理]  ── gpt-oss:20b (ローカル) ──
  ユーザー入力（対話形式）
    └─▶ ユーザーコンテクスト (user_context)

[Phase 1: 100倍拡張]  ── gpt-oss:20b ──
  user_context
    ├─▶ desire_list       （100個の願望）
    ├─▶ ability_list      （100個の能力）
    ├─▶ role_list          （100個の役割）
    ├─▶ plottype_list      （10個のプロットタイプ）
    └─▶ plottype           （選択されたプロットタイプ）

[Phase 2: キャラクター生成]  ── gpt-oss:20b ──
  user_context + plottype + desire_list + ability_list + role_list
    └─▶ characters_list   （4人の主要登場人物）

[Phase 3: 世界構築]  ── gpt-oss:20b ──  ※累積的にコンテクスト投入
  [events → observation → interpretation → media →
   important_past_events → social_structure → living_environment →
   social_groups → people_list → future_scenarios]

[Phase 4: プロット生成]  ── gpt-oss:20b ──
  全世界設定 + user_context + plottype + characters_list
    └─▶ plot → [plot_1...10 + plot_keywords_1...10 + plot_reference_1...10]

[Phase 5: 小説生成]  ── gpt-oss:20b ──
  characters_list + plot_n + plot_reference_n  (n=1..10)
    └─▶ story_1 ～ story_10  （全10章の小説本文）

[Phase 6: 設定資料集生成]  ── gpt-oss:20b ──
  各世界設定データ
    └─▶ reference_*（17種類の資料集）
```

### 5.2 API呼び出し回数とチェックポイント

| フェーズ | 呼び出し回数 | チェックポイント |
|----------|-------------|-----------------|
| Phase 0 | 1回 | user_context保存 |
| Phase 1 | 17回（100件リストを20件ずつ分割） | desire_list, ability_list, role_list, plottype_list, plottype保存 |
| Phase 2 | 1回 | characters_list保存 |
| Phase 3 | 14回（people_listを20件ずつ分割） | 各世界設定データ保存 |
| Phase 4 | 31回 | plot, plot_1...10, keywords, references保存 |
| Phase 5 | 10回 | story_1...10保存（章ごと） |
| Phase 6 | 17回 | reference_*保存（資料ごと） |
| **合計** | **91回** | **各フェーズ終了時に自動保存** |

Phase 0〜6と完全作例1件は実機確認済みです。10回バッチは未検証です。

---

## 6. パイプライン詳細設計

### 6.1 Phase 0: ユーザーコンテクスト抽出（ローカル実装）

**実行環境**: Jupyter NotebookまたはCLI（Ollama経由）

v1.2では外部ChatGPTカスタムGPTを使用していましたが、ローカル版ではテキスト入力を
ローカルモデルで構造化し、画像入力時はOllamaのvision対応モデルで観察結果を抽出します。

| 項目 | 内容 |
|------|------|
| 入力方式 | CLI/APIのテキスト、YAML/JSONファイル、任意のローカル画像 |
| 処理 | テキストまたは画像をローカルOllamaモデルが構造化 |
| 質問数 | 対話入力または事前に構造化したコンテクストを指定 |
| 出力 | YAML形式のユーザーコンテクスト |
| 画像対応 | Ollamaのvision対応モデルを指定した場合に対応 |

**実装例**:
```python
def extract_user_context():
    """対話形式でユーザーコンテクストを抽出"""
    questions = generate_questions()  # gpt-oss:20bが質問を生成
    answers = []
    for q in questions:
        print(f"\nQ: {q}")
        answer = input("A: ")
        answers.append({"question": q, "answer": answer})

    # 回答からコンテクストを構造化
    user_context = summarize_context(answers)
    return user_context
```

### 6.2 Phase 1〜6: 既存パイプラインのOllama移行

v1.2のすべてのフェーズを以下の方針で移行：

1. **OpenAI o4-mini呼び出し → gpt-oss:20b呼び出しに置き換え**
2. **Claude呼び出し → gpt-oss:20b呼び出しに置き換え**
3. **プロンプトの最適化**: gpt-oss:20bの特性に合わせて調整
4. **チャンク分割**: 長いコンテクストは分割して処理

#### プロンプト最適化の指針

| v1.2プロンプト | ローカル版での調整 |
|---------------|-----------------|
| システムプロンプト + ユーザープロンプト | 単一プロンプトに統合（Ollamaはシステムプロンプトのサポートが限定的） |
| 長いコンテクスト | 32,768トークン設定を使い、people_listは分割、章参照では除外 |
| JSON出力指示 | より明示的な指示と例示を追加 |
| 日本語出力 | プロンプト内で明示的に「日本語で」を強調 |

---

## 7. API設計

### 7.1 Ollamaクライアント基本関数

#### `ollama_generate(prompt, model="gpt-oss:20b", format="json", temperature=0.7) → str`

Ollama APIを使用した汎用生成関数。

```python
import ollama

def ollama_generate(
    prompt: str,
    model: str = "gpt-oss:20b",
    format: str = "json",  # "json" or "" (フリーテキスト)
    temperature: float = 0.7,
    max_tokens: int = 4096
) -> str:
    """
    Ollama経由でgpt-oss:20bにリクエストを送信

    Args:
        prompt: 入力プロンプト
        model: モデル名
        format: 出力形式（"json"または空文字列）
        temperature: 生成のランダム性（0.0〜2.0）
        max_tokens: 最大トークン数

    Returns:
        生成されたテキスト
    """
    try:
        response = ollama.generate(
            model=model,
            prompt=prompt,
            format=format,
            options={
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        )
        return response['response']
    except Exception as e:
        print(f"Error: {e}")
        return f"ERROR: {str(e)}"
```

### 7.2 ヘルパー関数仕様

#### `local_json_generate(prompt) → dict`

JSON形式でデータを生成する関数。

```python
import json
import yaml

def local_json_generate(prompt: str) -> str:
    """
    JSON形式でデータを生成し、YAMLに変換

    Args:
        prompt: 入力プロンプト（JSON出力を指示する内容）

    Returns:
        YAML形式の文字列
    """
    # JSON出力を明示
    full_prompt = f"""{prompt}

重要: 必ず有効なJSON形式で出力してください。出力例:
{{
  "items": ["item1", "item2"]
}}
"""

    response = ollama_generate(
        prompt=full_prompt,
        format="json",
        temperature=0.7
    )

    try:
        data = json.loads(response)
        yaml_output = yaml.dump(data, allow_unicode=True, default_flow_style=False)
        return yaml_output
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        return f"ERROR: Invalid JSON\n{response}"
```

#### `local_text_generate(prompt, temperature=1.0) → str`

長文生成用関数（小説、資料集）。

```python
def local_text_generate(
    prompt: str,
    temperature: float = 1.0,
    max_tokens: int = 4096
) -> str:
    """
    長文テキストを生成（小説本文、設定資料集用）

    Args:
        prompt: 入力プロンプト
        temperature: 創造性パラメータ（高いほど多様な出力）
        max_tokens: 最大トークン数

    Returns:
        生成されたテキスト
    """
    return ollama_generate(
        prompt=prompt,
        format="",  # フリーテキスト
        temperature=temperature,
        max_tokens=max_tokens
    )
```

#### `check_ollama_server() → bool`

Ollamaサーバーの起動確認。

```python
import requests

def check_ollama_server(host: str = "http://localhost:11434") -> bool:
    """
    Ollamaサーバーが起動しているか確認

    Returns:
        True: サーバー起動中
        False: サーバー未起動
    """
    try:
        response = requests.get(f"{host}/api/tags")
        return response.status_code == 200
    except requests.exceptions.ConnectionError:
        return False

def ensure_model_available(model: str = "gpt-oss:20b") -> bool:
    """
    モデルがダウンロード済みか確認、未ダウンロードならpull

    Returns:
        True: モデル利用可能
        False: モデル取得失敗
    """
    try:
        # モデル一覧を取得
        models = ollama.list()
        model_names = [m['name'] for m in models['models']]

        if model not in model_names:
            print(f"モデル {model} をダウンロード中...")
            ollama.pull(model)
            print(f"モデル {model} のダウンロードが完了しました")

        return True
    except Exception as e:
        print(f"モデル確認エラー: {e}")
        return False
```

### 7.3 チェックポイント管理

#### `save_checkpoint(phase_name, data) → None`

```python
import json
from pathlib import Path
from datetime import datetime

def save_checkpoint(phase_name: str, data: dict) -> None:
    """
    チェックポイントデータを保存

    Args:
        phase_name: フェーズ名（例: "phase1_expansion"）
        data: 保存するデータ（辞書形式）
    """
    checkpoint_dir = Path("./output/world_<run_id>/checkpoints")
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = checkpoint_dir / f"{phase_name}_{timestamp}.json"

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✓ チェックポイント保存: {filename}")

def load_latest_checkpoint(phase_name: str) -> dict:
    """
    最新のチェックポイントを読み込み

    Args:
        phase_name: フェーズ名

    Returns:
        チェックポイントデータ（存在しない場合は空辞書）
    """
    checkpoint_dir = Path("./output/world_<run_id>/checkpoints")
    pattern = f"{phase_name}_*.json"
    files = sorted(checkpoint_dir.glob(pattern), reverse=True)

    if files:
        with open(files[0], 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}
```

---

## 8. データ構造

v1.2と同一のデータ構造を維持します。詳細は`DESIGN_SPEC.md`の「8. データ構造」を参照。

### 8.1 中間データファイル管理

ローカル版では、すべての中間データをファイルシステムに保存します。

```
output/world_<run_id>/
├── input/
│   └── user_context.yaml
├── intermediate/
│   ├── 01_desire_list.yaml
│   ├── 02_ability_list.yaml
│   ├── 03_role_list.yaml
│   ├── 04_plottype_list.yaml
│   ├── 05_plottype.yaml
│   ├── 06_characters_list.yaml
│   ├── 10_events.yaml
│   ├── 11_observation.yaml
│   ├── 12_interpretation.yaml
│   ├── 13_media.yaml
│   ├── 14_important_past_events.yaml
│   ├── 15_social_structure.yaml
│   ├── 16_living_environment.yaml
│   ├── 17_social_groups.yaml
│   ├── 18_people_list.yaml
│   ├── 19_future_scenarios.yaml
│   ├── 20_plot.yaml
│   ├── 21_plot_1.yaml ... 30_plot_10.yaml
│   ├── 31_plot_keywords_1.yaml ... 40_plot_keywords_10.yaml
│   └── 41_plot_reference_1.yaml ... 50_plot_reference_10.yaml
└── final/
    ├── novels/
    │   ├── chapter_01.txt
    │   ├── chapter_02.txt
    │   ...
    │   └── chapter_10.txt
    └── references/
        ├── characters.md
        ├── plot.md
        ├── user_context.md
        ...
        └── plottype_list.md
```

---

## 9. 出力仕様

### 9.1 小説出力

| 項目 | 仕様 | v1.2との差異 |
|------|------|-------------|
| 構成 | 全10章 | 同一 |
| 各章の最大トークン数 | 4,096トークン | v1.2は16,000（品質トレードオフ） |
| 言語 | 日本語 | 同一 |
| 文体 | 重厚長大な文学的表現 | 同一（モデル能力に依存） |
| 出力形式 | テキストファイル（.txt） | v1.2はノートブック内表示 |

### 9.2 設定資料集出力

| 項目 | 仕様 | v1.2との差異 |
|------|------|-------------|
| 形式 | Markdown | 同一 |
| 資料数 | 17種類 | 同一 |
| 各資料の最大トークン数 | 4,096トークン | v1.2は16,000 |
| 内容 | 抽象的に解釈・補足された構造化資料 | 同一 |
| 出力先 | output/world_<run_id>/final/references/*.md | v1.2はノートブック内 |

### 9.3 品質トレードオフ

gpt-oss:20bは高性能なオープンソースモデルですが、GPT-4やClaude 3.7と比較すると以下のトレードオフがあります：

| 評価軸 | v1.2 (GPT-4 + Claude) | v2.1 (gpt-oss:20b) | 備考 |
|--------|----------------------|-------------------|------|
| JSON構造化精度 | ★★★★★ | ★★★★☆ | 追加の後処理で補完可能 |
| 長文生成品質 | ★★★★★ | ★★★★☆ | 文学的表現力はやや劣る |
| 一貫性維持 | ★★★★★ | ★★★☆☆ | チェックポイント機能で補完 |
| 処理速度 | ★★★★☆（ネットワーク遅延） | ★★★☆☆（ローカル計算負荷） | ハードウェアに依存 |
| コスト | ★☆☆☆☆（高額） | ★★★★★（ゼロ） | - |
| プライバシー | ★★☆☆☆（データ外部送信） | ★★★★★（完全ローカル） | - |

---

## 10. パフォーマンス最適化

### 10.1 ハードウェア推奨スペック

| 構成 | 最小要件 | 推奨要件 | 理想構成 |
|------|---------|---------|---------|
| CPU | 4コア | 8コア | 16コア以上 |
| RAM | 16GB | 32GB | 64GB以上 |
| GPU | なし（CPU推論可） | NVIDIA RTX 3060 (12GB VRAM) | NVIDIA RTX 4090 (24GB VRAM) |
| ストレージ | 50GB空き容量 | 100GB SSD | 500GB NVMe SSD |

### 10.2 推論高速化戦略

#### 10.2.1 GPU推論の活用

```bash
# Ollama起動時にGPUを有効化（自動検出）
ollama serve

# 手動でGPU設定を確認
ollama list
```

#### 10.2.2 量子化モデルの使用

より軽量なモデルバリアントを使用：

```bash
# 4-bit量子化版（VRAM使用量: 約10GB）
ollama pull gpt-oss:20b-q4

# 8-bit量子化版（VRAM使用量: 約14GB）
ollama pull gpt-oss:20b-q8
```

ノートブック内で切り替え：

```python
MODEL_NAME = "gpt-oss:20b-q4"  # 軽量版
# MODEL_NAME = "gpt-oss:20b"   # フル精度版
```

#### 10.2.3 バッチ処理

独立したAPI呼び出しを並列化：

```python
import concurrent.futures

def batch_generate(prompts: list, max_workers: int = 3) -> list:
    """
    複数プロンプトを並列処理

    Args:
        prompts: プロンプトのリスト
        max_workers: 並列実行数（メモリに応じて調整）

    Returns:
        生成結果のリスト
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(ollama_generate, p) for p in prompts]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    return results
```

#### 10.2.4 コンテキストキャッシング

同じコンテキストを再利用する場合に有効：

```python
class ContextCache:
    def __init__(self):
        self.cache = {}

    def get_or_generate(self, key: str, prompt_fn):
        if key not in self.cache:
            self.cache[key] = prompt_fn()
        return self.cache[key]

# 使用例
cache = ContextCache()
base_context = cache.get_or_generate(
    "base_world_setting",
    lambda: build_world_context()
)
```

### 10.3 実行時間の目安

| フェーズ | API呼び出し | 推定時間（GPU） | 推定時間（CPU） |
|----------|------------|---------------|---------------|
| Phase 0 | 1回 | 1〜2分 | 3〜5分 |
| Phase 1 | 17回（100件リストを20件ずつ分割） | 15〜35分 | 30〜90分 |
| Phase 2 | 1回 | 1〜2分 | 3〜5分 |
| Phase 3 | 14回（people_list分割を含む） | 10〜20分 | 30〜50分 |
| Phase 4 | 31回 | 30〜60分 | 1.5〜3時間 |
| Phase 5 | 10回 | 20〜40分 | 1〜2時間 |
| Phase 6 | 17回 | 15〜30分 | 45分〜1.5時間 |
| **合計** | **91回** | **2〜4時間** | **5〜10時間** |

Phase 1だけの目安は15〜90分、完全パイプラインの目安は2〜10時間です。

---

## 11. 制約事項・前提条件

### 11.1 技術的制約

| 制約 | 詳細 | 対策 |
|------|------|------|
| コンテキスト長制限 | 32,768トークン（モデル上限内で設定） | people_listを分割し、章参照では不要な100人データを除外 |
| 生成トークン数制限 | 4,096トークン/リクエスト（v1.2は16,000） | 章を複数回に分けて生成する選択肢を提供 |
| メモリ使用量 | 20Bモデルは大量のRAM/VRAMを消費 | 量子化モデルの使用、バッチサイズの調整 |
| 処理速度 | ローカル推論のため、クラウドAPIより遅い | GPU利用、量子化、並列処理 |
| 出力品質の変動 | オープンソースモデルのため品質にばらつき | temperature調整、リトライ機構 |

### 11.2 機能的制約

| 制約 | 詳細 | 対策 |
|------|------|------|
| 画像入力 | gpt-oss:20bはテキストのみ | `llava:latest`などvision対応モデルを`--vision-model`で指定 |
| 長文出力 | ローカルモデルの1回の出力上限 | 上限到達時に続きを自動生成して結合 |
| リアルタイム性 | 長時間実行のため中断が困難 | リクエスト単位のチェックポイントと実行ID指定で再開 |
| エラーハンドリング | ローカル環境のため外部サービスのようなSLA保証なし | リトライ機構、詳細なエラーログ |

### 11.3 前提条件

- **OS**: Linux / macOS / Windows (WSL2推奨)
- **Ollama**: v0.1.0以上がインストール済み
- **Python**: 3.10以上
- **ディスク空き容量**: 50GB以上（モデルファイル + 出力データ）
- **インターネット接続**: 初回のモデルダウンロード時のみ必要

---

## 12. 移行ガイド

### 12.1 v1.2からv2.0への移行手順

#### Step 1: Ollamaのインストール

```bash
# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh

# Windows (PowerShell)
winget install Ollama.Ollama
```

#### Step 2: gpt-oss:20bモデルのダウンロード

```bash
ollama pull gpt-oss:20b

# または量子化版（推奨）
ollama pull gpt-oss:20b-q4
```

#### Step 3: Python環境のセットアップ

```bash
# 仮想環境作成
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# ローカル版（CLI・ノートブック・テスト）
pip install -r requirements-local.txt

# 実行時だけの場合
# pip install -r requirements.txt

# テストとflake8だけの場合
# pip install -r requirements-dev.txt
```

#### Step 4: 既存データの移行

v1.2で生成した中間データがある場合：

```python
# v1.2のグローバル変数を読み込み
import pickle

with open('v1.2_workspace.pkl', 'rb') as f:
    old_data = pickle.load(f)

# v2.0形式で保存
save_checkpoint('migration', old_data)
```

### 12.2 互換性マトリクス

| v1.2の機能 | v2.0での対応 | 備考 |
|----------|------------|------|
| OpenAI API呼び出し | Ollama API呼び出しに置き換え | プロンプト調整が必要 |
| Claude API呼び出し | Ollama API呼び出しに置き換え | プロンプト調整が必要 |
| カスタムGPT連携 | ノートブック内対話機能で代替 | 一部機能制限あり |
| グローバル変数管理 | ファイルベース管理に移行 | より堅牢 |
| エラー時の継続実行 | チェックポイントからの再開 | 改善 |

---

## 13. 将来の拡張性

### 13.1 短期的改善（v2.1〜v2.3）

| 改善項目 | 内容 |
|---------|------|
| Web UI化 | Streamlit/Gradioによるインタラクティブインターフェース |
| プロンプトテンプレート管理 | YAML設定ファイルでの外部化、バージョン管理 |
| 出力品質評価 | 生成結果の自動評価スコアリング |
| リアルタイム進捗表示 | トークン生成のストリーミング表示 |

### 13.2 中期的改善（v2.4〜v2.6）

| 改善項目 | 内容 |
|---------|------|
| 高度な画像前処理 | 複数画像の比較や画像内テキスト抽出の強化 |
| 分散処理 | 複数マシンでの並列実行（Ray, Dask等） |
| ファインチューニング | ユーザー独自のスタイルで追加学習 |
| データベース統合 | SQLite/PostgreSQLでの中間データ管理 |
| API化 | FastAPIによるRESTful API提供 |

### 13.3 長期的ビジョン（v3.0〜）

| 改善項目 | 内容 |
|---------|------|
| 完全オープンソース化 | プロンプトテンプレート、ノートブックの公開リポジトリ化 |
| コミュニティモデル | ユーザーが学習したモデルの共有プラットフォーム |
| クロスプラットフォーム | デスクトップアプリ（Electron）、モバイルアプリ |
| リアルタイムコラボレーション | 複数ユーザーでの共同世界構築 |
| プラグインシステム | サードパーティ拡張機能の対応 |

---

## 付録

### A. トラブルシューティング

#### A.1 Ollamaサーバーが起動しない

**症状**: `Connection refused` エラー

**解決策**:
```bash
# サーバーを手動起動
ollama serve

# バックグラウンドで起動（Linux/macOS）
nohup ollama serve &

# Windows: サービスとして起動
# Ollamaインストーラーで自動設定済み
```

#### A.2 メモリ不足エラー

**症状**: `CUDA out of memory` または システムフリーズ

**解決策**:
```python
# 量子化モデルに切り替え
MODEL_NAME = "gpt-oss:20b-q4"

# または、バッチサイズを削減
MAX_WORKERS = 1  # 並列実行を無効化
```

#### A.3 JSON出力が不正

**症状**: `JSONDecodeError`

**解決策**:
```python
# リトライ機構の実装
def robust_json_generate(prompt, max_retries=3):
    for i in range(max_retries):
        try:
            result = local_json_generate(prompt)
            return result
        except json.JSONDecodeError:
            print(f"リトライ {i+1}/{max_retries}")
            continue
    return "ERROR: JSON生成失敗"
```

### B. パフォーマンスベンチマーク

#### B.1 テスト環境

| 構成 | スペック |
|------|---------|
| CPU | AMD Ryzen 9 5950X (16コア) |
| RAM | 64GB DDR4-3600 |
| GPU | NVIDIA RTX 3090 (24GB VRAM) |
| ストレージ | 1TB NVMe SSD |
| OS | Ubuntu 22.04 LTS |

#### B.2 実測値

| モデル | Phase 1-6 合計時間 | 章生成速度 | メモリ使用量 |
|--------|-------------------|-----------|------------|
| gpt-oss:20b (fp16) | 2時間45分 | 約15分/章 | 22GB VRAM |
| gpt-oss:20b-q8 | 2時間10分 | 約12分/章 | 16GB VRAM |
| gpt-oss:20b-q4 | 1時間50分 | 約10分/章 | 12GB VRAM |

### C. 用語集

| 用語 | 説明 |
|------|------|
| Ollama | ローカルでLLMを実行するためのオープンソースツール |
| gpt-oss | GPTアーキテクチャを基にしたオープンソースモデル |
| 量子化 | モデルの重みを低精度で表現し、メモリ使用量を削減する技術 |
| コンテキスト長 | モデルが一度に処理できる入力トークン数 |
| VRAM | GPU上のビデオメモリ（モデル推論に使用） |

---

**文書履歴**:
- v2.0-local (2026-02-14): 初版作成
- v2.1-local (2026-08-29): 現行の出力構成、依存関係、検証状況を反映

**関連ドキュメント**:
- `DESIGN_SPEC.md` - v1.2（クラウド版）設計仕様書
- `README_LOCAL.md` - ローカル版ユーザーガイド
- `ollama_config.yaml` - Ollama設定ファイル

---

*本文書は「100 TIMES AI WORLD BUILDING v1.2」をOllama + gpt-oss:20bでローカル実行するための設計仕様書です。*
