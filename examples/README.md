# 作例 — まずここを見る

このディレクトリは、リポジトリを見た人が実際の生成物を確認するための入口です。

`examples/` は `output/` と同じ成果物パッケージ構造を持つ、確認済み作例の置き場です。
`output/` は実行中に生成される成果物パッケージの置き場で、Git管理しません。

実際に使う場合は、先に[ローカル版の使い方](../README_LOCAL.md)を読み、
動作確認には[完全作例](neo_tokyo_complete/)の入力コンテクストを使えます。

- `examples/<example-name>/`: 内容を確認して残す1つの作例パッケージ。
- `output/world_<run_id>/`: 生成された1つの世界パッケージ。

作例ディレクトリは人間が読める名前を付けます。内部の `run_id` は一意な実行識別子で、
作品名ではありません。作例の説明はこのREADMEに書き、生成条件は各
`run_manifest.json` で確認します。

## 収録内容

```text
examples/
└── neo_tokyo_complete/    # output/world_<run_id> と同じ構造の完全作例
    ├── input/
    ├── intermediate/
    ├── checkpoints/
    ├── final/
    │   ├── novels/
    │   └── references/
    └── run_manifest.json
```

各作例ディレクトリは、`output/world_<run_id>/` と同じ成果物パッケージです。
入力、途中生成物、チェックポイント、最終成果物を1つのディレクトリにまとめます。

## 現在収録されている作例

このREADMEに、成功した作例とその生成条件を一覧化しています。
現在の代表例は、未来の東京とAIの共存をテーマにした完全パイプライン生成です。

- [作例パッケージ](neo_tokyo_complete/)
- [入力コンテキスト](neo_tokyo_complete/input/user_context.yaml)
- [願望リスト](neo_tokyo_complete/intermediate/01_desire_list.yaml)
- [能力リスト](neo_tokyo_complete/intermediate/02_ability_list.yaml)
- [役割リスト](neo_tokyo_complete/intermediate/03_role_list.yaml)
- [プロット候補](neo_tokyo_complete/intermediate/04_plottype_list.yaml)
- [選択プロット](neo_tokyo_complete/intermediate/05_plottype.yaml)
- [小説本文（全10章）](neo_tokyo_complete/final/novels/)
- [設定資料集（17ファイル）](neo_tokyo_complete/final/references/)
- [生成条件](neo_tokyo_complete/run_manifest.json)

## 実行例

Phase 1だけを作例として保存する場合:

```bash
python example_run.py --choice 1 \
  --context-file examples/neo_tokyo_complete/input/user_context.yaml \
  --model gpt-oss:20b-q4 \
  --output-dir output
```

全工程を10周して保存する場合:

```bash
python example_run.py --choice 2 --runs 10 --yes \
  --context-file examples/neo_tokyo_complete/input/user_context.yaml \
  --model gpt-oss:20b-q4 \
  --output-dir output
```

10回バッチの実機検証はまだ行っていません。所要時間はモデルとハードウェアに依存します。

同じ入力から再実行したい場合は `--seed` を追加します。生成後の
`output/world_*/run_manifest.json` に記録されたモデル・設定ハッシュも確認できます。
作例として残す場合は、内容を確認した出力パッケージを人間が読める名前で
`examples/<example-name>/` に格納します。

```bash
python example_run.py --choice 1 \
  --context-file examples/neo_tokyo_complete/input/user_context.yaml \
  --seed 20260828 \
  --output-dir output
```

作例としてコミットする前に、個人情報・秘密情報・意図しない画像や大容量の
チェックポイントを確認してください。未選別の実験結果は引き続き `output/` に
置く運用を推奨します。
