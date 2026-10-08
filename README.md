# 100 TIMES AI WORLD BUILDING

[![Tests](https://github.com/masa-san-jp/100-times-ai-world-building/actions/workflows/tests.yml/badge.svg)](https://github.com/masa-san-jp/100-times-ai-world-building/actions/workflows/tests.yml)

[日本語](#日本語) | [English](#english)

## 日本語

### 概要

利用者の入力（テキスト・YAML・JSON など、形式は自由）だけを起点に、**物語制作の土台になる世界設定資料**を、
人の介入なしに生成・検証・深化し続けるエンジンです。物語（主人公・プロット・章・小説本文）は生成しません。
成果物は世界そのものの資料です。

世界設定資料が物語の説得力を支えるために、次の 4 つを同時に満たすことを目指します。

| 性質 | 意味 | 仕組み |
|---|---|---|
| 広がり | 世界が主題の周辺だけで終わらず、周縁・他者・無関係な領域まで存在する | 入力から決める世界の軸と重み、視点・周縁の展開 |
| 深み | 各要素に「なぜそうなっているか」の因果と歴史の地層がある | 因果・歴史オペレータ、由来（provenance）の記録 |
| スケール感 | 世界から地域・集落・地区・施設・細部までの階層 | エンティティグラフのスケール階層、ズーム展開 |
| ディテール | 固有名詞・数値・制度・物・慣習など、場面に置ける具体物 | 具体性の検証、世界内文書（条文・記録・掲示など） |

あわせて、客観的な説明文（百科事典・設定解説の調子で、構造・歴史・因果を中立に記述する層）を必ず出力します。

#### 現在の検証状況

自動テストは決定的なフェイクバックエンドで実行します。別途、Ollama 上の3モデルを同じ入力・seed 1・各12反復で実機比較しました。

| モデル | 採用 / 不採用 | 到達スケール | 構造化出力の呼び出し | 所要時間 |
|---|---|---|---|---|
| gemma4:e4b | 5 / 7 | 地区 | 168 | 約14分 |
| gpt-oss:20b | 5 / 7 | 世界 | 149 | 約79分 |
| qwen3.8:27b | 9 / 3 | 施設 | 183 | 約116分 |

3モデルとも出力形式を守れずに失敗したタスクはありません。主な不合格理由は、入力・周辺の文の言い換えや、契約にない単位でした。
入力1つ・seed 1つの結果で、所要時間には他の処理との並行実行の影響があります。
条件・結果・生成資料は [モデル比較の作例](examples/model_comparison/README.md)、実装状況は
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) を参照してください。

### ドキュメント

| ファイル | 役割 | 言語 |
|---|---|---|
| [`README.md`](README.md) | 入口・概要・クイックスタート | 日本語 / 英語 |
| [`README_LOCAL.md`](README_LOCAL.md) | 利用ガイド（CLI・予算・出力・レポート） | 日本語 |
| [`DESIGN_SPEC_LOCAL.md`](DESIGN_SPEC_LOCAL.md) | エンジンの設計 | 日本語 |
| [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) | 実装・検証状況と残タスク | 日本語 |
| [`DESIGN_SPEC.md`](DESIGN_SPEC.md) | 旧クラウド版ノートブックの設計（旧版） | 日本語 |
| [`examples/README.md`](examples/README.md) | 新エンジンのモデル比較と旧版の作例（閲覧用） | 日本語 |

### 仕組み

```text
入力 → 入力ブリーフ → 世界の軸 → 世界の契約（独立した段階）
                                      ↓
                探索ループ：フロンティア評価 → バンディットで「操作×対象」を選択
                                      ↓
                EntityBuilder：型 → 由来 → 名前 → 軸 → 説明
                               → 事実（種類を指定して1件ずつ）→ 関係 → 審査
                各項目を生成・検証し、不合格の項目だけを作り直す
                                      ↓
                全基準に合格 → グラフへ採用 → 次の探索へ
                                      ↓
                世界設定資料（Markdown）＋ world.json ＋ 計測・選好ログ
```

- **入力ブリーフ**：原文を保存し、明示事項だけを引用付きで抽出します（`input/input_brief.json`）。引用が原文の
  連続部分文字列であることを検査します。画像（`--image`）の観察結果も入力に使えます。
- **世界の軸**：`config/world/domains.yaml` の領域カタログを入力に照らして重み付けします。
  入力が触れていない領域にも下限の重みを残します（`world/world_axes.json`）。
- **世界の契約**：軸の後・探索の前に、入力ブリーフと軸から暦・技術（能力・限界・単位）・社会を独立して生成します。
  原本はグラフの `world_contract`、結果と試行回数は `contract_stage` と manifest の `world_contract` に保存します。
  `engine.structured.max_attempts`（初回込み、既定3回）で準拠しなければ実行は失敗します。再開では保存済みの結果を使います。
- **探索ループ**：空・未展開・因果なし・事実不足・軸の不足などをフロンティアとして評価し、UCB1 / Thompson の
  バンディットで「操作×対象」を選びます。操作は `premise` / `expand` / `zoom` / `cause` / `perspective` / `history` / `document`。
  採用結果と作り直しの回数からバンディットを更新します。
- **EntityBuilder**（`src/world/builder.py`）：1つのエンティティを項目ごとに生成します。ID・スケール・親・操作に対応する
  関係はコードが決めます。型が操作で一意なら生成を省きます。事実は測定値・固有名詞を先に、物・手順・期間を
  スケールに応じて追加し、指定した種類で1件ずつ検証します。最後に組み立てた全体を審査し、指摘された名前・説明・事実だけを再生成します。
  ステップは既定4試行まで、全体審査後の修正は既定2巡までです（`config/world/explore.yaml` の `build`）。
- **エンティティグラフ**：`world → region → settlement → district → site → detail` の階層で、型・名前・軸・説明・事実・
  関係・由来を保存します（`world/graph.json`）。生成には件数と文字数を制限した局所文脈を渡します。
- **出力契約**：`config/schemas/` の JSON Schema を `generate_structured` が検証します。プレースホルダー値と
  スキーマの書き写しも検出します。形式が違う場合は元の出力から形式を変換し、文字列・数値が元の出力にあるかを
  決定的に検査します。変換で直らなければ違反箇所と前回出力を示して内容を書き直します。
  真偽値を含むスキーマでは形式変換を省きます。Ollama でデコード拘束中の応答が解析不能なら拘束を外し、
  同じクライアントのバックエンド・モデルの組ごとに可否を記憶します。Anthropic は tool use の拘束を維持します。
- **計測**：manifest の `structured` はタスク別のハーネス呼び出し数・準拠までの試行回数・失敗・所要時間・方式、
  プレースホルダーとスキーマ書き写しの検出数、変換の試行・成功・忠実性違反・スキーマ違反を記録します。
  `build` はステップ別の生成呼び出し数（再試行・変換を含む）・試行回数・失敗・基準別の不合格理由を記録し、`final/world_report.md` にも表示します。
- **選好ログ**：`world/preferences.jsonl` にステップ・事実の位置・試行・出力・検査結果・合否と反復の結果を保存します。
  `extract_preference_pairs` は同じ反復・ステップ・位置の合格出力と不合格出力を組にします。モデルの学習は実行しません。
- **予算と停止**：反復回数・経過時間・生成呼び出し回数、被覆条件、フロンティアの枯渇、連続した例外で停止します。
  入力・軸・契約の生成は探索の呼び出し予算の外で、構造化出力の試行上限で制限します。チェックポイントから再開できます。

採用基準は [config/world/criteria.yaml](config/world/criteria.yaml) の8基準です。各項目の検査と全体審査がすべて合格した場合だけ採用します。

| 基準 | 検査する内容 |
|---|---|
| `grounded` | 入力事項か局所エンティティに由来し、導出には理由がある |
| `consistent` | スキーマに準拠し、数値の矛盾・自己参照・全体の矛盾がない |
| `objective` | 名前が出力言語の文字を使い、説明が中立・客観的 |
| `no_story` | 説明に会話・個人の語り・物語の語り口を使わない |
| `specific` | 事実が指定された種類を満たし、測定値・期間に必要な情報がある |
| `informative` | 説明・事実の文字3-gramの重複率が入力・局所文脈に対して0.6以下で、事実が他の事実にも情報を加える |
| `distinct` | 正規化した名前が既存の名前と異なり、同一エンティティの事実が重複しない |
| `fits_world` | 単位・その組合せ・暦の標識が契約に属し、全体が入力と世界に合う |

#### 用語を読むための例

架空の入力「二つの集落が一つの水源を共有している」を考えると、「世界の軸」は水の配分・制度・暮らしなどの調査領域、「エンティティ」は集落や配分を担う組織、「ズーム」は集落から地区・施設・細部へ下る操作を指します。「由来」は入力の明示事項と、そこから生成した設定の関係です。例えば未記載の配分制度を生成した場合、入力に書かれた事実とは区別して扱います。

これは[オペレータ](src/world/operators.py)とグラフの用語を説明する例で、既定の入力・固定ジャンル・実測出力ではありません。基準への合格は作品としての完成や実世界の事実性を保証しません。

### クイックスタート

```bash
# 1. Ollama をインストールし、使うモデルを取得（モデル名は config/ollama_config.yaml の model.name）
ollama pull <model.name>

# 2. Ollama サーバーを起動
ollama serve

# 3. Python の依存関係をインストール
pip install -r requirements-local.txt

# 4. 前提を確認
python setup_check.py

# 5. 自分の入力ファイルで世界を生成（対話なし）
python example_run.py --context-file path/to/your_input.yaml --yes
```

入力は自分で用意します（テキスト・YAML・JSON、形式は自由）。既定の入力はなく、`--context-file` も `--yes` も
省くと対話メニュー（世界を生成 / 再開 / 終了）でファイルのパスを尋ねます。

#### 予算（長さの上限）

```bash
python example_run.py --context-file path/to/your_input.yaml --yes \
  --max-iterations 50 --max-minutes 90 --max-calls 600
```

| 引数 | 意味 | 既定 |
|---|---|---|
| `--max-iterations` | 探索の反復回数 | `config/world/explore.yaml` の `budget` |
| `--max-minutes` | 探索の経過時間（分） | 無制限 |
| `--max-calls` | モデルの生成呼び出し回数 | 無制限 |

そのほかの主な引数：`--model`（生成モデル）、`--vision-model`（`--image` 用）、`--backend ollama|anthropic`、
`--seed`、`--output-dir`、`--runs N`（同じ入力から N 個の独立した世界を作る）、`--run-id`、`--choice 2`（再開）。
モデル名は設定ファイルまたは `--model` で渡し、コードには固定しません。

```bash
# 途中から再開（run-id は output/world_<run_id>/ の <run_id>）
python example_run.py --choice 2 --run-id <run_id> --max-iterations 100

# 同じ入力から 5 つの独立した世界を作り、比較レポートも作る
python example_run.py --context-file path/to/your_input.yaml --yes --runs 5 --seed 7
```

#### Anthropic バックエンド

```bash
python -m pip install -r requirements-cloud.txt
python setup_check.py --backend anthropic
python example_run.py --yes --backend anthropic --context-file path/to/your_input.yaml
```

認証は Anthropic SDK の通常の環境変数 / プロファイルで解決します（API キーはリポジトリに保存されません）。モデルは
`anthropic.model`（または `--model`）で指定し、モデル依存のリクエスト設定は `anthropic.request_options` にあります。

#### 出力パッケージ

```text
output/world_<run_id>/
├── run_manifest.json        # エンジン設定・予算・seed・バックエンド/モデル・停止理由・状態
├── input/                   # 原文、画像、input_brief.json
├── world/                   # world_axes.json, graph.json, preferences.jsonl
├── checkpoints/             # 再開用
├── quality_report.json/.md  # 品質レポート
└── final/
    ├── world.json           # 機械可読の世界モデル（軸・グラフ・実行サマリ）
    ├── world_bible/         # 世界設定資料（README.md, scales/, entities/, glossary.md, timeline.md, documents.md）
    └── world_report.md      # 探索結果（被覆・スケール別件数・タスク別とステップ別の計測）
```

`--runs N` では `output/batch_<batch_id>/` に `batch_manifest.json`、`worlds/` 以下の独立した世界、`comparison.md` が
作られます。品質・比較は単体でも実行できます。

```bash
python -m src.quality output/world_<run_id>
python -m src.compare output/world_a output/world_b      # または --batch output/batch_<batch_id>
```

品質レポートはグラフの整合性、軸の被覆、スケールの深さ、由来、重複、探索の状態を確認できます。
比較レポートは世界同士の重複
（同名・近似エンティティ・共通の固有名詞）を示します。

#### Python API

```python
from src import Pipeline

pipeline = Pipeline(seed=7, budget={"max_iterations": 50})
result = pipeline.run(open("path/to/your_input.yaml", encoding="utf-8").read())
print(result.stop_reason, pipeline.package_dir)
```

### 旧版について

- 旧クラウド版ノートブック（`legacy/20250601-100-TIMES-AI-WORLD-BUILDING-v1.2.ipynb`）とローカル版ノートブック
  （`legacy/local-v2.0.ipynb`）は [`legacy/`](legacy/) に移しました（物語を生成する**旧版**です。
  新エンジンとは別物で、保守していません）。
- [`examples/`](examples/README.md) は閲覧用の作例です。新エンジンのモデル比較と旧パイプラインの出力を含み、仕組みからは参照しません。
- 旧パイプラインの 4 人の役割キャラクター、プロット・章・小説本文、固定スキーマの世界項目は撤去しました。

### 関連リポジトリ

| リポジトリ | 用途 |
|------------|------|
| [100 TIMES AI HEROES](https://github.com/masa-san-jp/100-times-ai-heroes) | 願い・能力・役割を多数のキャラクター案と画像生成プロンプトに展開する。 |
| [100 TIMES AI HERO'S JOURNEY](https://github.com/masa-san-jp/100-times-ai-heros-journey) | 書き手の自己物語をヒーローズ・ジャーニーの構造、キャラクター、プロット、物語に変換する。 |
| [100 TIMES AI WORLD BUILDING](https://github.com/masa-san-jp/100-times-ai-world-building) | 本リポジトリ：入力から世界設定資料を自律的に生成・検証・深化する。 |
| [100 TIMES AI MANGA DRAWING](https://github.com/masa-san-jp/100-times-ai-manga-drawing) | 生成 AI による漫画制作プロセスの高速化を記録・実験する。 |

各リポジトリは関連していますが、依存関係を共有する 1 つのパッケージではありません。

### テストの実行

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

外部サービスが必要なテストは `integration` マーカーが付き、既定では除外されます。

---

## English

### Overview

An engine that grows **world-setting material for story production** from your input alone (text, YAML,
JSON, … any shape) and keeps generating, verifying and deepening it with no human in the loop.
It does **not** write stories (no protagonist, plot, chapters or prose); the deliverable is the world itself.

For the material to support a story's credibility it aims at four properties at once:

| Property | Meaning | Mechanism |
|---|---|---|
| Breadth | The world extends beyond the subject: margins, others, unrelated domains | World axes and weights derived from the input; perspective/margin expansion |
| Depth | Every element has causes and layers of history | Cause and history operators; provenance recording |
| Scale | From world through region, settlement, district and site to detail | Scale hierarchy of the entity graph; zoom expansion |
| Detail | Proper nouns, numbers, institutions, objects, customs a scene can use | Specificity verification; in-world documents |

An objective, encyclopedia-style description layer is always produced as well.

#### Verification status

Automated tests use a deterministic fake backend. Separately, three models were compared on Ollama with the same input, seed 1 and 12 iterations each.

| Model | Accepted / rejected | Deepest scale | Structured-output calls | Time |
|---|---|---|---|---|
| gemma4:e4b | 5 / 7 | district | 168 | about 14 min |
| gpt-oss:20b | 5 / 7 | world | 149 | about 79 min |
| qwen3.8:27b | 9 / 3 | site | 183 | about 116 min |

No task failed to meet the output format in any of these runs. Common content failures were paraphrasing the input or nearby text and using units outside the contract.
This is one input and one seed; other concurrent work also affected elapsed time.
See the [model comparison examples](examples/model_comparison/README.md) for conditions and generated material,
and [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for implementation status.

### Documents

| File | Role | Language |
|---|---|---|
| [`README.md`](README.md) | Entry point, overview, quick start | Japanese / English |
| [`README_LOCAL.md`](README_LOCAL.md) | User guide (CLI, budgets, output, reports) | Japanese |
| [`DESIGN_SPEC_LOCAL.md`](DESIGN_SPEC_LOCAL.md) | Engine design | Japanese |
| [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) | Implementation / verification status | Japanese |
| [`DESIGN_SPEC.md`](DESIGN_SPEC.md) | Design of the old cloud notebook (legacy) | Japanese |
| [`examples/README.md`](examples/README.md) | Model comparison and legacy examples (for viewing) | Japanese |

### How it works

```text
input → input brief → world axes → world contract (independent stage)
                                           ↓
exploration: evaluate frontier → bandit selects an operator × target
                                           ↓
EntityBuilder: type → grounding → name → axes → summary
               → facts (one at a time, with a specified kind) → relations → review
Generate and validate each item; remake only items that fail
                                           ↓
all criteria pass → accept into the graph → next exploration iteration
                                           ↓
world reference (Markdown) + world.json + metrics and preference logs
```

- **Input brief**: preserves the original and extracts only explicit statements with quotes
  (`input/input_brief.json`). Quotes must be contiguous substrings of the source. Image observations (`--image`) can also be supplied.
- **World axes**: weights the domain catalog in `config/world/domains.yaml` against the input.
  Domains absent from the input retain a floor weight (`world/world_axes.json`).
- **World contract**: independently generates calendar, technology (capabilities, limits, units) and society
  from the brief and axes, before exploration. The graph holds `world_contract` and `contract_stage`;
  the manifest holds the stage result as `world_contract`. Failure to comply within `engine.structured.max_attempts`
  (default 3, including the first attempt) fails the run. Resume reuses the recorded result.
- **Exploration**: evaluates empty, unexpanded, uncaused, thin and underserved areas and selects an
  operator × target with a UCB1 / Thompson bandit. Operators are `premise`, `expand`, `zoom`, `cause`,
  `perspective`, `history` and `document`. Acceptance and the number of remade items update the bandit.
- **EntityBuilder** (`src/world/builder.py`): builds one entity field by field. Code assigns the ID, scale,
  parent and operation-specific relations. A type fixed by the operation needs no generation. Facts start
  with a measurement and a proper noun, then add objects, procedures and periods according to scale;
  each fact is generated and checked against its requested kind. A final review checks the assembled entity
  and requests repairs to specific names, summaries or facts. Defaults are four attempts per item and
  two repair rounds after review (`build` in `config/world/explore.yaml`).
- **Entity graph**: stores types, names, axes, summaries, facts, relations and provenance on the hierarchy
  `world → region → settlement → district → site → detail` (`world/graph.json`). Generation uses bounded local context.
- **Output contracts**: `generate_structured` validates JSON Schema from `config/schemas/`, and detects
  placeholder values and schema echoes. It tries format conversion of malformed outputs and deterministically
  checks that converted strings and numbers occur in the source output. Unresolved violations trigger content
  regeneration with feedback. Schemas containing booleans skip conversion. Unparseable constrained responses
  cause Ollama decoding constraints to be disabled; the client remembers this per backend and model.
  Anthropic keeps its forced tool-use constraint.
- **Metrics**: manifest `structured` records harness calls by task, attempts to compliance, failures, elapsed
  time, modes, placeholder/schema-echo counts, and conversion attempts, successes, fidelity failures and schema failures.
  `build` records generation calls by step (including retries and conversions), attempt distributions, failures
  and reasons by criterion. Both appear in `final/world_report.md`.
- **Preferences**: `world/preferences.jsonl` records each step, fact slot, attempt, output, checks and pass/fail,
  plus iteration outcomes. `extract_preference_pairs` pairs passing and failing outputs from the same
  iteration, step and slot. Model training is not performed.
- **Budgets and stopping**: iterations, wall time, generation calls, coverage, exhausted frontier and consecutive
  exceptions can stop exploration. Brief, axes and contract generation occur outside the exploration call budget
  and have structured-output attempt limits. Checkpoints support resuming.

Acceptance requires all eight criteria in [config/world/criteria.yaml](config/world/criteria.yaml) to pass through item checks and the final review.

| Criterion | What it checks |
|---|---|
| `grounded` | An input statement or local entity supports the entity, with a reason for derivation |
| `consistent` | Schema compliance, no numeric conflict or self-reference, and overall consistency |
| `objective` | The name uses the output language's script; the description is neutral |
| `no_story` | No dialogue, personal narration or narrative voice in reference descriptions |
| `specific` | Facts match their requested kinds and measurements/periods carry the required information |
| `informative` | Character 3-gram overlap with input/local context is at most 0.6; facts add information beyond other facts |
| `distinct` | Normalized names differ from existing names and facts within the entity do not duplicate one another |
| `fits_world` | Units, unit combinations and calendar markers belong to the contract; the entity fits the input and world |

### Quick Start

```bash
# 1. Install Ollama and pull your model (the name is model.name in config/ollama_config.yaml)
ollama pull <model.name>

# 2. Start the Ollama server
ollama serve

# 3. Install Python dependencies
pip install -r requirements-local.txt

# 4. Check prerequisites
python setup_check.py

# 5. Generate a world from your own input file (non-interactive)
python example_run.py --context-file path/to/your_input.yaml --yes
```

You supply your own input (text, YAML or JSON; free form). There is no built-in default input; without
`--context-file` and `--yes` the interactive menu (generate a world / resume / exit) asks for a file path.

#### Budget

```bash
python example_run.py --context-file path/to/your_input.yaml --yes \
  --max-iterations 50 --max-minutes 90 --max-calls 600
```

| Argument | Meaning | Default |
|---|---|---|
| `--max-iterations` | Exploration iterations | `budget` in `config/world/explore.yaml` |
| `--max-minutes` | Wall-clock minutes of exploration | unlimited |
| `--max-calls` | Model generation calls | unlimited |

Other arguments: `--model` (generation model), `--vision-model` (for `--image`), `--backend ollama|anthropic`,
`--seed`, `--output-dir`, `--runs N` (N independent worlds from the same input), `--run-id`, `--choice 2` (resume).
Model names come from the config file or `--model`; they are never fixed in code.

```bash
# Resume (run id is the <run_id> in output/world_<run_id>/)
python example_run.py --choice 2 --run-id <run_id> --max-iterations 100

# Five independent worlds from the same input, plus a comparison report
python example_run.py --context-file path/to/your_input.yaml --yes --runs 5 --seed 7
```

#### Anthropic backend

```bash
python -m pip install -r requirements-cloud.txt
python setup_check.py --backend anthropic
python example_run.py --yes --backend anthropic --context-file path/to/your_input.yaml
```

Credentials are resolved by the Anthropic SDK from its normal environment/profile (no API key is stored in the
repository). Set the model with `anthropic.model` (or `--model`); model-dependent request settings live in
`anthropic.request_options`.

#### Output package

```text
output/world_<run_id>/
├── run_manifest.json        # engine config, budget, seed, backend/model, stop reason, status
├── input/                   # original input, images, input_brief.json
├── world/                   # world_axes.json, graph.json, preferences.jsonl
├── checkpoints/             # for resuming
├── quality_report.json/.md  # quality report
└── final/
    ├── world.json           # machine-readable world model (axes, graph, run summary)
    ├── world_bible/         # world reference (README.md, scales/, entities/, glossary.md, timeline.md, documents.md)
    └── world_report.md      # exploration results (coverage, per-scale counts, task and step metrics)
```

`--runs N` creates `output/batch_<batch_id>/` with `batch_manifest.json`, independent worlds under `worlds/`
and `comparison.md`. Quality and comparison can also be run on their own:

```bash
python -m src.quality output/world_<run_id>
python -m src.compare output/world_a output/world_b      # or --batch output/batch_<batch_id>
```

The quality report checks graph integrity, axis coverage, scale depth, provenance, duplicates and exploration status;
the comparison report adds cross-world overlap (same names, near-identical entities, shared proper nouns).

#### Python API

```python
from src import Pipeline

pipeline = Pipeline(seed=7, budget={"max_iterations": 50})
result = pipeline.run(open("path/to/your_input.yaml", encoding="utf-8").read())
print(result.stop_reason, pipeline.package_dir)
```

### Old versions

- The old cloud notebook (`legacy/20250601-100-TIMES-AI-WORLD-BUILDING-v1.2.ipynb`) and the local notebook
  (`legacy/local-v2.0.ipynb`) were moved to [`legacy/`](legacy/). They are **old versions** that
  generate stories, are unrelated to the new engine, and are not maintained.
- [`examples/`](examples/README.md) contains model comparison runs and legacy output for viewing. The engine does not reference them.
- The old pipeline's four role characters, plot/chapter/novel generation and fixed-schema world items were removed.

### Related repositories

| Repository | Purpose |
|------------|---------|
| [100 TIMES AI HEROES](https://github.com/masa-san-jp/100-times-ai-heroes) | Expands wishes, abilities, and roles into many character ideas and image-generation prompts. |
| [100 TIMES AI HERO'S JOURNEY](https://github.com/masa-san-jp/100-times-ai-heros-journey) | Turns a writer's self-narrative into a Hero's Journey structure, characters, plot, and story. |
| [100 TIMES AI WORLD BUILDING](https://github.com/masa-san-jp/100-times-ai-world-building) | This repository: autonomously generates, verifies and deepens world-setting material from an input. |
| [100 TIMES AI MANGA DRAWING](https://github.com/masa-san-jp/100-times-ai-manga-drawing) | Documents and experiments with speeding up the manga-making process using generative AI. |

The repositories are related, but they are not a single package with shared dependencies.

### Running Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

Tests that require external services are marked `integration` and excluded by default.
