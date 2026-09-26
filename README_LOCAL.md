# 100 TIMES AI WORLD BUILDING — Local Version

このファイルは、Ollamaを使って本リポジトリをローカル実行するためのガイドです。
最初に読む人は、まず[完全作例](examples/neo_tokyo_complete/)を確認し、その後このページの
クイックスタートを実行してください。

## これは何か

入力したナラティブ（テーマ、舞台、主人公のアイデアなど）をもとに、Phase 0〜6を順番に実行します。

0. **Phase 0**: ナラティブの保存・必要に応じた構造化
1. **Phase 1**: 願望・能力・役割・プロット形式の拡張
2. **Phase 2**: キャラクター生成
3. **Phase 3**: 物語世界の構築
4. **Phase 4**: 10章分のプロット生成
5. **Phase 5**: 各章の小説本文生成
6. **Phase 6**: 設定資料集の生成

生成中の入力・途中生成物・チェックポイント・最終成果物は、1回の実行ごとに
`output/world_<run_id>/` へまとめて保存されます。複数回実行した場合は
`output/batch_<batch_id>/worlds/` に世界ごとのパッケージが作られます。

## 重要な前提

- 生成処理はOllamaへ送るため、生成時に入力や出力をOpenAIなどの外部APIへ送信しません。
- 初回のPython依存関係とOllamaモデルの取得にはインターネット接続が必要です。
- Phase 1だけの目安は15〜90分、完全パイプラインの目安は2〜10時間です（モデルとマシンに依存します）。
- `--choice 1` はPhase 1だけの短い確認用です。最終成果物まで作る場合は `--choice 2` を使います。
- 生成結果の品質、速度、完全な再現性は、Ollamaのモデル、モデルのバージョン、ハードウェアに依存します。
- Phase 0〜6と完全作例1件は実機確認済みです。10回バッチは未検証です。
- バックエンドの既定値はOllamaです。同じパイプラインを任意依存のAnthropic SDK経由でClaudeでも実行できます。

## 必要なもの

- Python 3.10以上
- [Ollama](https://ollama.com/)
- 生成に使用するOllamaモデル
- 完全版を実行する場合は、モデルと出力を保存する十分なRAM・ストレージ

既定モデルは `gpt-oss:20b` です。利用できるモデルはマシンによって異なるため、
`ollama list` で確認してください。別のOllamaモデルも `--model` で指定できます。

### モデル選択肢

| モデル | 説明 | 要件の目安 |
|---|---|---|
| `gpt-oss:20b` | **既定**。フル精度20Bモデル | VRAM 16GB以上またはRAM 32GB以上 |
| `gpt-oss:20b-q8` | 8-bit量子化。品質とメモリのバランス | VRAM 16〜24GB |
| `gpt-oss:20b-q4` | 4-bit量子化。最も軽量 | VRAM 8〜16GB |
| `gpt-oss:120b` | 高品質向けの大規模モデル | VRAM 60GB以上 |

## クイックスタート

### 1. Ollamaを用意する

Ollamaをインストールして、モデルを取得します。

```bash
ollama pull gpt-oss:20b
```

別ターミナルでサーバーを起動します。

```bash
ollama serve
```

### 2. Python環境を用意する

リポジトリのルートで実行します。

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -r requirements-local.txt
```

`requirements-local.txt` には、CLIの実行、ノートブック、テストに必要な依存関係をまとめています。
実行時だけなら `requirements.txt`、テストとflake8だけなら `requirements-dev.txt`、
ローカル版を一通り使う場合は `requirements-local.txt` を使います。

セットアップ状態を確認します。

```bash
python setup_check.py
```

### 3. まずPhase 1だけ実行する

短い動作確認では、100倍拡張までを実行します。

```bash
python example_run.py --choice 1 \
  --context-file examples/neo_tokyo_complete/input/user_context.yaml \
  --model gpt-oss:20b-q4 \
  --output-dir output
```

### 4. 完全パイプラインを実行する

Phase 0〜6を最後まで実行し、10章の本文と設定資料を生成します。

```bash
python example_run.py --choice 2 --yes \
  --context-file examples/neo_tokyo_complete/input/user_context.yaml \
  --model gpt-oss:20b \
  --output-dir output
```

完了後、表示された `output/world_<run_id>/` を開いて成果物を確認してください。

### Anthropicバックエンド（任意）

Ollamaを使わずClaudeで同じPhase 0〜6、検証、チェックポイント、品質レポートを実行する場合は、
任意依存を追加してからSDKの通常の認証設定を使います。APIキーはコードや設定ファイルに書きません。

```bash
python -m pip install -r requirements-cloud.txt
python setup_check.py --backend anthropic  # SDK/認証とモデル情報を確認
python example_run.py --choice 2 --yes --backend anthropic \
  --context-file examples/neo_tokyo_complete/input/user_context.yaml \
  --output-dir output
```

モデルは `config/ollama_config.yaml` の `anthropic.model`、またはCLIの `--model` で指定します。
サンプル設定の初期値は `claude-opus-5` ですが、モデルの世代を替えるときは
`anthropic.request_options` の `max_tokens`、`thinking`、`output_config`、フォールバック設定も
見直してください。`setup_check.py --backend anthropic` は Models API からモデルの存在、
`max_input_tokens`、`max_tokens` を確認し、設定値が上限を超える場合に警告します。
CLIを使わず設定だけで選ぶ場合は `backend: anthropic` にします。Ollama利用者は
`requirements-cloud.txt` をインストールする必要はありません。

## 入力の渡し方

`--context-file` には、YAML、JSON、またはプレーンテキストを指定できます。
YAML/JSONの構造をそのまま使う場合は通常 `--extract-context` は不要です。

```bash
# 構造化済みYAMLを使う
python example_run.py --choice 2 --context-file ./my_context.yaml --model gpt-oss:20b

# プレーンテキストをローカルモデルで構造化してから使う
python example_run.py --choice 2 --context-file ./idea.txt --extract-context
```

画像をコンテクストに含める場合は、ローカルのvisionモデルを指定します。

```bash
ollama pull llava:latest
python example_run.py --choice 2 \
  --context-file ./idea.txt \
  --image ./reference.png \
  --vision-model llava:latest
```

画像も外部サービスには送信されません。

## 繰り返し生成する

同じ入力から独立した世界を複数作るには `--runs` を指定します。各世界は別ディレクトリに保存され、
前の実行を上書きしません。

```bash
python example_run.py --choice 2 --runs 10 --yes \
  --context-file ./my_context.yaml \
  --model gpt-oss:20b-q4 \
  --output-dir output
```

バッチ全体のseedを固定すると、各周回に異なるseedを決定的に割り当てられます。
ただし、モデルやOllamaのバージョンが変われば完全一致は保証されません。

```bash
python example_run.py --choice 2 --runs 10 --seed 20260827 --yes \
  --context-file ./my_context.yaml \
  --model gpt-oss:20b-q4 \
  --output-dir output
```

`--seed` を省略すると、実行ごとに新しいseedが生成され、`run_manifest.json` に保存されます。

## 中断した実行を再開する

各フェーズのチェックポイントは実行パッケージ内に保存されます。再開時は、元の実行IDと出力ルートを指定します。
モデルを指定しなければ、保存済みマニフェストのモデル構成が優先されます。

```bash
python example_run.py --choice 3 \
  --run-id 20260829_123456_789012 \
  --output-dir output
```

`--run-id` はディレクトリ名 `world_<run_id>` の `world_` を除いた部分です。
バッチ内の世界も `--run-id` で指定できます。

## 出力構造

### 1回の実行

```text
output/world_<run_id>/
├── run_manifest.json       # モデル、seed、設定ハッシュ、実行状態
├── input/                  # 入力コンテクスト
├── intermediate/           # Phase 1〜4の途中生成物（YAML）
├── checkpoints/            # 再開用のフェーズ状態（JSON）
└── final/
    ├── novels/             # chapter_01.txt 〜 chapter_10.txt
    └── references/         # 設定資料（Markdown）
```

### 複数回の実行

```text
output/batch_<batch_id>/
├── batch_manifest.json     # バッチ全体のseed、件数、状態
└── worlds/
    ├── world_<run_id>/     # 1周目
    └── world_<run_id>/     # 2周目以降
```

`output/` は生成用で、Git管理対象外です。確認済みの作例だけを
[`examples/`](examples/README.md) に、同じパッケージ構造で保存します。

## Pythonから使う

```python
from src import Pipeline, run_batch

pipeline = Pipeline(
    model="gpt-oss:20b-q4",
    output_dir="output",
    seed=12345,
)
result = pipeline.run_full_pipeline("""
context:
  theme: "海底都市と地上文明の対立"
  mood: "静かな緊張感"
  setting: "23世紀の太平洋"
""")
print(pipeline.base_dir)
```

複数周回をコードから実行する場合:

```python
summary = run_batch(
    user_context="context:\n  theme: 海底都市と地上文明の対立\n",
    runs=10,
    seed=20260827,
    pipeline_kwargs={"model": "gpt-oss:20b-q4", "output_dir": "output"},
)
print(summary["summary_path"])
```

## モデルをフェーズごとに分ける

通常は `--model` 1つで全フェーズを実行できます。役割ごとにモデルを分ける場合は、次のオプションを使います。

```bash
python example_run.py --choice 2 \
  --structured-model gpt-oss:20b-q4 \
  --story-model gpt-oss:20b \
  --reference-model gpt-oss:20b-q4
```

- `--structured-model`: JSONや世界設定を生成するフェーズ
- `--story-model`: 小説本文を生成するフェーズ
- `--reference-model`: Markdownの設定資料を生成するフェーズ
- `--vision-model`: 画像コンテクストの解析

## 設定とプロンプト

- `config/ollama_config.yaml`: Ollama接続、モデル、生成パラメータ、出力先、チェックポイント設定
- `config/prompts/`: 各フェーズのプロンプトテンプレート
- `src/pipeline.py`: Phase 0〜6の実行制御
- `src/batch.py`: 複数周回の実行
- `src/validation.py`: 生成物の件数・構造検証
- `src/run_manifest.py`: seed、モデル、設定ハッシュ、状態の記録
- `src/checkpoint_manager.py`: 中断・再開用状態の保存

構造化出力はローカルモデルが1回で100件を返しきれない場合に備え、複数の小さなリクエストへ分割します。
この挙動は `config/ollama_config.yaml` の `items_per_request` などで調整できます。

## トラブルシューティング

### `Connection refused` が出る

Ollamaサーバーが起動しているか確認します。

```bash
ollama serve
ollama list
```

別ターミナルを占有したくない場合は、ログをファイルに保存してバックグラウンド起動できます。

```bash
nohup ollama serve > ollama.log 2>&1 &
```

### モデルが見つからない

モデル名はローカルに存在する名前と完全に一致させます。

```bash
ollama list
ollama pull gpt-oss:20b-q4
```

### メモリ不足・処理が遅い

量子化モデルを選び、同時実行数を増やさずに実行してください。完全版は大量の構造化出力と10章の本文を生成するため、
CPUのみの環境では長時間かかります。

同時実行数は `config/ollama_config.yaml` の次の設定で確認できます。

```yaml
performance:
  max_parallel_requests: 1
```

### JSONの解析に失敗する

構造化フェーズには再試行とJSON互換フォールバックがあります。それでも失敗する場合は、
より大きいモデルを使うか、`config/ollama_config.yaml` で温度を下げてください。

長時間実行のログは、実行方法に応じて `logs/full_pipeline.log` または
`logs/batch_pipeline.log` を確認してください。

## ノートブック版

- `20250601-100-TIMES-AI-WORLD-BUILDING-v1.2.ipynb`: OpenAI / Anthropic APIを使う元のクラウド版
- `local-v2.0.ipynb`: Ollamaを使うローカル版

`local-v2.0.ipynb` は、ローカル版を対話的に試すためのノートブックです。工程をセル単位で確認できます。
再実行、チェックポイント再開、複数周回、
成果物管理を行う場合は `example_run.py` またはPython APIを推奨します。

## 関連リポジトリ

100 TIMES AIシリーズの工程別リポジトリです。これらは関連プロジェクトですが、共通のインストールパッケージではありません。

- [100 TIMES AI HEROES](https://github.com/masa-san-jp/100-times-ai-heroes)：願望・能力・役割などを組み合わせ、キャラクター設定と画像生成用プロンプトを大量に作るプロジェクト。
- [100 TIMES AI HERO'S JOURNEY](https://github.com/masa-san-jp/100-times-ai-heros-journey)：作家の自己ナラティブから、ヒーローズ・ジャーニー形式のキャラクター、プロット、物語を生成するプロジェクト。
- [100 TIMES AI WORLD BUILDING](https://github.com/masa-san-jp/100-times-ai-world-building)：本リポジトリ。キャラクターや物語の材料を、設定資料・世界観・プロット・章本文へ展開するプロジェクト。
- [100 TIMES AI MANGA DRAWING](https://github.com/masa-san-jp/100-times-ai-manga-drawing)：生成AIを使ったマンガ制作工程の分析・構造化と高速化の試みをまとめた制作・実験リポジトリ。

## テスト

```bash
pytest tests/ -v
```

## 利用条件

このリポジトリには現在 `LICENSE` ファイルがありません。コードや生成物の利用・再配布条件は、
作者に確認してください。Ollamaや使用するモデルには、それぞれのライセンス・利用条件が適用されます。

---

**Author**: masa-san-jp
**Last Updated**: 2026-08-29
