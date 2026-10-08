# 探索レポート

[世界設定資料](world_bible/README.md)

## 実行の概要

- 停止理由: 反復の上限に達した
- 反復回数: 12
- 生成呼び出し数: 149
- 採用: 5
- 破棄: 7

## Structured output

| Task | Calls | Attempts to compliance | Failures | Seconds | Modes (attempts) | Placeholder violations | Schema echo | Conversions tried | Conversions succeeded | Fidelity failures | Schema failures |
| --- | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| input_brief | 1 | {"2": 1} | 0 | 74.833 | {"constrained": 1, "unconstrained": 1} | 0 | 0 | 0 | 0 | 0 | 0 |
| world_axes | 1 | {"1": 1} | 0 | 94.091 | {"unconstrained": 1} | 0 | 0 | 0 | 0 | 0 | 0 |
| world_contract | 1 | {"1": 1} | 0 | 177.376 | {"unconstrained": 1} | 0 | 0 | 0 | 0 | 0 | 0 |
| type | 11 | {"1": 11} | 0 | 324.931 | {"unconstrained": 12} | 0 | 0 | 1 | 1 | 0 | 0 |
| grounding | 12 | {"1": 12} | 0 | 380.605 | {"unconstrained": 12} | 0 | 0 | 0 | 0 | 0 | 0 |
| name | 14 | {"1": 14} | 0 | 133.936 | {"unconstrained": 14} | 0 | 0 | 0 | 0 | 0 | 0 |
| axes | 12 | {"1": 12} | 0 | 175.919 | {"unconstrained": 12} | 0 | 0 | 0 | 0 | 0 | 0 |
| summary | 19 | {"1": 19} | 0 | 994.235 | {"unconstrained": 19} | 0 | 0 | 0 | 0 | 0 | 0 |
| fact | 50 | {"1": 50} | 0 | 1425.654 | {"unconstrained": 52} | 0 | 0 | 2 | 1 | 0 | 1 |
| fact_check | 15 | {"1": 15} | 0 | 247.877 | {"unconstrained": 15} | 0 | 0 | 0 | 0 | 0 | 0 |
| review | 8 | {"1": 8} | 0 | 550.310 | {"unconstrained": 8} | 0 | 0 | 0 | 0 | 0 | 0 |
| relations | 5 | {"1": 5} | 0 | 148.470 | {"unconstrained": 5} | 0 | 0 | 0 | 0 | 0 | 0 |

## Entity building

- Accepted entities: 5
- Failed entities: 7
- Failed entities by step: {"fact": 7}

| Step | Calls | Attempt distribution | Failures | Reasons by criterion |
| --- | ---: | --- | ---: | --- |
| type | 12 | {"1": 11} | 0 | {} |
| grounding | 12 | {"1": 12} | 0 | {} |
| name | 14 | {"1": 11, "3": 1} | 0 | {} |
| axes | 12 | {"1": 12} | 0 | {} |
| summary | 19 | {"1": 7, "2": 3, "3": 2} | 0 | {"informative": {"character 3-gram overlap must be <= 0.6": 4}, "objective": {"quoted speech in the summary; move quotations into facts": 1}, "no_story": {"quoted speech in the summary; move quotations into facts": 1}} |
| fact | 52 | {"1": 7, "4": 9, "3": 1, "2": 2} | 7 | {"fits_world": {"units and calendar markers must belong to the contract": 19}, "informative": {"character 3-gram overlap must be <= 0.6": 17}} |
| fact_check | 15 | {"1": 15} | 0 | {} |
| review | 8 | {"1": 5, "3": 1} | 0 | {"consistent": {"summary states that 水源監督会 monitors water quality and supply, but no fact in the entity supports this claim.": 1, "Entity name '塩砂丘域' does not correspond to the institution described in the facts, which refers to '水源監督会'.; Summary describes activities of '水源監督会', inconsistent with the entity name '塩砂丘域'.; Fact 0 discusses '水源監督会', conflicting with the entity's name '塩砂丘域'.; Fact 1 discusses '水源監督会', conflicting with the entity's name '塩砂丘域'.": 1, "Salt production figure 50000 kg conflicts with world contract which reports 52000 kg.": 1}, "fits_world": {"institution 水源監督会 is not listed in the world contract, so the entity does not fit the defined world structure.": 1, "": 1, "false verdict has no issue identifying an affected field": 1, "Salt production figure 50000 kg does not match the value specified in world contract (52000 kg) and thus does not fit the world contract.": 1}} |
| relations | 5 | {"1": 5} | 0 | {} |

## 世界の契約生成

- 結果: success
- 試行回数: 1

- 暦・紀年: 盆地暦
- 紀年の起点: 盆地の塩採掘と導水路管理に基づく
- 日付の表記: 採掘週, 水祭, 乾季, 雨季
- 技術の能力と限界: 古い導水路と塩採掘機械の保守・運用。限界は老朽化と水質管理。
- 定義された装置・手法: 地下水抽出・導水路保守, 塩結晶化プロセス制御, 水質検査・監視
- 使用する測定単位: m3d (毎日消費水量), kg (塩生産量)
- 制度・社会の枠組みと限界: 塩の採掘で成り立つ内陸盆地。雨ほぼ無、導水路から水を得る。採掘組合と水番家系の長期対立が社会構造を形作る。
- 定義された規則・組織: 採掘組合 (採掘権管理と資源分配に責任), 水番家系 (導水路管理権保持と保守担当), 共管委員会 (争い解決と資源配分を協議), 自治議会 (住民意見を代表し政策調整)

## 被覆

- 被覆の状態: 未達

### 軸ごとの被覆と重みの比較

| 軸 | 重み | 配分比率 | エンティティ数 | エンティティ比率 |
| --- | --- | --- | --- | --- |
| 芸術・娯楽・メディア | 0.05 | 0.7% | 0 | 0.0% |
| 信仰と思想 | 0.05 | 0.7% | 1 | 7.1% |
| 日々の暮らし | 0.70 | 9.5% | 1 | 7.1% |
| 生態 | 0.60 | 8.1% | 0 | 0.0% |
| 教育と知識 | 0.05 | 0.7% | 0 | 0.0% |
| 外部との関係 | 0.05 | 0.7% | 0 | 0.0% |
| 地理と気候 | 0.80 | 10.8% | 1 | 7.1% |
| 歴史 | 0.50 | 6.8% | 1 | 7.1% |
| 血縁と共同体 | 0.70 | 9.5% | 1 | 7.1% |
| 言語と文字 | 0.05 | 0.7% | 0 | 0.0% |
| 法と規範 | 0.80 | 10.8% | 2 | 14.3% |
| 自然の法則と法則外の理 | 0.05 | 0.7% | 0 | 0.0% |
| 職業と労働 | 0.70 | 9.5% | 1 | 7.1% |
| 政治と権力 | 0.80 | 10.8% | 3 | 21.4% |
| 資源と経済 | 0.90 | 12.2% | 3 | 21.4% |
| 技術と道具 | 0.60 | 8.1% | 0 | 0.0% |

## スケールごとの件数

| スケール | 件数 |
| --- | --- |
| 世界 | 5 |
| 地域 | 0 |
| 集落 | 0 |
| 地区 | 0 |
| 施設 | 0 |
| 細部 | 0 |
| 合計 | 5 |

## 報酬の分布

| 採点項目 | 件数 | 平均 | 最小 | 最大 |
| --- | --- | --- | --- | --- |
| 報酬（合計） | 5 | 0.962 | 0.827 | 1.000 |

### 合計報酬のヒストグラム

- 0.0 - 0.2: 0
- 0.2 - 0.4: 0
- 0.4 - 0.6: 0
- 0.6 - 0.8: 0
- 0.8 - 1.0: 5

## 凡庸さで捨てられた候補

凡庸さで捨てられた候補はありません。
