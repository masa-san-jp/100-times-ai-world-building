# Neo Tokyo 完全作例

> **旧パイプラインの出力です。** 物語を生成していた旧 Phase 0〜6 の成果物で、現在の世界設定資料エンジンの出力ではありません（[examples/README.md](../README.md) を参照）。

未来の東京とAIの共存をテーマに、Phase 0〜6を最後まで実行した確認済みの作例です。
既存の入力コンテキストから続行して生成し、最終成果物まで揃えています。

```text
neo_tokyo_complete/
├── input/                  # 入力コンテキスト
├── intermediate/           # Phase 1〜4の途中生成物
├── checkpoints/            # 各フェーズの最新チェックポイント
├── final/
│   ├── novels/             # 全10章の本文
│   └── references/         # 設定資料17ファイル
└── run_manifest.json       # モデル、seed、設定、実行状態
```

`run_manifest.json` の `status` は `completed` です。各フェーズの出力はスキーマ検証済みで、
モデル応答が件数不足になった2項目は、補完内容をマニフェストの `completion_notes` に記録しています。
