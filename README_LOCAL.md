# 100 TIMES AI WORLD BUILDING - 利用ガイド

入力から世界設定資料を自律的に生成・検証・深化するエンジンの使い方です。仕組みは
[DESIGN_SPEC_LOCAL.md](DESIGN_SPEC_LOCAL.md)、状況は [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) を参照してください。

自動テストはフェイクバックエンドで実行します。実機ではOllamaの3モデルを同じ入力・seed 1・各12反復で比較しました。
gemma4:e4b は5件採用・地区まで・約14分、gpt-oss:20b は5件採用・世界のみ・約79分、
qwen3.8:27b は9件採用・施設まで・約116分でした。3モデルとも出力形式を守れずに失敗したタスクはありません。
入力・seed は各1つで、所要時間は他の処理との並行実行の影響も受けています。
条件と生成資料は [モデル比較の作例](examples/model_comparison/README.md) を参照してください。

## 1. 準備

```bash
# Ollama（既定のバックエンド）。モデル名は config/ollama_config.yaml の model.name
ollama pull <model.name>
ollama serve

pip install -r requirements-local.txt
python setup_check.py          # Anthropic を使う場合は --backend anthropic
```

`setup_check.py` は Python、必須ファイル、依存パッケージ、エンジン設定（探索設定・ドメインカタログ・プロンプト・
ステップ生成と決定的な検査の設定の読み込み）、バックエンド（Ollama サーバーと設定中のモデル、または Anthropic の認証とモデル）を確認します。

## 2. 入力

入力は自分で用意します（テキスト・YAML・JSON、形式は自由、画像は `--image`）。既定の入力はありません。
エンジンは原文を保存し、**明示された事項だけ**を引用付きで入力ブリーフに抽出します。
引用が原文の連続部分文字列かを検査します。後の段階で入力から導いた設定は、入力の明示事項と区別して由来を記録します。

### 生成と採用の流れ

入力ブリーフ → 世界の軸 → 世界の契約（独立した段階）→ 探索ループ → EntityBuilder → 採用 → 世界設定資料の出力、
の順に進みます。契約は暦・技術（能力・限界・単位）・社会を入力ブリーフと軸から生成し、グラフに保存します。
契約が構造化出力の試行上限内に準拠しなければ実行は失敗し、理由を記録します。

探索ループは未発達な箇所をフロンティアとして評価し、バンディット（UCB1 / Thompson）で「操作×対象」を選びます。
EntityBuilder は型・由来・名前・軸・説明・事実・関係を1項目ずつ生成・検証し、最後に全体を審査します。
事実には種類を指定し、測定値・固有名詞、続いてスケールに応じた物・手順・期間を1件ずつ生成します。
不合格のステップや審査で指摘された名前・説明・事実だけを作り直します。
`config/world/explore.yaml` の `build.max_step_attempts` は既定4、`build.review_rounds` は既定2です。

採用には [config/world/criteria.yaml](config/world/criteria.yaml) の8基準すべてへの合格が必要です。

| 基準 | 内容 |
|---|---|
| `grounded` | 入力事項か局所エンティティに由来し、導出理由がある |
| `consistent` | スキーマに準拠し、数値・自己参照・全体の矛盾がない |
| `objective` | 名前の文字が出力言語に合い、説明が中立・客観的 |
| `no_story` | 会話・個人の語り・物語の語り口を使わない |
| `specific` | 指定した種類の事実で、測定値・期間には必要な情報がある |
| `informative` | 入力・局所文脈との文字3-gramの重複率が0.6以下で、事実が他の事実にも情報を加える |
| `distinct` | 正規化した名前が既存の名前と異なり、同一エンティティの事実が重複しない |
| `fits_world` | 単位・その組合せ・暦の標識が契約に属し、全体が入力と世界に合う |

### 出力契約と修復

`config/schemas/` の JSON Schema を共通の `generate_structured` が検証し、プレースホルダー値と
スキーマの書き写しも検出します。形式が違う応答は元の出力から形式変換し、文字列・数値が元の出力に含まれるかを
決定的に検査します。変換で直らなければ、違反箇所と前回出力を提示して内容を書き直します。
真偽値を含むスキーマでは変換を省きます。

`config/ollama_config.yaml` の `engine.structured.max_attempts` は初回を含む内容生成の上限（既定3）、
`max_conversions` は1回の内容生成に対する形式変換の上限（既定2）です。
Ollama はデコード拘束ありで始め、解析不能なら拘束なしに切り替え、同じクライアントのバックエンド・モデルごとに記憶します。
Anthropic は tool use の拘束を維持します。

### 計測と選好ログ

`run_manifest.json` の `structured` はタスク別のハーネス呼び出し数・試行回数分布・失敗数・所要時間・方式、
プレースホルダーとスキーマ書き写しの検出数、変換の試行・成功・忠実性違反・スキーマ違反を記録します。
`build` はステップ別の生成呼び出し数（再試行・変換を含む）・試行回数・失敗数・基準別の不合格理由を記録します。
これらは `final/world_report.md` でも読めます。

`world/preferences.jsonl` はステップと事実の位置ごとに試行・出力・検査・合否を保存します。
`extract_preference_pairs` は同じ反復・ステップ・位置の合格出力と不合格出力を組にします。モデルの学習は実行しません。

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
入力・軸・契約の生成は探索予算の外で、構造化出力の試行上限で制限します。探索中の再試行・形式変換・審査は呼び出し予算に数えます。

| `stop_reason` | 意味 |
|---|---|
| `coverage_met` | 全軸が 1 件以上、指定スケールまで、バンディットの更新値の平均が目標以上、の被覆条件を満たした |
| `max_iterations` | 反復回数の上限 |
| `max_wall_seconds` | 経過時間の上限 |
| `max_generation_calls` | 生成呼び出し回数の上限 |
| `frontier_exhausted` | 次に行える操作が見つからない |
| `too_many_failures` | 例外が `budget.max_consecutive_failures` 回連続した（既定5） |

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
│   └── preferences.jsonl    # ステップの試行・出力・検査・合否と反復の結果
├── checkpoints/
├── quality_report.json/.md
└── final/
    ├── world.json
    ├── world_bible/         # README.md, scales/, entities/, glossary.md, timeline.md, documents.md
    └── world_report.md
```

- `final/world_bible/README.md`：概要、軸（根拠付き）、スケール別・用語集・年表・世界内文書への入口。
- `final/world_report.md`：停止理由、契約、被覆、スケール別件数、タスク別・ステップ別の計測。
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
| reward_distribution | 採用と作り直し回数から計算したバンディット更新値の分布（採否の基準ではない） |
| provenance | 由来のないエンティティ |
| duplicates | エンティティ内容・名前の完全 / 近似重複 |
| exploration | 実行状態、停止理由、反復数、採用された反復数 |

レポートには互換用の項目も残っています。現行エンジンの合否・失敗理由は `world_report.md` とステップの選好ログで確認します。

比較レポートは、世界ごとの実行条件・被覆・深度・バンディット更新値の平均・品質に加えて、世界同士の重複
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
| 生成が遅い | `--max-iterations` / `--max-calls` を小さくして計測を確認する |
| 世界が偏る | 品質レポートの axis_coverage / scale_depth を確認し、予算を増やして再開 |
| 停止後に続けたい | `--choice 2 --run-id <run_id>` に大きい予算を付ける |

## 9. 旧版

`legacy/` のノートブックは物語を生成していた旧パイプラインのものです。
閲覧用の `examples/` には旧版の出力と新エンジンのモデル比較を収録しています。新エンジンの仕組みは作例を参照しません。
