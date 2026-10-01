# 100 TIMES AI WORLD BUILDING — 設計仕様書

> **旧版**：この文書は旧クラウド版ノートブック（[`legacy/`](legacy/)）の設計です。物語（プロット・章・小説）を生成する旧パイプラインを
> 対象としており、現在のエンジンの設計ではありません。現在の設計は [DESIGN_SPEC_LOCAL.md](DESIGN_SPEC_LOCAL.md) を参照してください。

**バージョン**: v1.2
**作成日**: 2025-06-01
**著者**: masa-jp-art
**文書ステータス**: 初版

---

## 目次

1. [プロジェクト概要](#1-プロジェクト概要)
2. [設計思想](#2-設計思想)
3. [システムアーキテクチャ](#3-システムアーキテクチャ)
4. [技術スタック](#4-技術スタック)
5. [データフロー](#5-データフロー)
6. [パイプライン詳細設計](#6-パイプライン詳細設計)
7. [API設計](#7-api設計)
8. [データ構造](#8-データ構造)
9. [出力仕様](#9-出力仕様)
10. [制約事項・前提条件](#10-制約事項前提条件)
11. [将来の拡張性](#11-将来の拡張性)

---

## 1. プロジェクト概要

### 1.1 目的

「100 TIMES AI WORLD BUILDING」は、ユーザーが持つ断片的なコンテクスト（文脈・着想）を起点に、AIを活用して**100倍に拡張**し、重厚な長編小説と包括的な設定資料集を自動生成するワークフローシステムである。

### 1.2 解決する課題

- 創作の初期段階における「アイデアの種はあるが、世界観を広げられない」という障壁の解消
- 多層的な世界設定（社会構造、歴史、文化、生活環境など）を一貫性を保ちながら構築する困難さの軽減
- 長編小説執筆において必要な膨大な設定資料の作成コストの削減

### 1.3 ターゲットユーザー

- 小説家・物語作家
- ゲームデザイナー・シナリオライター
- TRPG（テーブルトークRPG）のゲームマスター
- AIを活用した創作に関心のあるクリエイター全般

### 1.4 成果物

| 成果物 | 内容 |
|--------|------|
| 長編小説（全10章） | Claude APIによる重厚な文体の物語本文 |
| 設定資料集 | キャラクター、プロット、世界観、社会構造等の包括的資料 |
| 中間生成データ | 100個の願望/能力/役割リスト、プロットタイプ等の構造化データ |

---

## 2. 設計思想

### 2.1 核となる概念：「100倍拡張」

本システムの根幹は、ユーザーが提供する最小限の入力（コンテクスト）を段階的に拡張し、最終的に100倍以上の情報量を持つ物語世界を構築する点にある。

```
ユーザーコンテクスト（1）
  → 100個の願望 × 100個の能力 × 100個の役割（100倍拡張）
    → 多層的な世界設定（数十カテゴリ）
      → 10章の詳細プロット
        → 全10章の長編小説 + 設定資料集
```

### 2.2 設計原則

1. **段階的拡張（Staged Expansion）**: 各ステージの出力が次のステージの入力となる積み上げ型アーキテクチャ
2. **抽象解釈（Abstract Interpretation）**: ユーザーコンテクストを直接引用せず、抽象的に解釈・再構築することで創発的な世界を生成
3. **モデル適材適所（Model Specialization）**: 構造化データ生成にはOpenAI（JSON出力）、長文創作にはClaude（高品質な文章生成）を使い分け
4. **累積的コンテクスト（Cumulative Context）**: 後段のプロンプトには前段の全生成結果を累積的に投入し、世界観の一貫性を維持

---

## 3. システムアーキテクチャ

### 3.1 全体構成

```
┌─────────────────────────────────────────────────────────┐
│                   実行環境                               │
│              Google Colab / Jupyter Notebook              │
│                                                          │
│  ┌──────────┐    ┌──────────────────────────────────┐    │
│  │  ユーザー  │───▶│       メインノートブック            │    │
│  │  入力     │    │  (20250601-...-v1.2.ipynb)        │    │
│  └──────────┘    └────────┬───────────┬──────────────┘    │
│                           │           │                   │
│              ┌────────────▼──┐   ┌────▼──────────┐       │
│              │  OpenAI API    │   │ Anthropic API  │       │
│              │  (o4-mini)     │   │ (Claude 3.7    │       │
│              │                │   │  Sonnet)       │       │
│              │ ・JSON構造化   │   │ ・長文生成     │       │
│              │ ・データ生成   │   │ ・小説執筆     │       │
│              │ ・キーワード   │   │ ・資料集作成   │       │
│              │   抽出         │   │                │       │
│              └───────────────┘   └────────────────┘       │
│                                                          │
│  ┌──────────────────────────────────────────────────┐    │
│  │               外部ツール（前処理）                  │    │
│  │   ChatGPT カスタムGPT                              │    │
│  │   ・ユーザーコンテクスト抽出用                      │    │
│  │   ・画像コンテクスト抽出用                          │    │
│  └──────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### 3.2 ノートブック構成（10セル）

| セル番号 | 種別 | 内容 |
|----------|------|------|
| Cell 0 | Markdown | プロジェクト説明・リンク・概念図 |
| Cell 1 | Markdown | 概念図画像（Base64埋め込み） |
| Cell 2 | Code | ライブラリインストール・インポート・API設定・関数定義 |
| Cell 3 | Markdown | ユーザーコンテクスト入力の説明 |
| Cell 4 | Code | `user_context`変数への代入（ユーザー手動入力） |
| Cell 5 | Markdown | コンテクスト拡張セクション見出し |
| Cell 6 | Code | 100倍拡張処理（願望・能力・役割・プロットタイプ・キャラクター・世界設定の全生成） |
| Cell 7 | Markdown | 物語と設定資料集出力セクション見出し |
| Cell 8 | Code | プロット分割・キーワード抽出・参考資料検索 |
| Cell 9 | Code | 小説本文生成（全10章）・設定資料集生成 |

---

## 4. 技術スタック

### 4.1 言語・フレームワーク

| 技術要素 | 採用技術 | 用途 |
|----------|----------|------|
| プログラミング言語 | Python 3.x | ワークフロー制御 |
| 実行環境 | Google Colab（推奨）/ Jupyter Notebook | インタラクティブ実行 |
| AIモデル（構造化データ） | OpenAI o4-mini | JSON形式での構造化データ生成 |
| AIモデル（長文生成） | Anthropic Claude 3.7 Sonnet | 小説本文・設定資料集の生成 |

### 4.2 ライブラリ

| ライブラリ | バージョン | 用途 |
|------------|-----------|------|
| `openai` | 最新 | OpenAI API クライアント |
| `anthropic` | 最新 | Anthropic Claude API クライアント |
| `json` | 標準ライブラリ | JSON パース |
| `yaml` | PyYAML | YAML 変換・出力 |
| `random` | 標準ライブラリ | ランダム選択 |
| `IPython` | Colab内蔵 | Markdown表示 |

---

## 5. データフロー

### 5.1 パイプライン全体フロー

```
[Phase 0: 前処理]
  ChatGPT カスタムGPT
    └─▶ ユーザーコンテクスト (user_context)

[Phase 1: 100倍拡張]  ── OpenAI o4-mini ──
  user_context
    ├─▶ desire_list       （100個の願望）
    ├─▶ ability_list      （100個の能力）
    ├─▶ role_list          （100個の役割）
    ├─▶ plottype_list      （10個のプロットタイプ）
    └─▶ plottype           （選択されたプロットタイプ）

[Phase 2: キャラクター生成]  ── OpenAI o4-mini ──
  user_context + plottype + desire_list + ability_list + role_list
    └─▶ characters_list   （4人の主要登場人物）

[Phase 3: 世界構築]  ── OpenAI o4-mini ──  ※累積的にコンテクスト投入
  plottype
    └─▶ events            （物理的事象）
  events
    └─▶ observation       （観測手段）
  events + observation
    └─▶ interpretation    （解釈体系）
  events + observation + interpretation
    └─▶ media             （記録媒体）
  events + observation + interpretation + media
    └─▶ important_past_events （歴史的事件10件）
  上記全て
    └─▶ social_structure  （社会構造）
  上記全て
    └─▶ living_environment（生活環境）
  上記全て
    └─▶ social_groups     （社会的集団10グループ）
  上記全て
    └─▶ people_list       （100人のペルソナ）
  上記全て
    └─▶ future_scenarios  （未来シナリオ）

[Phase 4: プロット生成]  ── OpenAI o4-mini ──
  全世界設定 + user_context + plottype + characters_list
    └─▶ plot              （10章の詳細プロット）
  plot
    ├─▶ plot_1 ～ plot_10          （章別プロット）
    ├─▶ plot_keywords_1 ～ _10     （章別キーワード）
    └─▶ plot_reference_1 ～ _10    （章別参考資料）

[Phase 5: 小説生成]  ── Anthropic Claude ──
  characters_list + plot_n + plot_reference_n  (n=1..10)
    └─▶ story_1 ～ story_10  （全10章の小説本文）

[Phase 6: 設定資料集生成]  ── Anthropic Claude ──
  各世界設定データ
    └─▶ reference_characters_list  （キャラクター資料）
    └─▶ reference_plot             （プロット資料）
    └─▶ reference_user_context     （根源的感情の分析）
    └─▶ reference_events           （事象資料）
    └─▶ reference_observation      （観測資料）
    └─▶ reference_interpretation   （解釈資料）
    └─▶ reference_media            （記録媒体資料）
    └─▶ reference_important_past_events  （歴史資料）
    └─▶ reference_social_structure       （社会構造資料）
    └─▶ reference_living_environment     （生活環境資料）
    └─▶ reference_social_groups          （社会集団資料）
    └─▶ reference_people_list            （ペルソナ資料）
    └─▶ reference_future_scenarios       （未来シナリオ資料）
    └─▶ reference_desire_list            （願望リスト資料）
    └─▶ reference_ability_list           （能力リスト資料）
    └─▶ reference_role_list              （役割リスト資料）
    └─▶ reference_plottype_list          （プロットタイプ資料）
```

### 5.2 API呼び出し回数

| フェーズ | API | 呼び出し回数 |
|----------|-----|-------------|
| Phase 1: 100倍拡張 | OpenAI | 5回 |
| Phase 2: キャラクター生成 | OpenAI | 1回 |
| Phase 3: 世界構築 | OpenAI | 10回 |
| Phase 4: プロット生成 | OpenAI | 1 + 10 + 10 + 10 = 31回 |
| Phase 5: 小説生成 | Claude | 10回 |
| Phase 6: 設定資料集生成 | Claude | 17回 |
| **合計** | **OpenAI: 47回 / Claude: 27回** | **74回** |

---

## 6. パイプライン詳細設計

### 6.1 Phase 0: ユーザーコンテクスト抽出（前処理）

**実行環境**: ChatGPT カスタムGPT（ノートブック外部）

| 項目 | 内容 |
|------|------|
| 入力 | ユーザーとの対話 or 画像 |
| 処理 | ランダムな質問を通じてコンテクストを抽出・構造化 |
| 出力 | YAML形式のユーザーコンテクスト |
| 対応GPT（テキスト） | `g-68280b3861008191b250b17b7fe76d88` |
| 対応GPT（画像） | `g-682dc76781808191a29bdf9d5f55ff6d` |

ユーザーは抽出結果を `user_context` 変数に手動で代入する。

### 6.2 Phase 1: 100倍拡張

**使用API**: OpenAI o4-mini（JSON出力モード）

#### 6.2.1 願望リスト生成（desire_list）

- **入力**: `user_context`
- **プロンプト指示**: コンテクストを抽象的に解釈して拡張し、100個の願望を生成
- **出力形式**: JSON → YAML変換

#### 6.2.2 能力リスト生成（ability_list）

- **入力**: `user_context`
- **プロンプト指示**: コンテクストを抽象的に解釈して拡張し、100個の能力を生成
- **出力形式**: JSON → YAML変換

#### 6.2.3 役割リスト生成（role_list）

- **入力**: `user_context`
- **プロンプト指示**: コンテクストを抽象的に解釈して拡張し、100個の役割を生成
- **出力形式**: JSON → YAML変換

#### 6.2.4 プロットタイプリスト生成（plottype_list）

- **入力**: なし（一般知識から生成）
- **プロンプト指示**: 10個の神話・伝承・物語の典型的な様式をリスト化
- **出力スキーマ**: plot_type, Core structure, Required events, Character requirements, Temporal design principles, Types of conflict, Climax conditions, Principles of temp, Typical story setting
- **出力形式**: JSON → YAML変換

#### 6.2.5 プロットタイプ選択（plottype）

- **入力**: `user_context` + `plottype_list`
- **プロンプト指示**: コンテクストに最適なプロットタイプを1つ選択し、必要に応じて拡張・修正
- **出力形式**: JSON → YAML変換

### 6.3 Phase 2: キャラクター生成

**使用API**: OpenAI o4-mini（JSON出力モード）

- **入力**: `user_context` + `plottype` + `desire_list` + `ability_list` + `role_list`
- **出力**: 4人の主要登場人物

| 役割 | 説明 |
|------|------|
| protagonist（主人公） | 物語の中心人物。冒険と試練を通じて成長する |
| messenger（使者） | 主人公に知恵や助言を与える存在 |
| supporter（支援者） | 主人公をサポートし、新たな視点を与える存在 |
| adversary（敵対者） | 主人公が克服すべき障害や敵対者 |

各キャラクターの属性: name, short introduction, description

キャラクターには願望・能力・役割リストからそれぞれランダムに1つが割り当てられる。

### 6.4 Phase 3: 世界構築

**使用API**: OpenAI o4-mini（JSON出力モード）

累積的にコンテクストを投入し、世界の各レイヤーを順次構築する。

#### 6.4.1 生成順序と依存関係

```
events ─────────────────────────────────┐
  │                                      │
  ▼                                      │
observation ────────────────────────┐    │
  │                                  │    │
  ▼                                  │    │
interpretation ────────────────┐    │    │
  │                              │    │    │
  ▼                              │    │    │
media ────────────────────┐    │    │    │
  │                          │    │    │    │
  ▼                          ▼    ▼    ▼    ▼
important_past_events ──▶ social_structure
                              │
                              ▼
                      living_environment
                              │
                              ▼
                        social_groups
                              │
                              ▼
                         people_list
                              │
                              ▼
                      future_scenarios
```

#### 6.4.2 世界設定カテゴリ詳細

| カテゴリ | 変数名 | 主要項目 |
|----------|--------|----------|
| 物理的事象 | `events` | 宇宙空間（時空間、相互作用、量子場、エントロピー）、地表（地殻変動、地表構造、生態系） |
| 観測手段 | `observation` | 感覚入力、測定装置、予測モデル、説明理論 |
| 解釈体系 | `interpretation` | 神話伝承、幾何的・哲学的解釈、経験主義的解釈、相対論的・量子論的解釈、情報・計算的解釈 |
| 記録媒体 | `media` | 生体媒体、静的刻記媒体、静的筆記媒体、アナログ信号媒体、デジタル媒体 |
| 歴史 | `important_past_events` | 有史以来の最重要イベント10件 |
| 社会構造 | `social_structure` | 政治体制、社会階層、経済システム、文化・宗教、法律・治安、教育・技術、環境・生態系、インフラ・交通、生活様式、コミュニケーション、芸術・娯楽（12大カテゴリ、各数十の詳細指標） |
| 生活環境 | `living_environment` | 家族形態、地域コミュニティ、ライフステージ、社会的モラル、ジェンダー役割、健康・衛生、日常行動パターン等 |
| 社会的集団 | `social_groups` | 10個の社会集団（名称、構成員、目的、課題、活動、特徴） |
| ペルソナ | `people_list` | 100人の生活者（氏名、年齢、性別、居住地、家族構成、所属、役割、収入、ライフスタイル、趣味、価値観、目標、悩み、人間関係） |
| 未来シナリオ | `future_scenarios` | 楽観的・悲観的・中間の3シナリオ（50〜100年後） |

### 6.5 Phase 4: プロット生成

**使用API**: OpenAI o4-mini（JSON出力モード）

#### 6.5.1 10章プロット生成（plot）

- **入力**: 全世界設定データ + `user_context` + `plottype` + `characters_list`
- **各章の構造要素**:
  - 物語世界の状況
  - 発生した事件
  - 主人公の受動的感情
  - 主人公の意思と行動
  - 状況の変化
  - 次章への伏線（第1〜9章）
  - 物語の締めくくり（第10章）

#### 6.5.2 章別分割（plot_1 〜 plot_10）

- plotから各章部分をYAML形式で分離抽出（10回のAPI呼び出し）

#### 6.5.3 キーワード抽出（plot_keywords_1 〜 plot_keywords_10）

- 各章プロットから最大10個の重要キーワードを抽出（10回のAPI呼び出し）

#### 6.5.4 参考資料検索（plot_reference_1 〜 plot_reference_10）

- 各章のキーワードに基づき、全世界設定データから関連する要素を最大20個抽出（10回のAPI呼び出し）

### 6.6 Phase 5: 小説生成

**使用API**: Anthropic Claude 3.7 Sonnet（`max_tokens=16000`, `temperature=1`）

- **入力（章ごと）**: `characters_list` + `plot_reference_n` + `plot_n`
- **システムプロンプト**: 「常に表現力豊かな日本語で出力します。」
- **生成指示**:
  - 現代を代表する小説家として執筆
  - 出力可能な最大トークン数を使用
  - 重厚長大な小説を出力
  - 鑑賞者が実際に体験していると感じられる深みとディテール
  - 余計な説明文を排除し物語本文のみ
  - 途中で止めず最後まで出力
- **繰り返し**: 全10章を順次生成

### 6.7 Phase 6: 設定資料集生成

**使用API**: Anthropic Claude 3.7 Sonnet（`max_tokens=16000`, `temperature=1`）

- **共通プロンプト指示**:
  - 資料を分析し抽象的に解釈
  - Markdown形式の構造化された日本語資料集を作成
  - 解釈や補足情報を加えて詳細かつ網羅的に
  - 可読性と読みやすさを重視
- **生成する資料**: 17種類（キャラクター設定、プロット、根源的感情、事象、観測、解釈、記録媒体、歴史、社会構造、生活環境、社会集団、ペルソナ、未来シナリオ、願望リスト、能力リスト、役割リスト、プロットタイプ）

---

## 7. API設計

### 7.1 ヘルパー関数仕様

#### `o4(prompt) → str`

OpenAI APIを使用した構造化データ生成関数。

| 項目 | 値 |
|------|-----|
| モデル | `o4-mini` |
| システムプロンプト | 「常に日本語で応答します。常にjson形式で応答します。」 |
| レスポンス形式 | `{"type": "json_object"}` |
| 後処理 | JSON → Python dict → YAML文字列変換 |
| エラーハンドリング | 例外時にエラーメッセージ文字列を返却 |

#### `o4md(prompt) → str`

OpenAI APIを使用したMarkdown出力関数。

| 項目 | 値 |
|------|-----|
| モデル | `o4-mini` |
| API | `client.responses.create`（Responses API） |
| システムプロンプト | 「常に日本語で応答します。常にMarkdown形式で応答します。」 |
| 後処理 | `response.output_text`をそのまま返却 |

#### `claude(prompt) → str`

Anthropic Claude APIを使用した長文生成関数。

| 項目 | 値 |
|------|-----|
| モデル | `claude-3-7-sonnet-latest` |
| 最大トークン数 | 16,000 |
| temperature | 1（最大の創造性） |
| システムプロンプト | 「常に表現力豊かな日本語で出力します。」 |
| 後処理 | `message.content[0].text`を返却 |

#### `data_to_markdown(data, indent=0) → str`

Python辞書/リストをMarkdownリスト形式に変換するユーティリティ関数。

- 辞書のキーは`**太字**`で表示
- リストの要素はインデックス付き（`[0]`, `[1]`, ...）で表示
- ネストされた構造は再帰的に処理

#### `rich_print(m) → None`

Markdown文字列をJupyterノートブック上でリッチ表示する関数。

- `IPython.display.Markdown`を使用

---

## 8. データ構造

### 8.1 中間データ形式

本システムでは、すべての中間データがPythonのグローバル変数として保持される。

| 変数名 | 型 | 形式 | 内容 |
|--------|----|------|------|
| `user_context` | str | YAML | ユーザーの入力コンテクスト |
| `desire_list` | str | YAML | 100個の願望リスト |
| `ability_list` | str | YAML | 100個の能力リスト |
| `role_list` | str | YAML | 100個の役割リスト |
| `plottype_list` | str | YAML | 10個のプロットタイプ |
| `plottype` | str | YAML | 選択されたプロットタイプ |
| `characters_list` | str | YAML | 4人の主要登場人物 |
| `events` | str | YAML | 物理的事象 |
| `observation` | str | YAML | 観測手段 |
| `interpretation` | str | YAML | 解釈体系 |
| `media` | str | YAML | 記録媒体 |
| `important_past_events` | str | YAML | 歴史的事件 |
| `social_structure` | str | YAML | 社会構造 |
| `living_environment` | str | YAML | 生活環境 |
| `social_groups` | str | YAML | 社会的集団 |
| `people_list` | str | YAML | 100人のペルソナ |
| `future_scenarios` | str | YAML | 未来シナリオ |
| `plot` | str | YAML | 10章の統合プロット |
| `plot_1` 〜 `plot_10` | str | YAML | 章別プロット |
| `plot_keywords_1` 〜 `_10` | str | YAML | 章別キーワード |
| `plot_reference_1` 〜 `_10` | str | YAML | 章別参考資料 |
| `story_1` 〜 `story_10` | str | テキスト | 小説本文（各章） |
| `reference_*` (17種) | str | Markdown | 設定資料集 |

### 8.2 キャラクターデータスキーマ

```yaml
characters_list:
  - protagonist:
      name: "名前"
      short_introduction: "短い紹介文"
      description: "詳細な説明（外見・人物像・魅力）"
  - messenger:
      name: "名前"
      short_introduction: "短い紹介文"
      description: "詳細な説明"
  - supporter:
      name: "名前"
      short_introduction: "短い紹介文"
      description: "詳細な説明"
  - adversary:
      name: "名前"
      short_introduction: "短い紹介文"
      description: "詳細な説明"
```

### 8.3 プロットデータスキーマ（各章）

```yaml
chapter_N:
  situation: "物語世界の状況"
  events: "発生した事件"
  protagonist_emotions: "主人公の受動的感情"
  protagonist_actions: "主人公の意思と行動"
  situation_change: "状況の変化"
  foreshadowing: "次章への伏線"  # 第1〜9章のみ
```

---

## 9. 出力仕様

### 9.1 小説出力

| 項目 | 仕様 |
|------|------|
| 構成 | 全10章 |
| 各章の最大トークン数 | 16,000トークン（Claude側制限） |
| 言語 | 日本語 |
| 文体 | 重厚長大な文学的表現 |
| 出力形式 | プレーンテキスト（Jupyter上でリッチ表示） |

### 9.2 設定資料集出力

| 項目 | 仕様 |
|------|------|
| 形式 | Markdown |
| 資料数 | 17種類 |
| 各資料の最大トークン数 | 16,000トークン |
| 内容 | 抽象的に解釈・補足された構造化資料 |

### 9.3 出力カテゴリ一覧

1. キャラクター設定（外見的特徴の詳細説明付き）
2. 作品のプロット（テーマ・成長アーク・モチーフ分析付き）
3. キャラクターとプロットに込められている根源的な感情
4. 物語世界における事象
5. 物語世界における事象の観測手段
6. 物語世界における事象の解釈
7. 物語世界における記録媒体
8. 物語世界の過去の重要なイベント
9. 物語世界の現在の社会構造
10. 物語世界の現在の生活環境
11. 物語世界の現在の社会的集団
12. 物語世界に暮らす人々のペルソナ
13. 物語世界における未来のシナリオ
14. 物語の登場人物が秘めている願望のリスト
15. 物語の登場人物が持っている能力のリスト
16. 物語の登場人物が担う役割のリスト
17. プロットタイプのリスト

---

## 10. 制約事項・前提条件

### 10.1 技術的制約

| 制約 | 詳細 |
|------|------|
| APIレート制限 | OpenAI/Anthropic各社のAPIレート制限に依存 |
| トークン制限 | Claude: 最大16,000トークン/リクエスト |
| コンテクストウィンドウ | 後段のプロンプトは累積データにより巨大化する可能性あり |
| 実行時間 | 74回のAPI呼び出しにより、完全な実行には相当の時間を要する |
| コスト | API利用料金が発生（特にClaude 27回×16,000トークンは高コスト） |

### 10.2 機能的制約

| 制約 | 詳細 |
|------|------|
| 状態管理 | グローバル変数による管理のため、セル実行順序に依存 |
| 永続化 | 中間データの自動保存機能なし（ノートブックの状態に依存） |
| エラーリカバリ | 個別API呼び出しの失敗時、エラーメッセージ文字列が変数に代入される（後続処理に影響） |
| 再現性 | `temperature=1`のためClaude出力は毎回異なる。OpenAI側もモデルの非決定性あり |
| 言語 | 日本語のみ対応 |

### 10.3 前提条件

- 有効なOpenAI APIキーを保有していること
- 有効なAnthropic APIキーを保有していること
- 十分なAPI利用枠（クレジット）があること
- Google Colabまたは互換のJupyter環境が利用可能であること
- ユーザーコンテクストの事前抽出が完了していること（ChatGPT カスタムGPT使用）

---

## 11. 将来の拡張性

### 11.1 考えられる改善点

| 領域 | 改善案 |
|------|--------|
| 状態管理 | グローバル変数からデータクラス/辞書への移行 |
| 永続化 | 中間生成データのJSON/YAMLファイル自動保存 |
| エラーハンドリング | リトライ機構、チェックポイント機能の追加 |
| 並列化 | 独立したAPI呼び出しの並列実行による高速化 |
| UI | Streamlit/GradioによるインタラクティブなWebアプリ化 |
| モデル選択 | ユーザーによるモデル選択の動的切り替え |
| 多言語対応 | 日本語以外の言語での世界構築対応 |
| コスト最適化 | キャッシュ機構による重複API呼び出しの削減 |
| 出力形式 | Google Docs / PDF / EPUB等への直接エクスポート |

### 11.2 v1.2での改善点（リリースノート）

- プロンプトの改善
- 設定資料出力部分のモデルをClaudeに変更

---

*本文書は「100 TIMES AI WORLD BUILDING v1.2」のソースコードおよびREADMEを基に作成された設計仕様書です。*
