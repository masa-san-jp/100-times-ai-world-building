# 探索レポート

[世界設定資料](world_bible/README.md)

## 実行の概要

- 停止理由: 反復の上限に達した
- 反復回数: 12
- 生成呼び出し数: 169
- 採用: 5
- 破棄: 7

## Structured output

| Task | Calls | Attempts to compliance | Failures | Seconds | Modes (attempts) | Placeholder violations | Schema echo | Conversions tried | Conversions succeeded | Fidelity failures | Schema failures |
| --- | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| input_brief | 1 | {"1": 1} | 0 | 12.119 | {"constrained": 1} | 0 | 0 | 0 | 0 | 0 | 0 |
| world_axes | 1 | {"1": 1} | 0 | 23.679 | {"constrained": 1} | 0 | 0 | 0 | 0 | 0 | 0 |
| world_contract | 1 | {"2": 1} | 0 | 20.188 | {"constrained": 1, "unconstrained": 1} | 0 | 0 | 0 | 0 | 0 | 0 |
| type | 12 | {"1": 12} | 0 | 74.155 | {"unconstrained": 12} | 0 | 0 | 0 | 0 | 0 | 0 |
| grounding | 12 | {"2": 1, "1": 11} | 0 | 60.417 | {"unconstrained": 15} | 0 | 0 | 2 | 0 | 0 | 2 |
| name | 12 | {"1": 12} | 0 | 22.555 | {"unconstrained": 12} | 0 | 0 | 0 | 0 | 0 | 0 |
| axes | 12 | {"1": 12} | 0 | 32.694 | {"unconstrained": 12} | 0 | 0 | 0 | 0 | 0 | 0 |
| summary | 18 | {"1": 18} | 0 | 127.922 | {"unconstrained": 18} | 0 | 0 | 0 | 0 | 0 | 0 |
| fact | 60 | {"1": 60} | 0 | 256.238 | {"unconstrained": 60} | 0 | 0 | 0 | 0 | 0 | 0 |
| fact_check | 30 | {"1": 30} | 0 | 181.893 | {"unconstrained": 30} | 0 | 0 | 0 | 0 | 0 | 0 |
| review | 5 | {"1": 5} | 0 | 17.337 | {"unconstrained": 5} | 0 | 0 | 0 | 0 | 0 | 0 |
| relations | 4 | {"1": 4} | 0 | 24.081 | {"unconstrained": 5} | 0 | 0 | 1 | 1 | 0 | 0 |

## Entity building

- Accepted entities: 5
- Failed entities: 7
- Failed entities by step: {"fact": 7}

| Step | Calls | Attempt distribution | Failures | Reasons by criterion |
| --- | ---: | --- | ---: | --- |
| type | 12 | {"1": 12} | 0 | {} |
| grounding | 15 | {"1": 12} | 0 | {} |
| name | 12 | {"1": 12} | 0 | {} |
| axes | 12 | {"1": 12} | 0 | {} |
| summary | 18 | {"1": 8, "2": 3, "4": 1} | 0 | {"informative": {"character 3-gram overlap must be <= 0.6": 3}, "objective": {"quoted speech in the summary; move quotations into facts": 3}, "no_story": {"quoted speech in the summary; move quotations into facts": 3}} |
| fact | 60 | {"1": 8, "2": 7, "3": 2, "4": 8} | 7 | {"informative": {"character 3-gram overlap must be <= 0.6": 42}, "specific": {"number requires its value and non-time measurement unit in the fact text": 1}} |
| fact_check | 30 | {"1": 30} | 0 | {} |
| review | 5 | {"1": 5} | 0 | {} |
| relations | 5 | {"1": 4} | 0 | {} |

## 世界の契約生成

- 結果: success
- 試行回数: 2
- 1: the JSON object must be str, bytes or bytearray, not NoneType

- 暦・紀年: 潮時暦
- 紀年の起点: 水の循環と塩の採掘サイクルに基づく計測。
- 日付の表記: 乾期初月, 水汲期, 盛塩期, 結塩時
- 技術の能力と限界: 塩の採掘と水の輸送に特化した技術体系。
- 定義された装置・手法: 塩の採掘と選別, 地下水路の維持・管理, 重い資材の運搬, 水の貯蔵と分配
- 使用する測定単位: kg (塩の重量。最大積載単位。), lit (水の体積。導水路からの汲み上げ量。), 尺 (距離の単位。移動や採掘範囲の計測。)
- 制度・社会の枠組みと限界: 塩の採掘と水資源の配分を巡る二大共同体の構造。
- 定義された規則・組織: 採掘組合 (塩の採掘権を基盤とする労働者集団。経済活動の主体。), 水番家系 (古来より導水路の管理と水の配給を担う家系。水資源の管理者。), 資源分配評議会 (水と塩の利用に関する一時的な合議体。対立構造を緩和する場。)

## 被覆

- 被覆の状態: 未達

### 軸ごとの被覆と重みの比較

| 軸 | 重み | 配分比率 | エンティティ数 | エンティティ比率 |
| --- | --- | --- | --- | --- |
| 芸術・娯楽・メディア | 0.05 | 0.8% | 0 | 0.0% |
| 信仰と思想 | 0.05 | 0.8% | 0 | 0.0% |
| 日々の暮らし | 0.05 | 0.8% | 0 | 0.0% |
| 生態 | 0.05 | 0.8% | 0 | 0.0% |
| 教育と知識 | 0.05 | 0.8% | 0 | 0.0% |
| 外部との関係 | 0.05 | 0.8% | 0 | 0.0% |
| 地理と気候 | 0.90 | 15.0% | 5 | 33.3% |
| 歴史 | 0.05 | 0.8% | 0 | 0.0% |
| 血縁と共同体 | 0.90 | 15.0% | 0 | 0.0% |
| 言語と文字 | 0.05 | 0.8% | 1 | 6.7% |
| 法と規範 | 0.05 | 0.8% | 0 | 0.0% |
| 自然の法則と法則外の理 | 0.80 | 13.3% | 0 | 0.0% |
| 職業と労働 | 0.90 | 15.0% | 0 | 0.0% |
| 政治と権力 | 1.00 | 16.7% | 4 | 26.7% |
| 資源と経済 | 1.00 | 16.7% | 5 | 33.3% |
| 技術と道具 | 0.05 | 0.8% | 0 | 0.0% |

## スケールごとの件数

| スケール | 件数 |
| --- | --- |
| 世界 | 1 |
| 地域 | 1 |
| 集落 | 1 |
| 地区 | 2 |
| 施設 | 0 |
| 細部 | 0 |
| 合計 | 5 |

## 報酬の分布

| 採点項目 | 件数 | 平均 | 最小 | 最大 |
| --- | --- | --- | --- | --- |
| 報酬（合計） | 5 | 0.975 | 0.966 | 1.000 |

### 合計報酬のヒストグラム

- 0.0 - 0.2: 0
- 0.2 - 0.4: 0
- 0.4 - 0.6: 0
- 0.6 - 0.8: 0
- 0.8 - 1.0: 5

## 凡庸さで捨てられた候補

凡庸さで捨てられた候補はありません。
