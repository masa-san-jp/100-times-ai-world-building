# Implementation Status - 100 TIMES AI WORLD BUILDING

**Version**: v3.0 (world-setting engine)
**Status**: エンジンと基盤の移行は実装完了。**検証はフェイクバックエンドのみで、実機のローカルモデルでの
エンドツーエンド実行は未実施。**

---

## 検証状況（正直な現状）

| 項目 | 状況 |
|---|---|
| ユニット / 結合テスト（フェイクバックエンド） | 実施済み。`python -m pytest tests/ -q` が通る。CI は Python 3.11 / 3.12 / 3.13 |
| 非対話 CLI（`example_run.py --context-file ... --yes`）のエンドツーエンド（フェイク） | 実施済み（`tests/test_example_run.py`） |
| 実機の Ollama モデルでのエンドツーエンド実行 | **未実施**。所要時間、出力品質、20B 級モデルでの安定性は未確認 |
| Anthropic バックエンドでのエンドツーエンド実行 | **未実施**（クライアント自体の単体テストのみ） |
| バッチ（N 個の世界）の実機実行 | **未実施**（フェイクでは検証済み） |
| 凡庸さの対照が実モデルの事前分布を十分に捉えるか | **未確認** |

旧パイプライン（物語を生成する Phase 0〜6）の実機検証メモは、撤去とともに削除しました。

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

- 実モデルでの挙動は未確認（上表）。最初は `--max-iterations 5` など小さな予算で確かめる。
- 生成のサンプリング seed は制御しない（`--seed` は操作と対象の選択、バッチの世界ごとの seed を決める）。同じ seed でも、
  実モデルの出力は完全には再現しない。
- 類似度は文字 3-gram が既定。埋め込み類似度・LLM 審査は未導入（プラグイン点のみ）。
- 旧パイプラインの出力パッケージは再開・比較・品質レポートの対象外。

## 今後の課題

- 実機のローカルモデル（20B 級）での長時間実行と、それに基づく設定（`generation.candidates`、しきい値など）の調整。
- Anthropic バックエンドでの実行検証。
- 選好ログを使った DPO などによるモデル調整（第 2 段階）。
- 埋め込み類似度と LLM 審査の導入。
