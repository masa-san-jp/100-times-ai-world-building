# 探索レポート

[世界設定資料](world_bible/README.md)

## 実行の概要

- 生成モデル: gemma4:e4b
- 判定モデル: qwen3.8:27b
- 停止理由: 反復の上限に達した
- 反復回数: 12
- 生成呼び出し数: 222
- 採用: 6
- 破棄: 6

## Structured output

| Task | Model | Calls | Attempts to compliance | Failures | Seconds | Modes (attempts) | Placeholder violations | Schema echo | Conversions tried | Conversions succeeded | Fidelity failures | Schema failures |
| --- | --- | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| input_brief | gemma4:e4b | 1 | {"1": 1} | 0 | 23.159 | {"constrained": 1} | 0 | 0 | 0 | 0 | 0 | 0 |
| world_axes | gemma4:e4b | 1 | {"1": 1} | 0 | 140.045 | {"constrained": 1} | 0 | 0 | 0 | 0 | 0 | 0 |
| real_world_check | qwen3.8:27b | 35 | {"1": 35} | 0 | 2319.326 | {"constrained": 35} | 0 | 0 | 0 | 0 | 0 | 0 |
| contract/calendar_name | gemma4:e4b | 1 | {"2": 1} | 0 | 348.288 | {"constrained": 1, "unconstrained": 1} | 0 | 0 | 0 | 0 | 0 | 0 |
| contract/calendar_origin | gemma4:e4b | 1 | {"1": 1} | 0 | 29.088 | {"unconstrained": 1} | 0 | 0 | 0 | 0 | 0 | 0 |
| contract/calendar_marker | gemma4:e4b | 3 | {"1": 2, "3": 1} | 0 | 322.739 | {"unconstrained": 5} | 0 | 0 | 0 | 0 | 0 | 0 |
| contract/technology_description | gemma4:e4b | 1 | {"1": 1} | 0 | 12.251 | {"unconstrained": 1} | 0 | 0 | 0 | 0 | 0 | 0 |
| contract/capability | gemma4:e4b | 3 | {"1": 3} | 0 | 166.733 | {"unconstrained": 3} | 0 | 0 | 0 | 0 | 0 | 0 |
| contract/unit | gemma4:e4b | 3 | {"1": 3} | 0 | 190.345 | {"unconstrained": 3} | 0 | 0 | 0 | 0 | 0 | 0 |
| contract/society_description | gemma4:e4b | 1 | {"1": 1} | 0 | 11.338 | {"unconstrained": 1} | 0 | 0 | 0 | 0 | 0 | 0 |
| contract/institution | gemma4:e4b | 3 | {"1": 3} | 0 | 203.049 | {"unconstrained": 3} | 0 | 0 | 0 | 0 | 0 | 0 |
| type | gemma4:e4b | 12 | {"1": 12} | 0 | 286.156 | {"unconstrained": 13} | 0 | 0 | 1 | 1 | 0 | 0 |
| grounding | gemma4:e4b | 12 | {"1": 12} | 0 | 306.468 | {"unconstrained": 12} | 0 | 0 | 0 | 0 | 0 | 0 |
| name | gemma4:e4b | 12 | {"1": 12} | 0 | 100.608 | {"unconstrained": 12} | 0 | 0 | 0 | 0 | 0 | 0 |
| axes | gemma4:e4b | 12 | {"1": 12} | 0 | 213.775 | {"unconstrained": 12} | 0 | 0 | 0 | 0 | 0 | 0 |
| summary | gemma4:e4b | 13 | {"1": 13} | 0 | 529.965 | {"unconstrained": 13} | 0 | 0 | 0 | 0 | 0 | 0 |
| fact_element | gemma4:e4b | 42 | {"1": 42} | 0 | 777.218 | {"unconstrained": 42} | 0 | 0 | 0 | 0 | 0 | 0 |
| fact_text | gemma4:e4b | 44 | {"1": 44} | 0 | 816.241 | {"unconstrained": 44} | 0 | 0 | 0 | 0 | 0 | 0 |
| restatement_check | qwen3.8:27b | 39 | {"1": 39} | 0 | 2740.451 | {"constrained": 39} | 0 | 0 | 0 | 0 | 0 | 0 |
| review | qwen3.8:27b | 9 | {"1": 9} | 0 | 1114.866 | {"constrained": 9} | 0 | 0 | 0 | 0 | 0 | 0 |
| relations | gemma4:e4b | 5 | {"1": 5} | 0 | 308.004 | {"unconstrained": 6} | 0 | 0 | 1 | 1 | 0 | 0 |

## Entity building

- Accepted entities: 6
- Failed entities: 6
- Failed entities by step: {"fact_text": 6}

| Step | Calls | Attempt distribution | Failures | Reasons by criterion |
| --- | ---: | --- | ---: | --- |
| type | 13 | {"1": 12} | 0 | {} |
| grounding | 12 | {"1": 12} | 0 | {} |
| name | 12 | {"1": 12} | 0 | {} |
| real_world_check | 20 | {"1": 20} | 0 | {} |
| axes | 12 | {"1": 12} | 0 | {} |
| summary | 13 | {"1": 11, "2": 1} | 0 | {} |
| fact_element | 42 | {"1": 10, "3": 2, "2": 11, "4": 1} | 0 | {"new_information": {"(value, unit) pair (1, 塩石) with a near subject ('採掘された塩の純度') already appears in an existing fact": 2, "(value, unit) pair (1, 水滴) with a near subject ('導水路から汲み上げられた水の体積') already appears in an existing fact": 1, "(value, unit) pair (1, 塩水尺) with a near subject ('導水路の水位差') already appears in an existing fact": 1}} |
| fact_text | 44 | {"1": 10, "3": 6, "2": 8} | 6 | {"new_information": {"fact text restates an existing fact: '採掘された塩の純度の測定値は1塩石で、これは塩盆地における塩の採掘活動の基礎的な指標である。'": 1, "fact text restates an existing fact: '塩月暦に基づく「水番潮」の基準点では、採掘された塩の純度は最低1塩石以上である必要がある。'": 2, "fact text duplicates an existing fact: '塩月暦に基づく「水番潮」の基準点では、採掘された塩の純度は最低1塩石以上である必要がある。'": 1, "fact text restates an existing fact: '塩の汲み場において、導水路の水位差は「塩水尺」を用いて計測され、この計測は「塩月暦」の「水番潮」の基準点と関連付けられている。'": 1, "fact text restates an existing fact: '塩月暦の「水番潮」の基準に基づき、導水路の水位差は「塩水尺」を用いて1の測定値で計測される。'": 7, "fact text duplicates an existing fact: '塩月暦の「水番潮」の基準に基づき、導水路の水位差は「塩水尺」を用いて1の測定値で計測される。'": 1, "fact text restates an existing fact: '「石塩採掘坑口」には、導水路管理評議会が監視する「水門石」が設置されており、この石は塩月暦の「水番潮」の基準に基づき、導水路の水位差を「塩水尺」を用いて計測する起点となる。'": 1, "fact text duplicates an existing fact: '玄武の水路口には、「水番潮の監視弁」が設置され、その開閉は「水番血統評議会」の承認に基づき、導水路管理評議会が監視する「塩水尺」による計測と連動している。'": 1, "fact text restates an existing fact: '北壁水門石周辺の導水路の水位差は、塩月暦の「水番潮」の基準に基づき、「塩水尺」を用いて計測され、その管理は導水路管理評議会が行う。'": 3, "fact text restates an existing fact: '「水番血統評議会」の規範に基づき、導水路管理評議会は、「塩月暦」の「水番潮」の基準点において、導水路の水位の差の計測を「塩水尺」を用いて1の単位で行う。'": 2, "fact text duplicates an existing fact: '「水番血統評議会」の規範に基づき、導水路管理評議会は、「塩月暦」の「水番潮」の基準点において、導水路の水位の差の計測を「塩水尺」を用いて1の単位で行う。'": 1}, "no_outside_premises": {"units and calendar markers must belong to the contract": 1}, "detail": {"number requires its value and non-time measurement unit in the fact text": 2, "fact text must contain actor and action": 3}} |
| restatement_check | 39 | {"1": 39} | 17 | {"new_information": {"fact text restates an existing fact: '採掘された塩の純度の測定値は1塩石で、これは塩盆地における塩の採掘活動の基礎的な指標である。'": 1, "fact text restates an existing fact: '塩月暦に基づく「水番潮」の基準点では、採掘された塩の純度は最低1塩石以上である必要がある。'": 2, "fact text restates an existing fact: '塩の汲み場において、導水路の水位差は「塩水尺」を用いて計測され、この計測は「塩月暦」の「水番潮」の基準点と関連付けられている。'": 1, "fact text restates an existing fact: '塩月暦の「水番潮」の基準に基づき、導水路の水位差は「塩水尺」を用いて1の測定値で計測される。'": 7, "fact text restates an existing fact: '「石塩採掘坑口」には、導水路管理評議会が監視する「水門石」が設置されており、この石は塩月暦の「水番潮」の基準に基づき、導水路の水位差を「塩水尺」を用いて計測する起点となる。'": 1, "fact text restates an existing fact: '北壁水門石周辺の導水路の水位差は、塩月暦の「水番潮」の基準に基づき、「塩水尺」を用いて計測され、その管理は導水路管理評議会が行う。'": 3, "fact text restates an existing fact: '「水番血統評議会」の規範に基づき、導水路管理評議会は、「塩月暦」の「水番潮」の基準点において、導水路の水位の差の計測を「塩水尺」を用いて1の単位で行う。'": 2}} |
| review | 9 | {"1": 3, "2": 3} | 0 | {"consistent": {"「塩月暦における『水番潮』の基準値は、最低でも1塩石以上の純度が求められる」という記述は、時間の指標（水番潮）と物質的属性（純度）を混同しており、入力されたブリーフステートメント（s1, s2, s3）や世界契約の定義（水番潮は水量変動と結びついた暦の指標、塩石は純度の単位）と因果関係・論理的整合性において矛盾している。": 1, "facts[1]は「乾水淵の取水地点」を参照していますが、この名称は入力されたe2（塩涸谷）や世界契約（world_contract）の定義された実体・制度・単位の中に存在しません。e2のfactsには「水門石」が記載されていますが、「乾水淵」は未定義の名前であり、既存の事実体系と整合性がありません。": 1, "「塩石」の純度評価と「塩水尺」を用いた水位差の計測値（1）を直接関連付けているが、提供された契約（world_contract）および入力文脈では、「塩石」は純度の単位、「塩水尺」は水位差の計測具/単位として別個に定義されており、両者の数値的等価性や直接的な因果関係は定義されていない。; 対立構造を「e6」と参照しているが、e6はFILLS ALREADY DECIDEDに示される出力実体（本レビューの対象）そのものであり、原因となる入力実体e4やe3を指すべきである。自己参照または循環的な因果関係の記述として論理的に不整合である。": 1}} |
| relations | 6 | {"1": 5} | 0 | {} |

## 世界の契約生成

- 結果: success
- 試行回数: 19
- 1: the JSON object must be str, bytes or bytearray, not NoneType
- 1: duplicate: 水番潮 already appears in calendar.markers
- 2: duplicate: 導水干期 already appears in calendar.markers

## Contract items

| Item | Calls | Attempt distribution | Failures | Rejection reasons |
| --- | ---: | --- | ---: | --- |
| calendar_marker | 10 | {"1": 2, "3": 1} | 0 | {"duplicate: 導水干期 already appears in calendar.markers": 1, "duplicate: 水番潮 already appears in calendar.markers": 1} |
| calendar_name | 3 | {"2": 1} | 0 | {"the JSON object must be str, bytes or bytearray, not NoneType": 1} |
| calendar_origin | 1 | {"1": 1} | 0 | {} |
| capability | 6 | {"1": 3} | 0 | {} |
| institution | 6 | {"1": 3} | 0 | {} |
| society_description | 1 | {"1": 1} | 0 | {} |
| technology_description | 1 | {"1": 1} | 0 | {} |
| unit | 6 | {"1": 3} | 0 | {} |

| Item | Slot | Calls | Attempt distribution | Failures | Rejection reasons |
| --- | --- | ---: | --- | ---: | --- |
| calendar_name | None | 3 | {"2": 1} | 0 | ["the JSON object must be str, bytes or bytearray, not NoneType"] |
| calendar_origin | None | 1 | {"1": 1} | 0 | [] |
| calendar_marker | 0 | 2 | {"1": 1} | 0 | [] |
| calendar_marker | 1 | 2 | {"1": 1} | 0 | [] |
| calendar_marker | 2 | 6 | {"3": 1} | 0 | ["duplicate: 水番潮 already appears in calendar.markers", "duplicate: 導水干期 already appears in calendar.markers"] |
| technology_description | None | 1 | {"1": 1} | 0 | [] |
| capability | 0 | 2 | {"1": 1} | 0 | [] |
| capability | 1 | 2 | {"1": 1} | 0 | [] |
| capability | 2 | 2 | {"1": 1} | 0 | [] |
| unit | 0 | 2 | {"1": 1} | 0 | [] |
| unit | 1 | 2 | {"1": 1} | 0 | [] |
| unit | 2 | 2 | {"1": 1} | 0 | [] |
| society_description | None | 1 | {"1": 1} | 0 | [] |
| institution | 0 | 2 | {"1": 1} | 0 | [] |
| institution | 1 | 2 | {"1": 1} | 0 | [] |
| institution | 2 | 2 | {"1": 1} | 0 | [] |

- 暦・紀年: 塩月暦
- 紀年の起点: 塩の採掘のサイクル、特に主要な導水路の水量変動と結びつけられた、古い記憶に基づく暦。
- 日付の表記: 導水干期, 水番潮, 塩潮期
- 技術の能力と限界: 塩の採掘に適応した単純な機械装置や、導水路の維持管理に必要な原始的な揚水・計測技術に限定される。
- 定義された装置・手法: 導水路流量計測, 塩気深度測, 塩滓精錬
- 使用する測定単位: 塩石 (採掘された塩の純度を測る単位。), 水滴 (導水路から汲み上げられた水の体積。), 塩水尺 (導水路の水位の差を測るための、定規状の計測具。)
- 制度・社会の枠組みと限界: 採掘組合と水番の家系が導水路の管理権をめぐり、権力と資源の分配に関する相互の義務を巡って緊張関係を保つ共同体。
- 定義された規則・組織: 導水路管理評議会 (水番と採掘組合の合意に基づき、導水路の利用と水量配分を決定する審議機関。), 水番血統評議会 (水番家系が水の配分と導水路の安全管理に関する規範を定める権限を持つ。), 塩滓精錬所 (採掘された塩滓から副産物資源を抽出し、共同体の経済基盤を支える作業場。)

## 目的の達成状況

- 被覆の状態: 未達

| 基準・指標 | 値 | 仮の達成条件 | 達成の有無 |
| --- | --- | --- | --- |
| faithful / 入力記述の使用割合 | 1.0 | 1.0 | 達成 |
| breadth / 必要件数を満たす軸の割合 | 0.1875 | 1.0 | 未達 |
| breadth / perspective のエンティティ数 | 1 | 1 | 達成 |
| depth / 因果・歴史の関係を持つ割合 | 0.5 | 0.3 | 達成 |
| depth / history のエンティティ数 | 0 | 1 | 未達 |
| scale / 世界のエンティティ数 | 2 | 1 | 達成 |
| scale / 地域のエンティティ数 | 1 | 1 | 達成 |
| scale / 集落のエンティティ数 | 1 | 1 | 達成 |
| scale / 地区のエンティティ数 | 2 | 1 | 達成 |
| scale / 施設のエンティティ数 | 0 | 1 | 未達 |
| scale / 細部のエンティティ数 | 0 | 1 | 未達 |
| scale / 世界から細部までの連鎖 | False | True | 未達 |

### 軸ごとの被覆と重みの比較

| 軸 | 重み | 配分比率 | エンティティ数 | エンティティ比率 |
| --- | --- | --- | --- | --- |
| 芸術・娯楽・メディア | 0.05 | 0.8% | 0 | 0.0% |
| 信仰と思想 | 0.05 | 0.8% | 0 | 0.0% |
| 日々の暮らし | 0.05 | 0.8% | 0 | 0.0% |
| 生態 | 0.05 | 0.8% | 0 | 0.0% |
| 教育と知識 | 0.05 | 0.8% | 0 | 0.0% |
| 外部との関係 | 0.05 | 0.8% | 0 | 0.0% |
| 地理と気候 | 0.90 | 14.2% | 2 | 11.1% |
| 歴史 | 0.70 | 11.0% | 0 | 0.0% |
| 血縁と共同体 | 0.80 | 12.6% | 2 | 11.1% |
| 言語と文字 | 0.05 | 0.8% | 0 | 0.0% |
| 法と規範 | 0.70 | 11.0% | 1 | 5.6% |
| 自然の法則と法則外の理 | 0.05 | 0.8% | 0 | 0.0% |
| 職業と労働 | 0.80 | 12.6% | 0 | 0.0% |
| 政治と権力 | 1.00 | 15.7% | 6 | 33.3% |
| 資源と経済 | 1.00 | 15.7% | 6 | 33.3% |
| 技術と道具 | 0.05 | 0.8% | 1 | 5.6% |

## スケールごとの件数

| スケール | 件数 |
| --- | --- |
| 世界 | 2 |
| 地域 | 1 |
| 集落 | 1 |
| 地区 | 2 |
| 施設 | 0 |
| 細部 | 0 |
| 合計 | 6 |

## 報酬の分布

| 採点項目 | 件数 | 平均 | 最小 | 最大 |
| --- | --- | --- | --- | --- |
| 報酬（合計） | 6 | 0.950 | 0.922 | 1.000 |

### 合計報酬のヒストグラム

- 0.0 - 0.2: 0
- 0.2 - 0.4: 0
- 0.4 - 0.6: 0
- 0.6 - 0.8: 0
- 0.8 - 1.0: 6

## 凡庸さで捨てられた候補

凡庸さで捨てられた候補はありません。
