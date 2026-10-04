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
| スケール感 | 世界・文明から地域・都市・地区・施設・部屋・個人の一日までの階層 | エンティティグラフのスケール階層、ズーム展開 |
| ディテール | 固有名詞・数値・制度・物・慣習など、場面に置ける具体物 | 具体性の検証、世界内文書（条文・記録・掲示など） |

あわせて、客観的な説明文（百科事典・設定解説の調子で、構造・歴史・因果を中立に記述する層）を必ず出力します。

#### 現在の検証状況

新エンジンのテストは**決定的なフェイクバックエンドだけ**で行っています（実 LLM には接続しません）。
実機のローカルモデルでは、Ollama + `gpt-oss:20b` による**短い 1 回のスモーク実行（反復 4 回・約 12 分で完走）**だけを行いました。
そこでは、入力の言い換えが満点になる・深く掘られない・日本語入力に英語が混ざる、という問題が見つかり、対処を入れています
（詳細は [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md)）。**修正後の実機での再実行と長時間実行は未実施**で、
出力品質と 20B 級モデルでの安定性は十分には確認できていません。

### ドキュメント

| ファイル | 役割 | 言語 |
|---|---|---|
| [`README.md`](README.md) | 入口・概要・クイックスタート | 日本語 / 英語 |
| [`README_LOCAL.md`](README_LOCAL.md) | 利用ガイド（CLI・予算・出力・レポート） | 日本語 |
| [`DESIGN_SPEC_LOCAL.md`](DESIGN_SPEC_LOCAL.md) | エンジンの設計 | 日本語 |
| [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) | 実装・検証状況と残タスク | 日本語 |
| [`DESIGN_SPEC.md`](DESIGN_SPEC.md) | 旧クラウド版ノートブックの設計（旧版） | 日本語 |
| [`examples/README.md`](examples/README.md) | 旧パイプラインの出力（閲覧用） | 日本語 |

### 仕組み

```
入力（形式自由） ──► 入力の受け入れ（原文保存・明示事項の抽出・前提を足さない）
                      │
                      ▼
                世界の軸を決める（入力から、この世界に必要な領域と重みを導く）
                      │
                      ▼
                世界の契約を決める（暦・技術・社会の定義と限界）
                      │
                      ▼
      ┌──────► 探索ループ（予算内で自律的に反復） ◄──────┐
      │   1. 世界を評価し、未発達な箇所（フロンティア）を見つける │
      │   2. 次に行う操作と対象を選ぶ（報酬で学習するバンディット）│
      │   3. 候補を複数生成（展開・ズーム・因果・視点・歴史・文書）│
      │   4. 検証器で採点（凡庸さ・由来・具体性・整合性・客観性） │
      │   5. 最良候補を採用／基準未満なら批評して書き直し        │
      └──────────────── 6. 世界モデルへ反映 ──────────────────┘
                      │
                      ▼
       世界設定資料（Markdown）＋ 機械可読の world.json ＋ 採点・選好ログ
```

- **入力の受け入れ**：原文を保存し、明示された事項だけを引用付きで抽出します（`input_brief.json`）。特定のジャンル・時代・
  舞台・技術・主人公像は、プロンプトにもコードにも埋め込みません。画像入力（`--image`）も受け付けます。
- **世界の軸**：汎用の領域チェックリストを入力に照らして重み付けし、この世界に必要な軸を決めます（`world_axes.json`）。
  入力が触れていない領域にも下限の重みを残し、周縁まで広げます。
- **世界の契約**：軸の決定後、入力ブリーフと軸だけの短い文脈から暦・技術・社会を独立して生成します。
  `config/world/explore.yaml` の `contract.max_attempts`（初回を含む、既定3回）まで不足欄を指摘して再試行します。
  結果と試行回数は `run_manifest.json` の `world_contract`、グラフの `contract_stage`、レポートに保存します。
  成功した定義はグラフの `world_contract` に保持し、`premise` は契約を返さなくても通常の候補として採点します。
  失敗時は暦・技術・単位・制度の契約に依存する検証を無効にし、入力・既存事実との矛盾や構造の検査を残して探索を続けます。
  再開時は成功・失敗とも結果を再利用します。契約呼び出しは入力・軸の生成と同様に探索前の処理であり、
  探索の生成回数予算とは別に `max_attempts` で制限します。
- **エンティティグラフ**：世界を `世界 → 地域 → 集落 → 地区 → 施設 → 細部` のスケール階層に置いたグラフとして保持します。
  各エンティティは種別・軸・関係・事実（固有名詞・数値・制度など）・由来（入力のどの記述、またはどのエンティティから
  どんな理由で導いたか）・採点を持ちます（`graph.json`）。
- **オペレータ**：`premise`（前提）、`expand`（展開）、`zoom`（下位スケールへ）、`cause`（因果）、`perspective`
  （視点・周縁）、`history`（歴史の地層）、`document`（世界内文書）。1 回の生成で扱う文脈は小さく保ち、
  ローカルの 20B 級モデルでも動く粒度にしています。
- **検証器と報酬**：凡庸さ（genericity）、由来、具体性、整合性、客観性、新規性を 0〜1 で採点し、重み付き合成を
  報酬とします。**凡庸さ**は「同じ話題の中でのありきたりさ」として、同じ生成スロットで独立に生成した候補どうしの収束
  （全候補に共通する内容はモデルの既定値）と、入力・文脈の言い換え（入力の語をなぞった名前や要約）を減点します。
  入力なしで生成した対照との近さも補助的に使います。具体性は、固有名詞・数値の実質（一般名詞や数えただけの数は
  空の事実）まで検査し、実機バックエンドでは LLM 判定も併用します。作例や固定のコーパスには頼りません。
- **自律探索ループ**：フロンティア（空・未展開・因果なし・薄い・軸の偏り・低スコア）を評価し、「操作×対象」を
  UCB1 / Thompson のバンディットで選びます。基準未満の候補は批評を添えて書き直します。重みは更新しません（第 1 段階）。
- **選好ログ**：すべての候補・採点・採否・書き直しの系譜を `world/preferences.jsonl` に保存します。将来 DPO などで
  モデル自体を調整するための選好データ形式までを実装済みです。候補の組み立て時の棄却理由（スキーマ不足・由来なし・
  事実不足・重複名・グラフ不整合・不正な契約など）は INFO ログと iteration 記録の `discard_reasons` に件数を残します。
- **予算と停止**：反復回数・経過時間・生成呼び出し回数のいずれかに達するか、被覆条件を満たすか、フロンティアが
  尽きると停止し、停止理由を記録します。途中から再開できます。


#### 用語を読むための例

架空の入力「二つの集落が一つの水源を共有している」を考えると、「世界の軸」は水の配分・制度・暮らしなどの調査領域、「エンティティ」は集落や配分を担う組織、「ズーム」は集落から地区・施設・細部へ下る操作を指します。「由来」は入力の明示事項と、そこから生成した設定の関係です。例えば未記載の配分制度を生成した場合、入力に書かれた事実とは区別して扱います。

これは[オペレータ](src/world/operators.py)とグラフの用語を説明する例で、既定の入力・固定ジャンル・実測出力ではありません。検証器の高得点も作品としての完成や実世界の事実性を保証しません。

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
├── world/                   # world_axes.json, graph.json, contrasts.json, preferences.jsonl
├── checkpoints/             # 再開用
├── quality_report.json/.md  # 品質レポート
└── final/
    ├── world.json           # 機械可読の世界モデル（軸・グラフ・実行サマリ）
    ├── world_bible/         # 世界設定資料（README.md, scales/, entities/, glossary.md, timeline.md, documents.md）
    └── world_report.md      # 探索結果（被覆・スケール別件数・報酬分布・凡庸さで落とした例）
```

`--runs N` では `output/batch_<batch_id>/` に `batch_manifest.json`、`worlds/` 以下の独立した世界、`comparison.md` が
作られます。品質・比較は単体でも実行できます。

```bash
python -m src.quality output/world_<run_id>
python -m src.compare output/world_a output/world_b      # または --batch output/batch_<batch_id>
```

品質レポートは軸の被覆、スケールの深さ、報酬の分布、凡庸さ、由来、重複を、比較レポートは世界同士の重複
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
- [`examples/`](examples/README.md) の作例は旧パイプラインの出力です。新エンジンの仕組みからは参照しません。
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
| Scale | From world and civilisation down to region, city, district, site, room and one person's day | Scale hierarchy of the entity graph; zoom expansion |
| Detail | Proper nouns, numbers, institutions, objects, customs a scene can use | Specificity verification; in-world documents |

An objective, encyclopedia-style description layer is always produced as well.

#### Verification status

The new engine is tested **only with a deterministic fake backend** (no real LLM is contacted).
The implementation notes record a short Ollama + `gpt-oss:20b` smoke run (four iterations, about 12 minutes),
followed by an attempted rerun that exposed a model-output parsing failure. Fixes were added, but a complete
post-fix real-model rerun and long-duration validation are still unverified. See [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md).

### Documents

| File | Role | Language |
|---|---|---|
| [`README.md`](README.md) | Entry point, overview, quick start | Japanese / English |
| [`README_LOCAL.md`](README_LOCAL.md) | User guide (CLI, budgets, output, reports) | Japanese |
| [`DESIGN_SPEC_LOCAL.md`](DESIGN_SPEC_LOCAL.md) | Engine design | Japanese |
| [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) | Implementation / verification status | Japanese |
| [`DESIGN_SPEC.md`](DESIGN_SPEC.md) | Design of the old cloud notebook (legacy) | Japanese |
| [`examples/README.md`](examples/README.md) | Output of the old pipeline (for viewing) | Japanese |

### How it works

```
input (free form) ──► input acceptance (keep the original, extract only what is stated)
                          │
                          ▼
                 decide the world's axes (domains and weights from the input)
                          │
                          ▼
       ┌──────► exploration loop (autonomous, within a budget) ◄──────┐
       │  1. evaluate the world, find the frontier (underdeveloped parts)│
       │  2. pick the next operator and target (bandit learning rewards) │
       │  3. generate several candidates (expand/zoom/cause/perspective/ │
       │     history/document)                                           │
       │  4. score with verifiers (genericity, provenance, specificity,  │
       │     consistency, objectivity)                                   │
       │  5. accept the best, or critique and rewrite if below threshold │
       └────────────── 6. commit to the world model ─────────────────────┘
                          │
                          ▼
     world reference (Markdown) + machine-readable world.json + score/preference logs
```

- **Input acceptance**: stores the original and extracts only explicit statements with exact quotes
  (`input_brief.json`). No genre, era, setting, technology or protagonist is built into prompts or code.
  Image input (`--image`) is supported.
- **World axes**: a generic domain checklist is weighted against the input to decide the axes this world needs
  (`world_axes.json`). Domains the input never touches keep a floor weight, so the world reaches its margins.
- **Entity graph**: the world is a graph on the scale hierarchy `world → region → settlement → district → site → detail`.
  Each entity has a type, axes, relations, facts (proper nouns, numbers, institutions, …), provenance (which input
  statement, or which entity and why it was derived) and scores (`graph.json`).
- **Operators**: `premise`, `expand`, `zoom` (to the next scale), `cause`, `perspective` (viewpoints and margins),
  `history` (layers of history), `document` (in-world documents). Each call carries only a small context, sized for
  local 20B-class models.
- **Verifiers and reward**: genericity, provenance, specificity, consistency, objectivity and novelty are scored in
  [0, 1] and combined by weights into the reward. **Genericity** uses a contrast: the same generation slot generated
  *without any input* (the model's prior, what appears in every world), and penalises text close to it. No example
  or fixed corpus is used.
- **Autonomous exploration loop**: frontier items (empty, unexpanded, uncaused, thin, axis gap, low score) are
  evaluated and an operator x target pair is chosen by a UCB1 / Thompson bandit. Candidates below threshold are
  critiqued and rewritten. No weights are updated (stage 1).
- **Preference log**: every candidate, its scores, the decision and the rewrite lineage go to
  `world/preferences.jsonl`, so a later stage can tune a model (e.g. DPO). This repository implements the data
  format only.
- **Budget and stopping**: the run stops on iterations, wall time, generation calls, met coverage or an exhausted
  frontier, and records the stop reason. It can be resumed.

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
├── world/                   # world_axes.json, graph.json, contrasts.json, preferences.jsonl
├── checkpoints/             # for resuming
├── quality_report.json/.md  # quality report
└── final/
    ├── world.json           # machine-readable world model (axes, graph, run summary)
    ├── world_bible/         # world reference (README.md, scales/, entities/, glossary.md, timeline.md, documents.md)
    └── world_report.md      # exploration results (coverage, per-scale counts, reward distribution, genericity discards)
```

`--runs N` creates `output/batch_<batch_id>/` with `batch_manifest.json`, independent worlds under `worlds/`
and `comparison.md`. Quality and comparison can also be run on their own:

```bash
python -m src.quality output/world_<run_id>
python -m src.compare output/world_a output/world_b      # or --batch output/batch_<batch_id>
```

The quality report covers axis coverage, scale depth, reward distribution, genericity, provenance and duplicates;
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
- The samples in [`examples/`](examples/README.md) are output of the old pipeline. The new engine never references them.
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
