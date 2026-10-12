# 100 TIMES AI WORLD BUILDING

[![Tests](https://github.com/masa-san-jp/100-times-ai-world-building/actions/workflows/tests.yml/badge.svg)](https://github.com/masa-san-jp/100-times-ai-world-building/actions/workflows/tests.yml)

[日本語](#日本語) | [English](#english)

## 日本語

### 概要

利用者の入力（テキスト・YAML・JSON など、形式は自由）だけを起点に、**物語制作の土台になる世界設定資料**を、
人の介入なしに生成・検証・深化し続けるエンジンです。物語（主人公・プロット・章・小説本文）は生成しません。
成果物は世界そのものの資料です。

このリポジトリは**エージェントハーネス**です。出力の形式（`config/schemas/` の JSON Schema）と、採否の基準
（項目ごとの基準 `config/world/criteria.yaml`、世界全体の基準 `config/world/world_criteria.yaml`）をリポジトリが決め、
どのモデルにも同じものを守らせます。基準はモデルに合わせて緩めません。そのため、モデルの違いは「動く・動かない」ではなく、
基準を満たして採用された**量・深さ・かかった時間**の差として表れます。

世界設定資料が物語の説得力を支えるために、次の 4 つを同時に満たすことを目指します。

| 性質 | 意味 | 仕組み |
|---|---|---|
| 広がり | 世界が主題の周辺だけで終わらず、周縁・他者・無関係な領域まで存在する | 入力から決める世界の軸と重み、視点・周縁の展開 |
| 深み | 各要素に「なぜそうなっているか」の因果と歴史の地層がある | 因果・歴史オペレータ、由来（provenance）の記録 |
| スケール感 | 世界から地域・集落・地区・施設・細部までの階層 | エンティティグラフのスケール階層、ズーム展開 |
| ディテール | 固有名詞・数値・制度・物・慣習など、場面に置ける具体物 | 具体性の検証、世界内文書（条文・記録・掲示など） |

あわせて、客観的な説明文（百科事典・設定解説の調子で、構造・歴史・因果を中立に記述する層）を必ず出力します。

#### 現在の検証状況

自動テストは決定的なフェイクバックエンドで実行します。実機では、Ollama 上で次の 2 つを確かめました。

**モデル比較**（[`examples/model_comparison/`](examples/model_comparison/README.md)）：同じ入力・設定・基準・seed 1 で、
サイズの違う 3 モデルに世界を作らせました。判定モデルは 3 実行とも `qwen3.8:27b` です。

| モデル | 反復 | 採用 / 不採用 | 到達スケール | 世界全体の基準 | 所要時間 |
|---|---|---|---|---|---|
| gemma4:e4b | 12 | 6 / 6 | 世界 → 地区 | 未達（軸の被覆 0.19・歴史 0・施設と細部なし） | 約 2.3 時間 |
| gpt-oss:20b | 18 | 13 / 5 | 世界 → 細部 | 未達（軸の被覆 0.38） | 約 8.6 時間 |
| qwen3.8:27b | 31 | 28 / 3 | 世界 → 細部 | すべて達成（`coverage_met`） | 約 8.1 時間 |

反復の回数がそろっていないのは、途中再開で反復の上限が引き継がれなかったためです（qwen3.8:27b は基準を満たして自動停止）。
量は 1 反復あたりの採用率（50% / 72% / 90%）で比べてください。所要時間は、3 本を同じマシンで並列に走らせ、
別プロジェクトとも Ollama を共用した状態の値です。

**合格ラインの確認**（[`examples/calibration/`](examples/calibration/README.md)）：世界全体の基準が特定の入力に合わせた値でないかを、
性質の違う入力（英語・制度と記録の方式を含む）で確かめました。`qwen3.8:27b`（生成・判定とも）で、反復の上限 40 のところ
33 反復・25 件採用で `coverage_met` に達しました（約 4.8 時間）。

どちらも入力 1 つ・seed 1 つの結果で、モデル全般の順位を示すものではありません。実装状況は
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) を参照してください。

#### 実行時間の目安と注意

ローカルモデルでは、1 回の実行に数時間かかります（上の作例では約 2.3〜8.6 時間）。macOS の低電力モードでは GPU が大きく
制限されるので、長い実行は電源につないで低電力モードを切ってください。

### ドキュメント

| ファイル | 役割 | 言語 |
|---|---|---|
| [`README.md`](README.md) | 入口・概要・クイックスタート | 日本語 / 英語 |
| [`README_LOCAL.md`](README_LOCAL.md) | 利用ガイド（CLI・予算・出力・レポート） | 日本語 |
| [`DESIGN_SPEC_LOCAL.md`](DESIGN_SPEC_LOCAL.md) | エンジンの設計 | 日本語 |
| [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) | 実装・検証状況と残タスク | 日本語 |
| [`DESIGN_SPEC.md`](DESIGN_SPEC.md) | 旧クラウド版ノートブックの設計（旧版） | 日本語 |
| [`examples/README.md`](examples/README.md) | 新エンジンの作例（モデル比較・合格ラインの確認）と旧版の作例（閲覧用） | 日本語 |

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
  契約は項目ごとに生成し、その試行上限は `config/world/contract.yaml` の `max_item_attempts`（既定4回）です。準拠しなければ実行は失敗します
  （`engine.structured.max_attempts` は契約内の判定呼び出しに使います）。再開では保存済みの結果を使います。
- **探索ループ**：空・未展開・因果なし・事実不足・軸の不足などをフロンティアとして評価し、UCB1 / Thompson の
  バンディットで「操作×対象」を選びます。操作は `premise` / `expand` / `zoom` / `cause` / `perspective` / `history` / `document`。
  採用結果と作り直しの回数からバンディットを更新します。
- **EntityBuilder**（`src/world/builder.py`）：1つのエンティティを項目ごとに生成します。ID・スケール・親・操作に対応する
  関係はコードが決めます。型が操作で一意なら生成を省きます。事実は測定値・固有名詞を先に、物・手順・期間を
  スケールに応じて追加し、指定した種類で1件ずつ検証します。最後に組み立てた全体を審査し、指摘された名前・説明・事実だけを再生成します。
  ステップは既定4試行まで、全体審査後の修正は既定2巡までです（`config/world/explore.yaml` の `build`）。
  ただし事実本文の試行を使い切ったとき、または `restatement_check` が既存の事実の言い換えと判定したとき（残りの本文試行は続けず直ちに）、その事実を一度だけ要素から作り直し、`fact_element`・`fact_text` に追加の試行枠を与えます（既定では同じ事実の各ステップが合計最大8試行）。
- **エンティティグラフ**：`world → region → settlement → district → site → detail` の階層で、型・名前・軸・説明・事実・
  関係・由来を保存します（`world/graph.json`）。生成には件数と文字数を制限した局所文脈を渡します。
- **出力契約**：`config/schemas/` の JSON Schema を `generate_structured` が検証します。プレースホルダー値と
  スキーマの書き写しも検出します。形式が違う場合は元の出力から形式を変換し、自由文字列・数値（数値の列挙値を含む）が
  元の出力にあるかを決定的に検査します。文字列の列挙値（`enum`）は検査の対象外です。変換で直らなければ違反箇所と前回出力を示して内容を書き直します。
  真偽値を含むスキーマでは形式変換を省きます。Ollama でデコード拘束中の応答が解析不能なら拘束を外し、
  同じクライアントのバックエンド・モデルの組ごとに可否を記憶します。Anthropic は tool use の拘束を維持します。
- **計測**：manifest の `structured` はタスク別のハーネス呼び出し数・準拠までの試行回数・失敗・所要時間・方式、
  プレースホルダーとスキーマ書き写しの検出数、変換の試行・成功・忠実性違反・スキーマ違反を記録します。
  `build` はステップ別の生成呼び出し数（再試行・変換を含む）・試行回数・失敗・基準別の不合格理由を記録し、`final/world_report.md` にも表示します。
- **選好ログ**：`world/preferences.jsonl` にステップ・事実の位置・試行・出力・検査結果・合否と反復の結果を保存します。
  `extract_preference_pairs` は同じ反復・ステップ・位置の合格出力と不合格出力を組にします。モデルの学習は実行しません。
- **予算と停止**：世界全体の基準をすべて満たすと `coverage_met` で止まります。そのほか、反復回数・経過時間・
  生成呼び出し回数、フロンティアの枯渇、連続した例外でも停止します。
  入力・軸・契約の生成は探索の呼び出し予算の外で、構造化出力の試行上限で制限します。チェックポイントから再開できます。

#### 項目ごとの基準（`config/world/criteria.yaml`）

エンティティは、次の基準のうち適用される項目検査と審査に合格すれば採用されます。`breadth`・`depth`・`scale` は世界全体の基準で、未達でも探索を続け、すべて達成すると停止条件 `coverage_met` になります。`level` は適用先（`entity`＝エンティティ、
`world`＝世界全体、`both`＝両方）、`method` は主な検査の方式（`structure`＝構造の検査、`rule`＝決定的な規則、
`judge`＝モデルの判定）です。

| 基準 | level / method | 検査する内容 |
|---|---|---|
| `faithful` | both / structure | 入力の事項か局所エンティティに由来し、導出の理由がある。世界が入力に忠実である |
| `no_outside_premises` | entity / judge | 単位と暦の標識が契約に従う。現実世界の体系と固有名詞は、元の入力で指定された場合だけ許す |
| `breadth` | world / structure | 世界が入力から導いた領域（軸）に広がっている |
| `depth` | world / structure | 世界が根本の原因と仕組み（因果・歴史）を説明している |
| `scale` | world / structure | 世界がスケールの階層をまたいで事実をつないでいる |
| `detail` | entity / structure | 事実が種類ごとの必須項目を持ち本文に含む。固有名詞は新しく、測定値は値と時間以外の単位、期間は暦の標識と値を持つ |
| `objective` | entity / judge | 名前が出力言語の文字種で、説明が引用・個人の語り・物語の語り口のない客観的な参照の文体である |
| `consistent` | both / judge | 出力がスキーマに従い、数値が既存の事実と矛盾せず、関係が自己参照せず、エンティティ内に矛盾がない |
| `new_information` | entity / rule | 各事実が既存のどの事実にもない情報を加える。固有名詞は入力・ブリーフ・局所文脈・既存の名前・契約の用語にもない。数値は（値, 単位）と主題が既存と重なる場合だけ重複とし、本文は既存の事実と同一・ほぼ同一（文字3-gram の Jaccard が `duplicate_jaccard`＝0.8 以上）でなく、別の言い方での言い換えでもない |

言い換えの判定は、判定モデルが文字3-gram の Jaccard が大きい既存の事実（最大 `restatement_candidates`＝5 件）と比べて行います。

#### 判定モデル（`engine.judge_model` / `--judge-model`）

モデルの判定を使う処理（`real_world_check`＝入力にない現実世界の体系の持ち込み、`review`＝組み立てた全体の審査、
`restatement_check`＝言い換えの判定）は、生成モデルとは別のモデルに固定できます。`config/ollama_config.yaml` の
`engine.judge_model` か `--judge-model` で指定し、空なら生成モデルと同じです。判定を固定すると、生成モデルを替えても
同じ判定で比べられます。再開では、`--model` と `--vision-model` のどちらも指定しなければ、その実行の判定モデルを引き継ぎます。
どちらかを指定すると引き継がず、`engine.judge_model`（空なら生成モデル）を使うので、CLI で固定した判定を維持するには
`--judge-model` も再指定してください。判定の精度は、検証用の事例集 `tests/fixtures/judge_cases/` を使う `scripts/validate_judges.py` で測ります
（実モデルに接続するため、CI では実行しません）。モデル比較の作例では判定を `qwen3.8:27b` に固定しました。

#### 世界全体の基準と停止（`config/world/world_criteria.yaml`）

世界全体の基準をすべて満たすと、探索は停止理由 `coverage_met` で止まります。値は目標を表し、モデルの能力に合わせて下げません。

| 基準 | 閾値 | 意味 |
|---|---|---|
| `faithful` | 1.0 | 入力の事項のうち、由来として使われた事項の割合 |
| `breadth.axes` | 1.0 | 必要件数（`max(1, ceil(軸の重み × per_weight))`、`per_weight`＝3。例：重み0.34なら2件）を満たした軸の割合 |
| `breadth.perspective` | 1 | 操作 `perspective` で作ったエンティティの件数 |
| `depth.relations` | 0.3 | 世界以外のエンティティのうち、因果の関係（`causes` / `affects`）でつながったものの割合 |
| `depth.history` | 1 | 操作 `history` で作ったエンティティの件数 |
| `scale.<スケール>` | 各 1 | 世界・地域・集落・地区・施設・細部それぞれの最低件数（`min_entities`） |
| `scale.chain` | あり | 世界から細部まで、親子が途切れずにつながっている |

`selection.focus_unmet`（`config/world/explore.yaml`、既定 true）が有効なあいだは、未達の基準を埋める候補
（世界全体の基準の不足を埋める候補と、`breadth.axes` が未達のときは軸の不足を埋める候補）を優先して選びます。

#### 並列生成（`parallel.builds` / `--parallel-builds`）

`config/world/explore.yaml` の `parallel.builds`（既定 4）の件数だけ、エンティティを並列に作ります。
単独生成と再開では `--parallel-builds` でこの件数を上書きできます。`--runs 2` 以上のバッチには `--parallel-builds` を渡さず、設定ファイルの `parallel.builds` が使われます。
確定は選んだ順に行い、2 件目以降は確定の前に、その間に確定した内容との重複などを確かめ直します。
確かめ直しで不合格になったエンティティは不採用になります。

注意：Ollama はモデルによって、同時に 1 件しか処理しません（サーバーログ `~/.ollama/logs/server.log` の `n_seq_max` で確認できます）。
その場合は 1 にしてください。並列にしても速くならず、確定時の不採用が増えます。

#### バックエンドが応答しないとき

- 生成呼び出しがタイムアウトか接続エラーになると、Ollama の生存確認（`GET /api/tags`）を行い、応答がなければ呼び出しを失敗にします。
- `server.call_deadline_seconds`（`config/ollama_config.yaml`、既定 1800）が Ollama の 1 回の呼び出し（再試行を含む）の上限です。超えると呼び出しは失敗します。
  Anthropic には適用されず、`anthropic.timeout` と `anthropic.max_retries` を使います（再試行を含む同じ総時間の上限はありません）。
- 探索中にバックエンドが応答しないときは、チェックポイントを保存して待機し、60・120・240・480・600 秒…の間隔で生存確認を繰り返します。
  応答が戻れば、その反復をやり直します。
- 反復が確定しないまま `engine.backend_wait_max_seconds`（既定 7200 秒）を超えると、終了コード 75 で止まり、
  再開コマンド（`--choice 2 --run-id <run_id>`）がログに出ます。これは単独生成と再開の場合です。
  `--runs 2` 以上のバッチでは、待機上限の例外を失敗として記録して次の世界へ進み、バッチ終了時の終了コードは 1 です。

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
| `--parallel-builds` | 並列に作るエンティティ数 | `config/world/explore.yaml` の `parallel.builds`（4） |

`--parallel-builds` は単独生成と再開だけに有効です（`--runs 2` 以上のバッチでは `parallel.builds` を使います）。バックエンドが同時に処理できる数に合わせてください。1 にすると 1 件ずつ作ります（上の「並列生成」の注意を参照）。

そのほかの主な引数：`--model`（生成モデル）、`--judge-model`（判定モデル）、`--vision-model`（`--image` 用）、
`--backend ollama|anthropic`、`--seed`、`--output-dir`、`--runs N`（同じ入力から N 個の独立した世界を作る）、`--run-id`、
`--choice 2`（再開）。モデル名は設定ファイルまたは引数で渡し、コードには固定しません。

#### 再開

```bash
# 途中から再開（run-id は output/world_<run_id>/ の <run_id>）
python example_run.py --choice 2 --run-id <run_id>
```

再開は、開始時の予算（実効値）を引き継ぎます。明示した引数（例：`--max-iterations 100`）だけを上書きし、
上書きした内容は manifest の `budget.resume_overrides` に記録します。

```bash
# 予算を上書きして再開
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
- [`examples/`](examples/README.md) は閲覧用の作例です。新エンジンの作例（モデル比較・合格ラインの確認）と旧パイプラインの出力を含み、仕組みからは参照しません。
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

This repository is an **agent harness**. The repository decides the output format (the JSON Schemas in
`config/schemas/`) and the acceptance criteria (per-item criteria in `config/world/criteria.yaml`, world-level
criteria in `config/world/world_criteria.yaml`) and makes every model follow the same ones. The criteria are not
relaxed for any model, so differences between models show up not as "works / does not work" but as differences in
the **amount accepted, the depth reached and the time taken**.

For the material to support a story's credibility it aims at four properties at once:

| Property | Meaning | Mechanism |
|---|---|---|
| Breadth | The world extends beyond the subject: margins, others, unrelated domains | World axes and weights derived from the input; perspective/margin expansion |
| Depth | Every element has causes and layers of history | Cause and history operators; provenance recording |
| Scale | From world through region, settlement, district and site to detail | Scale hierarchy of the entity graph; zoom expansion |
| Detail | Proper nouns, numbers, institutions, objects, customs a scene can use | Specificity verification; in-world documents |

An objective, encyclopedia-style description layer is always produced as well.

#### Verification status

Automated tests use a deterministic fake backend. On real models, two things were checked on Ollama:

**Model comparison** ([`examples/model_comparison/`](examples/model_comparison/README.md)): three models of different
sizes built a world with the same input, settings, criteria and seed 1. The judge model was `qwen3.8:27b` in all three runs.

| Model | Iterations | Accepted / rejected | Deepest scales | World-level criteria | Time |
|---|---|---|---|---|---|
| gemma4:e4b | 12 | 6 / 6 | world → district | not met (axis coverage 0.19, history 0, no site or detail) | about 2.3 h |
| gpt-oss:20b | 18 | 13 / 5 | world → detail | not met (axis coverage 0.38) | about 8.6 h |
| qwen3.8:27b | 31 | 28 / 3 | world → detail | all met (`coverage_met`) | about 8.1 h |

The iteration counts differ because resuming did not carry the iteration limit over (qwen3.8:27b stopped on its own once
the criteria were met). Compare quantity by acceptance rate per iteration (50% / 72% / 90%). The times are from three
runs in parallel on one machine, with Ollama shared with other projects.

**Threshold check** ([`examples/calibration/`](examples/calibration/README.md)): checks that the world-level criteria are
not tuned to one input, using an input of a different nature (English, including institutions and record-keeping methods).
With `qwen3.8:27b` (generation and judging) the run reached `coverage_met` in 33 iterations with 25 entities accepted,
against a limit of 40 iterations (about 4.8 hours).

Both are one input and one seed, so they do not rank models in general. See
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for implementation status.

#### Run time and cautions

With local models one run takes hours (about 2.3 to 8.6 hours in the examples above). On macOS, Low Power Mode
restricts the GPU heavily, so connect to power and turn Low Power Mode off before a long run.

### Documents

| File | Role | Language |
|---|---|---|
| [`README.md`](README.md) | Entry point, overview, quick start | Japanese / English |
| [`README_LOCAL.md`](README_LOCAL.md) | User guide (CLI, budgets, output, reports) | Japanese |
| [`DESIGN_SPEC_LOCAL.md`](DESIGN_SPEC_LOCAL.md) | Engine design | Japanese |
| [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) | Implementation / verification status | Japanese |
| [`DESIGN_SPEC.md`](DESIGN_SPEC.md) | Design of the old cloud notebook (legacy) | Japanese |
| [`examples/README.md`](examples/README.md) | Examples of the current engine (model comparison, threshold check) and legacy examples (for viewing) | Japanese |

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
  the manifest holds the stage result as `world_contract`. The contract is generated item by item, with at most
  `max_item_attempts` attempts per item (`config/world/contract.yaml`, default 4); failure to comply fails the run
  (`engine.structured.max_attempts` applies to the judge calls inside the contract). Resume reuses the recorded result.
- **Exploration**: evaluates empty, unexpanded, uncaused, thin and underserved areas and selects an
  operator × target with a UCB1 / Thompson bandit. Operators are `premise`, `expand`, `zoom`, `cause`,
  `perspective`, `history` and `document`. Acceptance and the number of remade items update the bandit.
- **EntityBuilder** (`src/world/builder.py`): builds one entity field by field. Code assigns the ID, scale,
  parent and operation-specific relations. A type fixed by the operation needs no generation. Facts start
  with a measurement and a proper noun, then add objects, procedures and periods according to scale;
  each fact is generated and checked against its requested kind. A final review checks the assembled entity
  and requests repairs to specific names, summaries or facts. Defaults are four attempts per item and
  two repair rounds after review (`build` in `config/world/explore.yaml`). If the attempts for a fact's text are
  used up, or `restatement_check` judges the text a restatement of an existing fact (the remaining text attempts are
  then skipped), that fact is rebuilt from its elements, at most once per fact, with extra attempts for each of `fact_element` and `fact_text`
  (by default up to eight attempts in total per step for the same fact).
- **Entity graph**: stores types, names, axes, summaries, facts, relations and provenance on the hierarchy
  `world → region → settlement → district → site → detail` (`world/graph.json`). Generation uses bounded local context.
- **Output contracts**: `generate_structured` validates JSON Schema from `config/schemas/`, and detects
  placeholder values and schema echoes. It tries format conversion of malformed outputs and deterministically
  checks that converted free-form strings and numbers (including numeric enum values) occur in the source output;
  string enum values are excluded from this check. Unresolved violations trigger content
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
- **Budgets and stopping**: exploration stops with `coverage_met` once all world-level criteria hold. Iterations,
  wall time, generation calls, an exhausted frontier and consecutive exceptions also stop it. Brief, axes and
  contract generation occur outside the exploration call budget and have structured-output attempt limits.
  Checkpoints support resuming.

#### Per-item criteria (`config/world/criteria.yaml`)

An entity is accepted if it passes the item checks and review that apply to it. `breadth`, `depth` and `scale` are world-level criteria: when they are unmet, exploration continues, and meeting all of them is the `coverage_met` stop condition. `level` is
where the criterion applies (`entity`, `world`, or `both`); `method` is the main way it is checked (`structure` =
structural check, `rule` = deterministic rule, `judge` = model judgement).

| Criterion | level / method | What it checks |
|---|---|---|
| `faithful` | both / structure | Derived from input statements or local entities with an explained derivation; the world stays faithful to the input |
| `no_outside_premises` | entity / judge | Units and calendar markers obey the contract; real-world systems and proper names are allowed only when the original input specifies them |
| `breadth` | world / structure | The world covers the areas (axes) derived from the input |
| `depth` | world / structure | The world explains underlying causes and mechanisms (causation, history) |
| `scale` | world / structure | The world connects facts across its scale layers |
| `detail` | entity / structure | Every fact supplies its kind-specific fields and includes them in its text; proper names are new, measurements carry a value and a non-time unit, periods carry a calendar marker and value |
| `objective` | entity / judge | Names use the output language's script; explanations use objective reference language without quoted speech, personal narration or narrative voice |
| `consistent` | both / judge | Fields obey schemas, numeric facts do not contradict existing facts, relations avoid self-reference, entities have no contradictions |
| `new_information` | entity / rule | Each fact adds information absent from every existing fact. A proper name must also be absent from the input, brief, local context, existing names and contract terms. A number repeats an existing one only when its (value, unit) pair and subject both match. The text must not equal or nearly equal an existing fact (character 3-gram Jaccard at or above `duplicate_jaccard` = 0.8) nor restate it in other words |

The restatement judgement is made by the judge model, which compares a fact with up to `restatement_candidates` (5)
existing facts that have the largest character 3-gram Jaccard with it.

#### Judge model (`engine.judge_model` / `--judge-model`)

The tasks that rely on model judgement (`real_world_check` for outside real-world systems, `review` of the assembled
entity, and `restatement_check`) can be pinned to a model other than the generation model. Set `engine.judge_model` in
`config/ollama_config.yaml` or pass `--judge-model`; empty means the generation model. Pinning the judge lets different
generation models be compared under the same judgement. On resume, the run's judge model is carried over only if
neither `--model` nor `--vision-model` is given; if either is given, the carry-over is dropped and
`engine.judge_model` (empty means the generation model) is used, so pass `--judge-model` again to keep a judge pinned
on the CLI. Judge accuracy is measured by `scripts/validate_judges.py`
with the cases in `tests/fixtures/judge_cases/` (it connects to a real model, so CI does not run it). The model
comparison example pinned the judge to `qwen3.8:27b`.

#### World-level criteria and stopping (`config/world/world_criteria.yaml`)

Exploration stops with the stop reason `coverage_met` once all world-level criteria hold. The values express the goal
and are not lowered to let a model pass.

| Criterion | Threshold | Meaning |
|---|---|---|
| `faithful` | 1.0 | Share of input statements used as provenance |
| `breadth.axes` | 1.0 | Share of axes that have their required count (`max(1, ceil(axis weight × per_weight))`, `per_weight` = 3; e.g. weight 0.34 needs 2) |
| `breadth.perspective` | 1 | Number of entities created by the `perspective` operator |
| `depth.relations` | 0.3 | Share of non-world entities connected by a causal relation (`causes` / `affects`) |
| `depth.history` | 1 | Number of entities created by the `history` operator |
| `scale.<scale>` | 1 each | Minimum entities per scale: world, region, settlement, district, site, detail (`min_entities`) |
| `scale.chain` | yes | An unbroken parent chain from world to detail |

While `selection.focus_unmet` (`config/world/explore.yaml`, default true) is on, candidates that fill unmet criteria
are chosen first (candidates for a world-level shortfall, plus candidates for an axis shortfall while `breadth.axes`
is unmet).

#### Parallel builds (`parallel.builds` / `--parallel-builds`)

`parallel.builds` in `config/world/explore.yaml` (default 4) sets how many entities are built concurrently.
For single generation and resume, `--parallel-builds` overrides it. Batches (`--runs 2` or more) are not given
`--parallel-builds`; they use `parallel.builds` from the config file. They are settled in selection order; from the second one on, each is re-checked before settling
against what was committed in the meantime (duplicates and the like), and an entity that fails the re-check is rejected.

Caution: depending on the model, Ollama processes only one request at a time (see `n_seq_max` in the server log
`~/.ollama/logs/server.log`). In that case set it to 1: parallel builds are not faster and cause more rejections at
settling.

#### When the backend does not respond

- When a generation call times out or fails to connect, Ollama is probed for liveness (`GET /api/tags`); if it does not answer, the call fails.
- `server.call_deadline_seconds` (`config/ollama_config.yaml`, default 1800) caps a single Ollama call, retries included; beyond it the call fails.
  It does not apply to Anthropic, which uses `anthropic.timeout` and `anthropic.max_retries` (there is no equivalent total-time cap including retries).
- During exploration, if the backend does not respond, the run saves a checkpoint, waits, and probes again at intervals of
  60, 120, 240, 480 and then 600 seconds. When the backend answers, the iteration is redone.
- If no iteration settles for longer than `engine.backend_wait_max_seconds` (default 7200 seconds), the run exits with
  code 75 and logs the resume command (`--choice 2 --run-id <run_id>`). This holds for single generation and resume.
  In a batch (`--runs 2` or more), the wait-limit exception is recorded as a failed run and the batch moves on to the
  next world; the batch exits with code 1.

#### Example for reading the terms

Take the fictional input "two settlements share one water source". A world axis is an area of inquiry such as water allocation, institutions or daily life; an entity is a settlement or an organization that handles allocation; zoom is the operation that descends from a settlement to districts, sites and details. Provenance is the relation between statements explicit in the input and settings generated from them. For example, an allocation system the input does not mention is treated as distinct from facts the input states.

This example explains the terms of the [operators](src/world/operators.py) and the graph; it is not a default input, a fixed genre or measured output. Meeting the criteria does not guarantee that a work is complete or that its content is factual in the real world.

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
| `--parallel-builds` | Entities built concurrently | `parallel.builds` in `config/world/explore.yaml` (4) |

`--parallel-builds` applies to single generation and resume only (batches with `--runs 2` or more use `parallel.builds`). Set it to the number of requests the backend can serve at once. `1` builds one entity at a time (see the caution under "Parallel builds" above).

Other arguments: `--model` (generation model), `--judge-model` (judge model), `--vision-model` (for `--image`),
`--backend ollama|anthropic`, `--seed`, `--output-dir`, `--runs N` (N independent worlds from the same input),
`--run-id`, `--choice 2` (resume). Model names come from the config file or arguments; they are never fixed in code.

#### Resuming

```bash
# Resume (run id is the <run_id> in output/world_<run_id>/)
python example_run.py --choice 2 --run-id <run_id>
```

Resuming carries over the budget the run started with (its effective values). Only the arguments you give
(for example `--max-iterations 100`) override it, and the overrides are recorded in `budget.resume_overrides` in the manifest.

```bash
# Resume with an overridden budget
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
- [`examples/`](examples/README.md) contains runs of the current engine (model comparison, threshold check) and legacy output for viewing. The engine does not reference them.
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
