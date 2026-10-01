# 100 TIMES AI WORLD BUILDING - 利用ガイド

入力から世界設定資料を自律的に生成・検証・深化するエンジンの使い方です。仕組みは
[DESIGN_SPEC_LOCAL.md](DESIGN_SPEC_LOCAL.md)、状況は [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) を参照してください。

> **検証状況**：新エンジンはフェイクバックエンドでのみテスト済みで、実機のローカルモデルでのエンドツーエンド
> 実行は未確認です。実モデルでの所要時間・品質は、最初は小さい予算（`--max-iterations 5` など）で確かめてください。

## 1. 準備

```bash
# Ollama（既定のバックエンド）。モデル名は config/ollama_config.yaml の model.name
ollama pull <model.name>
ollama serve

pip install -r requirements-local.txt
python setup_check.py          # Anthropic を使う場合は --backend anthropic
```

`setup_check.py` は Python、必須ファイル、依存パッケージ、エンジン設定（探索設定・ドメインカタログ・プロンプト・
報酬設定の読み込み）、バックエンド（Ollama サーバーと設定中のモデル、または Anthropic の認証とモデル）を確認します。

## 2. 入力

入力は自分で用意します（テキスト・YAML・JSON、形式は自由、画像は `--image`）。既定の入力はありません。
エンジンは原文を保存し、**明示された事項だけ**を引用付きで抽出します。入力にない設定は、
ジャンル・時代・舞台・技術・主人公像を含め、エンジン側からは持ち込みません。

## 3. 実行

```bash
# 対話なしで 1 つの世界を生成
python example_run.py --context-file path/to/your_input.yaml --yes

# 予算を指定
python example_run.py --context-file path/to/your_input.yaml --yes \
  --max-iterations 50 --max-minutes 90 --max-calls 600

# 画像も入力に使う（Ollama では models.vision のビジョンモデル）
python example_run.py --context-file path/to/your_input.yaml --yes --image path/to/picture.png

# 対話メニュー（1. 世界を生成 / 2. 再開 / 3. 終了）
python example_run.py
```

| 引数 | 説明 |
|---|---|
| `--context-file` | 入力ファイル（必須。対話メニューではパスを尋ねる） |
| `--yes` | 確認プロンプトを省く。`--context-file` か `--yes` があれば、メニューを出さず「世界を生成」を実行 |
| `--choice 1|2|3` | 1=生成、2=再開、3=終了 |
| `--max-iterations` / `--max-minutes` / `--max-calls` | 予算（反復回数 / 分 / 生成呼び出し回数） |
| `--seed` | 乱数 seed（操作と対象の選択を再現可能にする） |
| `--backend ollama|anthropic` | バックエンド（既定は設定値、なければ Ollama） |
| `--model` | 生成モデル（既定は `model.name` / `anthropic.model`） |
| `--vision-model` | `--image` を読むモデル（Ollama。既定は `models.vision`） |
| `--output-dir` | 世界パッケージの置き場（既定は `output.base_dir`） |
| `--run-id` | パッケージ ID。再開時に指定 |
| `--runs N` | 同じ入力から N 個の独立した世界を作る（バッチ） |
| `--config` | 設定ファイル（既定は `config/ollama_config.yaml`） |

旧版の `--structured-model` / `--story-model` / `--reference-model` / `--extract-context` は廃止しました。
新エンジンのモデルの役割は「生成」と「画像読み取り」の 2 つだけで、`--model` と `--vision-model` が対応します。
入力の受け入れは常に行われます。

### 予算と停止理由

予算の既定は `config/world/explore.yaml` の `budget`、`config/ollama_config.yaml` の `engine.explore` で上書きできます。
停止すると `run_manifest.json` の `stop_reason` に理由が残ります。

| `stop_reason` | 意味 |
|---|---|
| `coverage_met` | 全軸が 1 件以上、指定スケールまで、平均報酬が目標以上、の被覆条件を満たした |
| `max_iterations` | 反復回数の上限 |
| `max_wall_seconds` | 経過時間の上限 |
| `max_generation_calls` | 生成呼び出し回数の上限 |
| `frontier_exhausted` | 次に行える操作が見つからない |

### 再開

```bash
python example_run.py --choice 2 --run-id <run_id> --max-iterations 100
```

チェックポイント（グラフ・バンディット・乱数状態・選好ログの位置）から続行します。再開時は、そのパッケージを作った
バックエンドとモデルをそのまま使います（`--model` で明示的に変えた場合を除く）。同じ `run_id` に別の入力や別の
seed を渡すとエラーになります。

### バッチ（独立した N 個の世界）

```bash
python example_run.py --context-file path/to/your_input.yaml --yes --runs 5 --seed 7
```

`output/batch_<batch_id>/` に `batch_manifest.json`、`worlds/world_<run_id>/`（各自の seed・チェックポイント・
マニフェスト）、`comparison.md` が作られます。`--seed` を固定すると各世界の seed が決定的に導かれます。
1 つの世界が失敗しても残りは続行されます（`completed_with_errors`）。

## 4. 出力

```text
output/world_<run_id>/
├── run_manifest.json        # エンジン設定・予算・seed・バックエンド/モデル・停止理由・状態
├── input/                   # 原文、画像、input_brief.json
├── world/
│   ├── world_axes.json      # 世界の軸と重み
│   ├── graph.json           # エンティティグラフ
│   ├── contrasts.json       # 「入力なし」の対照（凡庸さの検証用）
│   └── preferences.jsonl    # 候補・採点・採否・書き直しの選好ログ
├── checkpoints/
├── quality_report.json/.md
└── final/
    ├── world.json
    ├── world_bible/         # README.md, scales/, entities/, glossary.md, timeline.md, documents.md
    └── world_report.md
```

- `final/world_bible/README.md`：概要、軸（根拠付き）、スケール別・用語集・年表・世界内文書への入口。
- `final/world_report.md`：停止理由、被覆、スケール別件数、報酬分布とヒストグラム、凡庸さで落とした候補の例。
- `final/world.json`：軸・グラフ・実行サマリを含む機械可読の世界モデル。
- `run_manifest.json`：`engine_config`（探索・オペレータ・生成の既定値）、`budget`（要求値と有効値）、`run_seed`、
  `backend` / `model` / `models`、`stop_reason`、`iterations`、`counters`、設定ファイルのハッシュを記録します。

## 5. 品質・比較レポート

```bash
python -m src.quality output/world_<run_id> [--json] [--strict]
python -m src.compare output/world_a output/world_b [--out comparison.md]
python -m src.compare --batch output/batch_<batch_id>
```

品質レポート（`quality_report.json/.md`、実行後に自動生成）は次を見ます。しきい値は `config/world/quality.yaml` です。

| チェック | 見るもの |
|---|---|
| graph | グラフの整合性（参照・スケール・親子）、エンティティ数 |
| axis_coverage | 軸ごとのエンティティ数、重み比と実際の比、未被覆の軸 |
| scale_depth | スケール別件数、最深スケール、目標深度に届いていないスケール |
| reward_distribution | 報酬の平均・最小・最大、ヒストグラム、検証器別平均、低報酬・未採点 |
| genericity | 凡庸さスコア、基準未満のエンティティ、凡庸さで却下された候補数 |
| provenance | 由来のないエンティティ |
| duplicates | エンティティ内容・名前の完全 / 近似重複 |
| exploration | 実行状態、停止理由、反復数、採用された反復数 |

比較レポートは、世界ごとの実行条件・被覆・深度・平均報酬・平均凡庸さ・品質に加えて、世界同士の重複
（同名率、近似エンティティ率、共通の固有名詞率、軸の類似度）を示します。重複が高い組は `REPEATS` で示します。
率が低いほど、同じ入力から大きく分岐した世界です。

## 6. バックエンド

- **Ollama（既定）**：`config/ollama_config.yaml` の `server` と `model.name`。`generation`（`max_tokens`・`num_ctx`・
  `think`・`temperature`）は全生成呼び出しの既定値です（`null` は送らない）。
- **Anthropic**：`--backend anthropic`、またはそのファイルの `backend: anthropic`。モデルは `anthropic.model`、
  モデル依存のリクエスト設定は `anthropic.request_options`。認証は SDK が環境変数 / プロファイルから解決します。

モデル名・モデル固有のパラメータはコードに固定せず、設定ファイルと `--model` で扱います。

## 7. Python から使う

```python
from src import Pipeline, run_batch

pipeline = Pipeline(seed=7, budget={"max_iterations": 50})
result = pipeline.run(open("path/to/your_input.yaml", encoding="utf-8").read())
print(result.stop_reason, result.iterations, pipeline.package_dir)

pipeline.resume()                                   # 同じパッケージを続行
run_batch(text, runs=3, seed=1, budget={"max_iterations": 20})
```

`Pipeline` はエンジン（`src/world/explore.py:run_world_engine`）を包む薄いラッパーで、バックエンド/モデルの解決、
パッケージ、マニフェスト、品質レポートだけを担当します。テストでは `backend=` にフェイクバックエンドを渡せます。

## 8. トラブルシューティング

| 症状 | 対処 |
|---|---|
| `No model configured` | `model.name`（Ollama）または `anthropic.model` を設定、または `--model` |
| `Prerequisites not met` | `python setup_check.py` で Ollama サーバー・モデルを確認 |
| `Input differs from the one stored` | 既存の `run_id` に別の入力は使えません。新しい `run_id` で |
| `Seed ... does not match` | 再開は保存済みの seed を使います。`--seed` を外す |
| 生成が遅い | `--max-iterations` / `--max-calls` を小さくし、`config/world/explore.yaml` の `generation.candidates` を減らす |
| 世界が偏る | 品質レポートの axis_coverage / scale_depth を確認し、予算を増やして再開 |
| 停止後に続けたい | `--choice 2 --run-id <run_id>` に大きい予算を付ける |

## 9. 旧版

`legacy/` のノートブックと `examples/` の作例は、物語を生成していた旧パイプラインのものです。新エンジンとは別物で、
新エンジンの仕組みはそれらを参照しません。
