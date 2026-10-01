# 作例（旧パイプラインの出力）

> **注意**：このディレクトリの作例は、物語（キャラクター・プロット・章・小説本文）を生成していた**旧パイプライン**の
> 出力です。現在の世界設定資料エンジン（`final/world.json` / `final/world_bible/` / `final/world_report.md`）の
> 出力ではなく、現在の構造・採点・レポートとも対応しません。過去の生成物を閲覧するために残しています。

作例は閲覧用です。仕組みの一部ではなく、コード・設定・プロンプト・テスト・ドキュメントの実行例から作例の内容を
参照してはいけません（`tests/test_example_run.py` の混入ガードが検査します）。実際に使う場合は
[利用ガイド](../README_LOCAL.md)を読み、自分で用意した入力で実行してください。

## 収録内容

```text
examples/
└── neo_tokyo_complete/    # 旧パイプラインの完全な出力（旧 Phase 0〜6）
    ├── input/
    ├── intermediate/      # 旧: 願望・能力・役割リスト、プロット、キャラクター、固定スキーマの世界項目
    ├── checkpoints/
    ├── final/
    │   ├── novels/        # 旧: 全 10 章の小説本文
    │   └── references/    # 旧: 設定資料 17 ファイル
    └── run_manifest.json
```

- [`neo_tokyo_complete/`](neo_tokyo_complete/)：未来の東京と AI の共存をテーマに、旧パイプラインを最後まで実行した出力。

## 現在のエンジンの出力

現在のエンジンは次の構造で出力します。詳細は [README_LOCAL.md](../README_LOCAL.md) を参照してください。

```text
output/world_<run_id>/
├── run_manifest.json
├── input/  world/  checkpoints/
├── quality_report.json/.md
└── final/
    ├── world.json
    ├── world_bible/
    └── world_report.md
```

作例として残す場合は、内容を確認した出力パッケージを人間が読める名前で `examples/<example-name>/` に格納します。
その前に、個人情報・秘密情報・意図しない画像や大容量のチェックポイントを確認してください。未選別の実験結果は
`output/` に置く運用を推奨します（`output/` は Git 管理しません）。
