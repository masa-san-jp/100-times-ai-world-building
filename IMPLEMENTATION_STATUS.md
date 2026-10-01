# Implementation Status - 100 TIMES AI WORLD BUILDING

**Version**: v3.0 (world-setting engine)
**Status**: エンジンと基盤の移行は実装完了。**実機（Ollama + 20B 級）での短い 1 回のスモーク実行を行い、
そこで見つかった問題への対処（#43）を入れた。修正後の実機での再実行と長時間実行は未実施。**

---

## 検証状況（正直な現状）

| 項目 | 状況 |
|---|---|
| ユニット / 結合テスト（フェイクバックエンド） | 実施済み。`python -m pytest tests/ -q` が通る。CI は Python 3.11 / 3.12 / 3.13 |
| 非対話 CLI（`example_run.py --context-file ... --yes`）のエンドツーエンド（フェイク） | 実施済み（`tests/test_example_run.py`） |
| 実機の Ollama モデルでのエンドツーエンド実行 | **短い 1 回のみ実施**（`gpt-oss:20b`、反復 4 回、約 12 分で完走）。品質の問題が見つかり #43 で対処した（下記）。**修正後の再実行と長時間実行は未実施** |
| Anthropic バックエンドでのエンドツーエンド実行 | **未実施**（クライアント自体の単体テストのみ） |
| バッチ（N 個の世界）の実機実行 | **未実施**（フェイクでは検証済み） |
| 凡庸さの対照が実モデルの事前分布を十分に捉えるか | **捉えられないと判明**（話題が外れるため）。#43 で「同じ話題の中でのありきたりさ」の測り方に作り替えた。修正後の実機での効果は未確認 |

旧パイプライン（物語を生成する Phase 0〜6）の実機検証メモは、撤去とともに削除しました。

---

## 実機での初回検証と #43 での対処

### 実行条件と結果

- バックエンド `ollama`、モデル `gpt-oss:20b`（設定ファイルの既定）。入力は内陸の盆地での暮らしと、水路の管理権をめぐる
  対立を日本語 2 文で書いたもの（作例とは無関係）。反復 4 回・約 12 分で最後まで完走した。
- 採用された 4 件はすべて報酬 1.0（全検証器が満点）だったが、内容は入力の言い換えが中心だった。

### 見つかった問題

| 問題 | 内容 |
|---|---|
| 採点が甘い | 名前が入力の語をなぞる（入力の地名をそのまま連結した名前）。事実は種類のラベルだけ満たす（一般名詞の `proper_noun`、数えただけの `number`）。入力なしの対照は話題がまったく別の内容になり、n-gram 類似度が常に低く、凡庸さの減点が一度も起きなかった |
| 深く掘られない | 4 件すべてスケール `world`。16 軸すべての不足度が 1.0 で `expand\|axis_gap` が毎回選ばれ、`zoom` は一度も選ばれなかった |
| 言語が混ざる | 日本語入力なのに、入力ブリーフの `text`、軸の `name` / `meaning`、レポートの軸名が英語 |

### 対処（#43）

| 項目 | 対処 |
|---|---|
| 凡庸さ | 同じスロットで独立に生成した候補どうしの収束（共有する語句を罰）、ブリーフ・局所文脈の言い換え（要約の新規 n-gram 比率）、入力の語でできた名前の検出を追加。入力なし対照は残すが重みを半分にした（`genericity.contrast_weight`） |
| 事実の実質 | `proper_noun` が入力の語の連結・短い一般名詞（CJK は 3 文字未満、英語は大文字なし）でないか、`number` が単位・比率・期間を伴う測定値か（数えただけの「3部門」型を除く）を決定的に検査し、空の事実は種類の網羅にも数えない。LLM 判定は実機バックエンドで既定有効（`engine.judge.enabled: auto`）、フェイクでは無効 |
| 深さ | フロンティアに `depth_need`（下位スケールの不足）を持たせ、`zoom` の事前確率に反映（`selection.depth_weight`）。`axis_gap` は `zoom` / `perspective` / `cause` で補い、対象は子スケールが最も空いている既存エンティティにした（世界スケールの兄弟は増やさない） |
| 言語 | ブリーフ・軸のプロンプトに入力言語での出力を指示（引用は原文のまま）。言語は `guess_language` か、`run_world_engine(language=...)` で指定する。領域カタログの `name` / `description` と「入力が触れていない」理由を `ja` / `en` で持ち、無い言語は `en`。レポートの軸名は保存された（現地語の）名前を使う |
| 報酬の再調整 | `specificity` の重みを 1.5 から 2.0、合計しきい値を 0.6 から 0.7 に。実機型の薄い候補はいずれかの検証器で閾値未満になり、独自の固有名詞・数値・仕組みを持つ候補は通る（`tests/test_world_realrun.py`） |

### 限界（正直に）

- 上記の対処は合成データとフェイクバックエンドでだけ確認した。**修正後に実機で再実行して効果を確かめてはいない。**
- 収束の測定は文字 n-gram なので、言い換えられた同じ発想は検出できない。埋め込み類似度は未導入。
- 3 文字未満の CJK の固有名詞を「一般名詞」とみなす簡易規則は、実在する短い固有名を誤って弱くしうる。LLM 判定で補う想定。
- LLM 判定は候補 1 件あたり生成呼び出しを 1 回増やす（予算 `max_generation_calls` に数える）。

---

## 実装完了状況（エピック #26 の子イシュー）

| # | 内容 | 主なファイル |
|---|---|---|
| #27 | 入力の受け入れ（形式自由・前提を足さない） | `src/world/input.py`, `config/prompts/input_brief.yaml` |
| #28 | 世界の軸と重み | `src/world/axes.py`, `config/world/domains.yaml`, `config/prompts/world_axes.yaml` |
| #29 | スケール階層と由来を持つエンティティグラフ | `src/world/graph.py` |
| #30 | 生成オペレータ（premise / expand / zoom / cause / perspective / history / document） | `src/world/operators.py`, `config/prompts/world/` |
| #31 | 凡庸さを罰する検証器と報酬 | `src/world/verify.py`, `src/world/reward.py`, `config/world/reward.yaml`, `language_rules.yaml` |
| #32 | 報酬で行動を選ぶ自律探索ループと選好ログ | `src/world/explore.py`, `config/world/explore.yaml` |
| #33 | 世界設定資料（Markdown と world.json）の出力 | `src/world/render.py`, `config/world/render_labels.yaml` |
| #34 | 新エンジンを既定にし、旧フェーズを撤去して基盤を移行 | 下記 |

### #34 で撤去したもの

- 4 人の役割キャラクター、プロットタイプの一覧と選択、プロット・章プロット・キーワード・参考資料検索、
  章本文（小説）と参考資料の生成。
- 入力を固定形に整形する旧 `context_extraction`、固定スキーマの世界項目（events / observation / interpretation / media など）と
  「50〜100 年後の未来シナリオ」。
- 100 倍の願望・能力・役割リスト（キャラクター・プロット生成にだけ使われていたため）。
- それらのプロンプト（`expansion` / `plot_generation` / `story_generation` / `world_building`）、設定セクション、テスト。
- 旧 `Pipeline` の Phase メソッド、role 別モデル（structured / story / reference）と `--structured-model` などの引数。
- ハードコードされたモデル一覧（`example_run.py`、`setup_check.py`、`OllamaClient` の既定モデル名）。

### #34 で移行したもの

| 対象 | 内容 |
|---|---|
| `example_run.py` | 新エンジンを実行。`--context-file` 必須（既定入力なし）、`--image`、`--backend`、`--model`、`--vision-model`、`--seed`、`--output-dir`、`--runs`、`--yes`、`--run-id`、予算（`--max-iterations` / `--max-minutes` / `--max-calls`）、再開（`--choice 2`）。メニューは 生成 / 再開 / 終了 |
| `src/pipeline.py` | 生成ロジックを持たない薄いラッパー（`Pipeline.run` / `.resume`）。バックエンド/モデルの解決、パッケージ、マニフェスト、品質レポート |
| `src/batch.py` | 同じ入力から N 個の独立した世界（各自の package と seed）、`batch_manifest.json`、`comparison.md` |
| `src/quality.py` | 新しい世界モデルが対象。軸の被覆・スケールの深さ・報酬の分布・凡庸さ・由来・重複・探索の状態 |
| `src/compare.py` | 世界ごとの要約と、世界同士の重複（同名・近似エンティティ・共通の固有名詞・軸の類似） |
| `run_manifest.json` | エンジン設定、予算、seed、バックエンド/モデル、入力、停止理由、反復数、カウンタ |
| `setup_check.py` | 新エンジンの前提（必須ファイル、エンジン設定の読み込み、バックエンド、設定中のモデル） |
| ノートブック | `legacy/` へ移動（旧版） |
| `examples/neo_tokyo_complete` | 旧パイプラインの出力として残し、`examples/README.md` に明記。仕組みからは参照しない |

---

## テスト

- 実 LLM に依存しない決定的なテスト（フェイクバックエンド、合成入力）。
- 旧語彙（`protagonist` / `plottype` / `chapter` / `novel` など）が `src/`・`config/` に残らないことを検査
  （`tests/test_old_phases_removed.py`）。`novelty`（新規性の検証器）は対象外。
- 混入ガード（`tests/test_example_run.py`）：`examples/` の内容が `src/`・`config/`・テスト・ノートブック（`legacy/` を含む）に
  入っていないことを検査。
- CI（`.github/workflows/tests.yml`）：`pytest tests/ -q` と flake8 の致命的エラー検査。

## 既知の制限事項

- 実モデルでの挙動は、短い 1 回の実行を除いて未確認（上表）。最初は `--max-iterations 5` など小さな予算で確かめる。
- 生成のサンプリング seed は制御しない（`--seed` は操作と対象の選択、バッチの世界ごとの seed を決める）。同じ seed でも、
  実モデルの出力は完全には再現しない。
- 類似度は文字 n-gram が既定。埋め込み類似度は未導入（プラグイン点のみ）。LLM 審査（`specificity`）は実機バックエンドで既定有効。
- 旧パイプラインの出力パッケージは再開・比較・品質レポートの対象外。

## 今後の課題

- #43 の修正後に、実機のローカルモデル（20B 級）で再実行して効果を確かめる。長時間実行と、それに基づく設定
  （`generation.candidates`、しきい値、`selection.depth_weight` など）の調整。
- Anthropic バックエンドでの実行検証。
- 選好ログを使った DPO などによるモデル調整（第 2 段階）。
- 埋め込み類似度の導入。
