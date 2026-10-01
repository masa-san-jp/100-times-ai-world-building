# 100 TIMES AI WORLD BUILDING — エンジン設計仕様書

**バージョン**: v3.0
**対象**: 入力から世界設定資料を自律的に生成・検証・深化するエンジン（Ollama 既定、Anthropic 任意）
**位置づけ**: 旧 v2.x（物語を生成する Phase 0〜6 のパイプライン）の設計は撤去しました。旧クラウド版ノートブックの
設計は [DESIGN_SPEC.md](DESIGN_SPEC.md)（旧版）にあります。

> **検証状況**：テストは決定的なフェイクバックエンドのみです。実機のローカルモデルでのエンドツーエンド実行は未確認です
> （[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)）。

---

## 1. 目的と原則

利用者の入力（形式自由）だけを起点に、**物語制作の土台になる世界設定資料**を、人の介入なしに生成・検証・深化し続ける。

| 性質 | 意味 | 実現する仕組み |
|---|---|---|
| 広がり | 周縁・他者・無関係な領域まで存在する | 入力から決める軸と重み、`perspective` |
| 深み | 各要素に因果と歴史の地層がある | `cause` / `history`、由来の記録 |
| スケール感 | 世界から個人の一日までの階層 | スケール階層、`zoom` |
| ディテール | 場面に置ける具体物 | 具体性の検証、`document` |

あわせて、客観的な説明文（百科事典・設定解説の調子）を必ず出力する（客観性の検証と描画規則）。

共通の制約：

- **作例を仕組みに持ち込まない**：`examples/` をコード・設定・プロンプト・テストから参照しない（`tests/test_example_run.py`
  の混入ガード）。テスト入力はテスト内の最小の合成入力。
- **入力に前提を持ち込まない**：ジャンル・時代・舞台・技術・主人公像を埋め込まない。世界の内容は入力かそこから導いた
  前提だけに由来する。
- **物語を書かない**：主人公・プロット・章・小説本文は生成しない（`tests/test_old_phases_removed.py` が旧語彙を検査）。
- **モデル非依存**：モデル名・モデル固有パラメータは設定ファイルと `src/llm/` の抽象で扱う。1 回の生成で扱う文脈を小さく保つ。
- **テスト**：実 LLM に接続しない決定的なフェイクバックエンドで検証する。

## 2. 全体構成

```
example_run.py ─► src/pipeline.py (Pipeline) ─► src/world/explore.py (run_world_engine)
                  │  設定・バックエンド/モデル解決      ├─ input.py   入力の受け入れ
                  │  パッケージ・マニフェスト           ├─ axes.py    世界の軸
                  │  品質レポート                       ├─ graph.py   エンティティグラフ
src/batch.py ─────┘                                     ├─ operators.py 生成オペレータ
src/quality.py / src/compare.py（レポート）             ├─ verify.py / reward.py 検証器と報酬
src/llm/（Ollama / Anthropic / フェイク）               └─ render.py  世界設定資料の描画
src/checkpoint_manager.py / src/run_manifest.py（再開・記録）
```

`Pipeline` は薄いラッパー（API は `Pipeline(...)`, `.run(input)`, `.resume()`, `.check_prerequisites()`）で、生成ロジックは
持たない。担当は、設定からのバックエンド/モデルの解決、世界パッケージ 1 つ分のディレクトリ、`run_manifest.json`、
全呼び出しへの生成既定値の適用（`ConfiguredBackend`）、実行後の品質レポートのみ。旧 `Pipeline` の Phase メソッドは撤去した。

## 3. 入力の受け入れ（`src/world/input.py`）

原文（UTF-8 のテキスト / YAML / JSON、任意の形）と任意の画像を `input/` に保存する。画像はビジョンモデルで観察可能な
事項だけを記述し、原文に付加する。モデルは `statements`（引用付きの明示事項）、`open_questions`、`constraints` だけを
返し、**引用は原文の連続部分文字列であることをコードが検査**し、合致しないものは捨てる。ID はコードが振る。
結果は `input/input_brief.json`。事項を推測・補完しない。

## 4. 世界の軸（`src/world/axes.py`）

`config/world/domains.yaml` の汎用領域カタログ（地理と気候・生態・自然法則・技術・資源と経済・政治と権力・規範・信仰と思想・言語と文字・親族と共同体・日常・労働・教育と知・
芸術とメディア・歴史・外部との関係の 16 領域。どの世界にも当てはまる）は**被覆のチェックリスト**であり、特定の世界の雛形ではない。モデルは入力に照らして各領域の
重みと世界固有の意味付けを提案し、コードが検証する：すべてのカタログ領域が軸になる／重みの下限（0 にならない）／
根拠となる事項がない軸の重みの上限／入力が加える領域の数の上限。結果は `world/world_axes.json`
（`id`・`name`・`meaning`・`weight`・`grounds`・`origin`）。後段は軸を `id` で参照し、重みで探索の配分を決める。

## 5. エンティティグラフ（`src/world/graph.py`）

世界は素の `dict`（JSON と往復可能）のグラフ `world/graph.json`。

- **スケール階層**：`world → region → settlement → district → site → detail`。親のスケールは子より上でなければならず、
  `world` だけが親を持たない。
- **エンティティ**：`id`（コードが `eN` を採番）、`type`（place / group / institution / person / object / practice /
  event / concept / document）、`name`、`axes`、`scale`、`parent`、`relations`（located_in / causes / affects / opposes /
  derived_from / part_of / uses / produces / governs / related_to など）、`summary`、`facts`、`provenance`、`scores`。
  人物は住人であり物語上の役割を持たない。
- **事実**：`kind`（proper_noun / number / period / procedure / object / expression / other）と `text` と事実ごとの由来。
- **由来（provenance）**：入力の記述 ID（`statement_ids`）、導出元エンティティ（`derived_from`）、理由（`reason`）。
  入力にも既存の世界にも根拠のないものは採用されない。
- **検証**：スキーマと参照整合性（`validate_graph`）。書き込みは原子的（一時ファイル + rename）で、コミットごとに
  `world_graph` チェックポイントを残す。
- **局所文脈**：`local_context` が対象の周囲（親・兄弟・関連・事実）を件数・文字数で上限を切って返し、1 回の生成の
  文脈を世界の大きさに依存させない。

## 6. オペレータ（`src/world/operators.py`）

| オペレータ | 対象 | 新エンティティの置き場 |
|---|---|---|
| `premise` | 世界全体 | `world` スケール |
| `expand` | 既存エンティティ | 同じスケール・同じ親（兄弟） |
| `zoom` | 既存エンティティ | 1 つ下のスケール・対象を親に |
| `cause` | 既存エンティティ | 兄弟 + `causes` 関係（なぜそうなっているか） |
| `perspective` | 既存エンティティ | 兄弟 + `related_to`（別の立場・周縁から見た姿） |
| `history` | 既存エンティティ | 兄弟 + `affects`（歴史の地層） |
| `document` | 既存エンティティ | 兄弟 + `related_to`（条文・記録・掲示などの世界内文書） |

1 回の呼び出しは対象の局所文脈と少数の事項・軸だけをプロンプトに入れ、`n` 個の候補を 1 度に求める。**ID・スケール・
親・構造的な関係はコードが付与**し、由来のない候補は捨て、スケールが下がるほど増える最低限の具体的事実数を課す。
プロンプトは `config/prompts/world/operators.yaml`。基準未満の候補は `revision.yaml` の批評付きプロンプトで書き直す。

## 7. 検証器と報酬（`src/world/verify.py`, `reward.py`）

各検証器は 0〜1（1 が最良）のスコアと、どのフィールドをなぜ減点したかの構造化された減点記録を返す。既定は決定的で、
LLM 審査や埋め込み類似度は任意のプラグイン。言語依存の語彙は `config/world/language_rules.yaml`（言語コード別）。

| 検証器 | 見るもの |
|---|---|
| genericity（凡庸さ） | 同じスロットを**入力なし**で生成した対照（モデルの事前分布）との文字 3-gram 類似度。近い記述を減点。対照は `world/contrasts.json` にキャッシュ |
| provenance | 由来の有無、参照先の実在、導出の理由 |
| specificity | 固有名詞・数値・事実の種類の多様さ、抽象語の密度 |
| consistency | グラフの整合、自己関係、関係の矛盾、所在・時間順序・数値の矛盾 |
| objectivity | 引用・一人称・二人称・感嘆・疑問・修辞（説明文の調子から外れる表現） |
| novelty | 既存のエンティティとの重複 |

報酬は重み付き平均（`config/world/reward.yaml` の `weights`）。候補は、全検証器が各しきい値以上で、かつ合計報酬が
`thresholds.total` 以上のとき合格。スコアは採用されたエンティティの `scores` に保存される。

## 8. 自律探索ループ（`src/world/explore.py`）

1 反復：

1. **フロンティア評価**：`empty`（空）／`unexpanded`（下のスケールがない）／`uncaused`（因果がない）／`thin`（事実が少ない）／
   `axis_gap`（軸の被覆が重みに比べ不足）／`low_score`（保存済みスコアが低い）の各項目を、不足度（deficit）付きで列挙。
2. **選択**：`config/world/explore.yaml` の `operators` で各種別に許す操作を結び、（操作 × 種別）を腕とするバンディット
   （UCB1 または Thompson、ε ランダム）が（フロンティア項目 × 操作）を選ぶ。腕の価値は平均報酬（事前分布付き）で、
   項目の不足度と軸の重みが事前値として加わる。乱数は 1 つの seed 付き `random.Random`。
3. **生成**：選んだオペレータで候補を複数生成。
4. **採点**：検証器で採点し、報酬を算出。
5. **採否**：最良候補が合格ならそれを採用。不合格なら減点記録を批評として添えて書き直し（最大 `max_rewrites` 回）。
   どれも合格しなければ破棄し、腕の報酬を `discard_reward` として記録。
6. **反映**：採用したエンティティをグラフにコミットし、チェックポイント（グラフ・バンディット・乱数状態・ログ行数）を保存。

**停止条件**（`stop_reason`）：`coverage_met`（全軸が下限件数以上・指定スケールまで各 N 件以上・平均報酬が目標以上）、
`max_iterations`、`max_wall_seconds`、`max_generation_calls`、`frontier_exhausted`。予算は設定とエンジン呼び出しの
引数（CLI の `--max-*`）で指定する。途中で止まっても、再開時に乱数状態とログ位置を復元して同じ経過をたどる
（コミット済みでチェックポイント未保存の変更は巻き戻す）。第 1 段階のため、モデルの重みは更新しない。

**選好ログ**（`world/preferences.jsonl`）：すべての候補（スコア・減点・採否・書き直し元）と反復の記録を追記。
`extract_preference_pairs` が（プロンプト, 採用, 却下）の組を取り出す。第 2 段階（DPO など）の入力形式までを実装し、
学習そのものは行わない。

## 9. 出力（`src/world/render.py`）

テンプレートによる決定的な描画で、モデルは呼ばず、世界モデルにない文章は書かない。見出しは
`config/world/render_labels.yaml`（`meta.language` で選択、なければ `en`）。

```text
final/world.json         機械可読の世界モデル（正規化したグラフ + 軸 + 実行サマリ）
final/world_bible/       README.md（概要・軸・目次）, scales/<scale>.md, entities/<id>.md,
                         glossary.md, timeline.md, documents.md
final/world_report.md    停止理由・被覆・スケール別件数・報酬分布・凡庸さで落とした候補の例
```

## 10. 基盤

- **バックエンド抽象**（`src/llm/`）：`LLMBackend`（`generate_json` / `generate_text` / `check_ready`）。Ollama
  （`src/ollama_client.py`）と Anthropic（`src/llm/anthropic_client.py`）、テスト用の決定的フェイク（`src/llm/fake.py`）。
  `src/llm/factory.py` が設定からクライアントを組み立てる。
- **設定**（`config/ollama_config.yaml`）：`backend`、`server`、`model.name`、`models.vision`、`anthropic`、`generation`
  （全生成呼び出しの既定値）、`engine.explore` / `engine.operator`（上書き）、`checkpointing`、`logging`、`output`。
  エンジン本体の設定は `config/world/`（`domains` / `explore` / `reward` / `language_rules` / `render_labels` / `quality`）。
- **モデルの役割**：「生成」と「画像読み取り（ビジョン）」の 2 つ。旧版の role 別モデル（structured / story / reference）は、
  物語・参考資料の生成とともに廃止した。Anthropic では単一のモデルが両方を担う。
- **マニフェスト**（`run_manifest.json`）：`engine_config`（探索・オペレータ・生成既定値）、`budget`（要求値と有効値）、
  `run_seed`、`backend` / `model` / `models`、設定ファイルのハッシュと設定・プロンプトのスナップショット、`input`、
  `status`、`stop_reason`、`iterations`、`counters`。再開時は保存済みの seed・バックエンド・モデルを引き継ぐ。
- **チェックポイント**（`src/checkpoint_manager.py`）：`world_graph` と `world_explore`。
- **バッチ**（`src/batch.py`）：同じ入力から N 個の独立した世界（各自の package・seed・チェックポイント）。
  `batch_manifest.json`（各世界の seed・停止理由・状態）と、2 個以上なら `comparison.md`。1 つの失敗は他を止めない。
- **品質レポート**（`src/quality.py`）：軸の被覆、スケールの深さ、報酬の分布、凡庸さ、由来、重複、探索の状態。
  **比較レポート**（`src/compare.py`）：世界ごとの要約と、世界同士の重複（同名・近似エンティティ・共通の固有名詞・軸の類似）。

## 11. 制約と未検証事項

- 実機のローカルモデルでのエンドツーエンド実行は未確認（所要時間・出力品質・20B 級モデルでの安定性）。
- 凡庸さの対照は同じモデルの「入力なし」生成なので、モデルの事前分布そのものが偏っている場合の限界は残る。
- 類似度は決定的な文字 3-gram が既定。意味的な類似（埋め込み）や LLM 審査はプラグイン点だけ用意している。
- 旧パイプライン（物語生成）の出力は新エンジンから読まない。

## 12. 将来の拡張

- 選好ログを使った DPO などによるモデル調整（第 2 段階）。
- 埋め込みによる類似度、LLM 審査の導入。
- 実機での長時間実行の検証と、そこで得た知見による設定の見直し。
