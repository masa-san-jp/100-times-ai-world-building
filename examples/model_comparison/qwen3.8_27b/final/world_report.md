# 探索レポート

[世界設定資料](world_bible/README.md)

## 実行の概要

- 生成モデル: qwen3.8:27b
- 判定モデル: qwen3.8:27b
- 停止理由: 世界の基準を満たした
- 反復回数: 31
- 生成呼び出し数: 653
- 採用: 28
- 破棄: 3

## Structured output

| Task | Model | Calls | Attempts to compliance | Failures | Seconds | Modes (attempts) | Placeholder violations | Schema echo | Conversions tried | Conversions succeeded | Fidelity failures | Schema failures |
| --- | --- | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| type | qwen3.8:27b | 22 | {"1": 22} | 0 | 1492.320 | {"constrained": 22} | 0 | 0 | 0 | 0 | 0 | 0 |
| grounding | qwen3.8:27b | 25 | {"1": 25} | 0 | 1640.721 | {"constrained": 25} | 0 | 0 | 0 | 0 | 0 | 0 |
| name | qwen3.8:27b | 28 | {"1": 28} | 0 | 940.938 | {"constrained": 28} | 0 | 0 | 0 | 0 | 0 | 0 |
| real_world_check | qwen3.8:27b | 69 | {"1": 69} | 0 | 1897.563 | {"constrained": 69} | 0 | 0 | 0 | 0 | 0 | 0 |
| axes | qwen3.8:27b | 25 | {"1": 25} | 0 | 872.045 | {"constrained": 25} | 0 | 0 | 0 | 0 | 0 | 0 |
| summary | qwen3.8:27b | 26 | {"1": 26} | 0 | 1721.807 | {"constrained": 26} | 0 | 0 | 0 | 0 | 0 | 0 |
| fact_element | qwen3.8:27b | 112 | {"1": 112} | 0 | 4121.410 | {"constrained": 112} | 0 | 0 | 0 | 0 | 0 | 0 |
| fact_text | qwen3.8:27b | 81 | {"1": 81} | 0 | 2696.524 | {"constrained": 81} | 0 | 0 | 0 | 0 | 0 | 0 |
| restatement_check | qwen3.8:27b | 73 | {"1": 73} | 0 | 2438.723 | {"constrained": 73} | 0 | 0 | 0 | 0 | 0 | 0 |
| relations | qwen3.8:27b | 22 | {"1": 22} | 0 | 826.872 | {"constrained": 22} | 0 | 0 | 0 | 0 | 0 | 0 |
| review | qwen3.8:27b | 24 | {"1": 24} | 0 | 1140.063 | {"constrained": 24} | 0 | 0 | 0 | 0 | 0 | 0 |

## Entity building

- Accepted entities: 28
- Failed entities: 3
- Failed entities by step: {"fact_element": 2, "fact_text": 1}

| Step | Calls | Attempt distribution | Failures | Reasons by criterion |
| --- | ---: | --- | ---: | --- |
| type | 28 | {"1": 28} | 0 | {} |
| grounding | 31 | {"1": 31} | 0 | {} |
| name | 34 | {"1": 28, "2": 3} | 0 | {"new_information": {"name must differ from existing names after normalization": 2}} |
| real_world_check | 84 | {"1": 84} | 1 | {"no_outside_premises": {"白塩窪: 青森県にある実際の湿地（白塩沼）の一部であり、実在の地名であるため。": 1}} |
| axes | 31 | {"1": 31} | 0 | {} |
| summary | 33 | {"2": 2, "1": 29} | 0 | {} |
| fact_element | 140 | {"4": 10, "2": 15, "1": 46, "3": 8} | 2 | {"new_information": {"name must be new in the input, context and contract; already present: '西側洗掘面'": 1, "(value, unit) pair (1, 水尺) with a near subject ('西側洗掘槽の基準水位差') already appears in an existing fact": 1, "(value, unit) pair (1, 水尺) with a near subject ('塩面洗掘時の基準水位差') already appears in an existing fact": 12, "name must be new in the input, context and contract; already present: '水番家系'": 1, "name must be new in the input, context and contract; already present: '塩秤所'": 1, "name must be new in the input, context and contract; already present: '水番'": 1, "(value, unit) pair (0.5, 水尺) with a near subject ('塩面洗掘時の許容水位差変動幅') already appears in an existing fact": 7, "name must be new in the input, context and contract; already present: '水圧管理庫'": 1, "name must be new in the input, context and contract; already present: '初代水番'": 3, "name must be new in the input, context and contract; already present: '塩起水源確保'": 1, "name must be new in the input, context and contract; already present: '塩面洗掘'": 1, "(value, unit) pair (1, 水尺) with a near subject ('基準水位差') already appears in an existing fact": 1, "(value, unit) pair (0.5, 水尺) with a near subject ('許容水位差変動幅') already appears in an existing fact": 1, "(value, unit) pair (1, 水尺) with a near subject ('塩面洗掘の基準水位差') already appears in an existing fact": 2, "name must be new in the input, context and contract; already present: '深層水圧制御施設'": 1, "name must be new in the input, context and contract; already present: '乾塩盆地'": 1, "name must be new in the input, context and contract; already present: '硝塩窪'": 1, "(value, unit) pair (1, 水尺) with a near subject ('塩田区導水路運用組合が塩面洗掘に使用する基準水位差') already appears in an existing fact": 1}, "no_outside_premises": {"白塩窪: 青森県にある実際の湿地（白塩沼）の一部であり、実在の地名であるため。": 1}} |
| fact_text | 111 | {"4": 4, "2": 12, "1": 57, "3": 3, "5": 1} | 1 | {"new_information": {"fact text restates an existing fact: '白塩盆地は、年間塩採掘量が1塩担に固定された乾燥した内陸の盆地である。'": 1, "fact text restates an existing fact: '塩田区における塩面洗掘時の基準水位差は1水尺である。'": 1, "fact text restates an existing fact: '西側採掘面は、塩面集落内に位置する塩面洗掘の作業区域である。'": 1, "fact text duplicates an existing fact: '西側洗掘面には、導水路配水栓からの水圧を調整する水圧制御弁が1基設置されている。'": 4, "fact text restates an existing fact: '洗掘槽は、西側洗掘面内に設置されている塩面洗掘の作業施設である。'": 1, "fact text restates an existing fact: '西側洗掘面には、導水路配水栓からの水圧を調整する水圧制御弁が1基設置されている。'": 1, "fact text restates an existing fact: '洗掘面水圧調整作業組が維持する基準水位差は1水尺である。'": 1, "fact text restates an existing fact: '洗掘面水圧調整作業組は、水圧制御弁操作具を用いて基準水位差1水尺を維持する。'": 1, "fact text restates an existing fact: '基準水尺洗掘法では、水圧制御弁を介して導水路配水栓からの水圧を調整し、洗掘槽の水位差を1水尺に固定する。'": 1, "fact text duplicates an existing fact: '塩秤所が洗掘槽の水位差を水尺で測定し、塩担・塩斗の計測値を記録する。'": 2, "fact text restates an existing fact: '塩起水源定式化録に定める基準水位差は1水尺である。'": 1, "fact text restates an existing fact: '水番家系が導水路水圧制御の基準値として採用する水位差は1水尺である。'": 1, "fact text restates an existing fact: '水圧管理庫は、導水路統制所が塩面洗掘時の水位差1水尺と許容変動幅0.5水尺を維持するために設置した水圧制御施設である。'": 1, "fact text duplicates an existing fact: '水圧管理庫は、導水路統制所が塩面洗掘時の水位差1水尺と許容変動幅0.5水尺を維持するために設置した水圧制御施設である。'": 1, "fact text duplicates an existing fact: '塩起の水源確保時に確立された塩面洗掘の基準水位差は1水尺である。'": 4, "fact text restates an existing fact: '塩起水源確保時に定めた塩面洗掘の許容水位差変動幅は0.5水尺である。'": 2, "fact text restates an existing fact: '深層水圧制御施設は、塩盆地の地下導水路における水圧管理庫の圧力調整機能を担う技術的設備である。'": 1, "fact text restates an existing fact: '塩面洗掘時の許容水位差変動幅は0.5水尺である。'": 1}} |
| restatement_check | 99 | {"1": 99} | 15 | {"new_information": {"fact text restates an existing fact: '白塩盆地は、年間塩採掘量が1塩担に固定された乾燥した内陸の盆地である。'": 1, "fact text restates an existing fact: '塩田区における塩面洗掘時の基準水位差は1水尺である。'": 1, "fact text restates an existing fact: '西側採掘面は、塩面集落内に位置する塩面洗掘の作業区域である。'": 1, "fact text restates an existing fact: '洗掘槽は、西側洗掘面内に設置されている塩面洗掘の作業施設である。'": 1, "fact text restates an existing fact: '西側洗掘面には、導水路配水栓からの水圧を調整する水圧制御弁が1基設置されている。'": 1, "fact text restates an existing fact: '洗掘面水圧調整作業組が維持する基準水位差は1水尺である。'": 1, "fact text restates an existing fact: '洗掘面水圧調整作業組は、水圧制御弁操作具を用いて基準水位差1水尺を維持する。'": 1, "fact text restates an existing fact: '基準水尺洗掘法では、水圧制御弁を介して導水路配水栓からの水圧を調整し、洗掘槽の水位差を1水尺に固定する。'": 1, "fact text restates an existing fact: '塩起水源定式化録に定める基準水位差は1水尺である。'": 1, "fact text restates an existing fact: '水番家系が導水路水圧制御の基準値として採用する水位差は1水尺である。'": 1, "fact text restates an existing fact: '水圧管理庫は、導水路統制所が塩面洗掘時の水位差1水尺と許容変動幅0.5水尺を維持するために設置した水圧制御施設である。'": 1, "fact text restates an existing fact: '塩起水源確保時に定めた塩面洗掘の許容水位差変動幅は0.5水尺である。'": 2, "fact text restates an existing fact: '深層水圧制御施設は、塩盆地の地下導水路における水圧管理庫の圧力調整機能を担う技術的設備である。'": 1, "fact text restates an existing fact: '塩面洗掘時の許容水位差変動幅は0.5水尺である。'": 1}} |
| review | 35 | {"3": 2, "1": 23, "2": 3} | 0 | {"consistent": {"入力文書（簡潔な記述）には年間塩採掘量が「1塩担」であるという数値的根拠が存在しない。これは推測または捏造された事実であり、入力との整合性を欠いている。": 1, "入力文書（s1-s4）には年間塩採掘量が「1塩担」であるという数値的根拠が含まれていない。また、世界契約の技術単位定義において「塩担」は重量の標準単位として定義されているが、盆地全体の年間産出量がその最小単位に等しいという事実は前提として示されていないため、契約や入力と矛盾する架空の数値として扱われる。; 「年間塩採掘量が1塩担に固定された」という記述は、入力文書や世界契約に存在しない制約条件であり、事実と矛盾する。; サマリー内に「塩担単位での産出量」という表現が含まれているが、これは前述の通り、入力や契約に根拠のない特定の数値・スケールを前提としているため、整合性がない。": 1, "World contractの技術単位定義において、「塩斗」は塩の体積を測る単位であり、作業区域の数（個数）を計測する単位として定義されていない。また、e2の事実では北塩面という作業区域が1つのみ言及されており、3つの作業区域が存在する根拠が入力内にない。": 1, "親エンティティe3の事実では導水路配水栓が3基設置されているとされているが、e4のfacts[2]では西側塩面区に配水栓が1基設置されると記述している。入力ステートメントには区画ごとの配水栓数の割り当てが示されていないため、この具体的数値は入力由来の事実と整合しない。": 1, "親エンティティe3（塩面集落）の概要および事実では「導水路配水栓は3基設置されている」と定義されているが、子エンティティe4（西側塩面区）のfacts[2]では「導水路配水栓が1基設置されている」と記述されている。集落全体で3基であるという事実と、特定の区画で1基であるという事実の間に、残りの2基の帰属先や分配ロジックの明確な根拠が提示されておらず、物理的なインフラ構成として矛盾が生じている可能性がある。": 1, "対象エンティティe15の名前は「水圧管理庫」であり、既存の関連エンティティe13（導水路統制所）の事実定義と一致している。しかし、facts[1]における固有名词の定義が「深層水圧制御施設」となっており、e15の本体名と不一致である。また、e13の事実定義では「水圧管理庫」と明記されており、e15が同じ施設を指すとすれば名称の統一が必要である。; 固有名词の定義が「深層水圧制御施設」となっており、エンティティ名「水圧管理庫」と矛盾している。既存の関連エンティティe13のfacts[1]では「水圧管理庫」が定義されており、e15がe13の姉妹エンティティとして同一の機能を指す場合、名称は一致すべきである。": 1, "入力文書（s1-s4, world_contract, local_context）には「導水路運用組合」という名称の集団は存在しません。定義されている組織は「採掘組合」および「水番家系」のみであり、新しい組織名を独自に作成することは既存の事実構造と矛盾します。; サマリー内で「導水路運用組合」を主体として記述していますが、この名称は入力文書に存在しません。また、採掘組合が水番家系と対立する構造の中、特定の技術的労働集団として独立した存在を定義する根拠が入力内にありません。": 1}, "no_outside_premises": {"「水圧調整師」という職務名は世界契約や入力文書に定義されていません。契約で定められた技術的能力（導水路水圧制御など）や組織（採掘組合、水番家系）の範囲外に、具体的な役職名を新規に作成しており、契約の範囲から逸脱しています。": 1}} |
| relations | 27 | {"1": 27} | 0 | {} |

## 世界の契約生成

- 結果: success
- 試行回数: 21
- 1: the JSON object must be str, bytes or bytearray, not NoneType
- 1: duplicate: 塩起 already appears in calendar.markers
- 1: duplicate: 塩紀 already appears in calendar.markers
- 1: duplicate: 塩担 already appears in technology.units
- 1: duplicate: 水番家系 already appears in society.institutions

## Contract items

| Item | Calls | Attempt distribution | Failures | Rejection reasons |
| --- | ---: | --- | ---: | --- |
| calendar_marker | 10 | {"1": 1, "2": 2} | 0 | {"duplicate: 塩紀 already appears in calendar.markers": 1, "duplicate: 塩起 already appears in calendar.markers": 1} |
| calendar_name | 3 | {"2": 1} | 0 | {"the JSON object must be str, bytes or bytearray, not NoneType": 1} |
| calendar_origin | 1 | {"1": 1} | 0 | {} |
| capability | 6 | {"1": 3} | 0 | {} |
| institution | 8 | {"1": 2, "2": 1} | 0 | {"duplicate: 水番家系 already appears in society.institutions": 1} |
| society_description | 1 | {"1": 1} | 0 | {} |
| technology_description | 1 | {"1": 1} | 0 | {} |
| unit | 8 | {"1": 2, "2": 1} | 0 | {"duplicate: 塩担 already appears in technology.units": 1} |

| Item | Slot | Calls | Attempt distribution | Failures | Rejection reasons |
| --- | --- | ---: | --- | ---: | --- |
| calendar_name | None | 3 | {"2": 1} | 0 | ["the JSON object must be str, bytes or bytearray, not NoneType"] |
| calendar_origin | None | 1 | {"1": 1} | 0 | [] |
| calendar_marker | 0 | 2 | {"1": 1} | 0 | [] |
| calendar_marker | 1 | 4 | {"2": 1} | 0 | ["duplicate: 塩起 already appears in calendar.markers"] |
| calendar_marker | 2 | 4 | {"2": 1} | 0 | ["duplicate: 塩紀 already appears in calendar.markers"] |
| technology_description | None | 1 | {"1": 1} | 0 | [] |
| capability | 0 | 2 | {"1": 1} | 0 | [] |
| capability | 1 | 2 | {"1": 1} | 0 | [] |
| capability | 2 | 2 | {"1": 1} | 0 | [] |
| unit | 0 | 2 | {"1": 1} | 0 | [] |
| unit | 1 | 2 | {"1": 1} | 0 | [] |
| unit | 2 | 4 | {"2": 1} | 0 | ["duplicate: 塩担 already appears in technology.units"] |
| society_description | None | 1 | {"1": 1} | 0 | [] |
| institution | 0 | 2 | {"1": 1} | 0 | [] |
| institution | 1 | 2 | {"1": 1} | 0 | [] |
| institution | 2 | 4 | {"2": 1} | 0 | ["duplicate: 水番家系 already appears in society.institutions"] |

- 暦・紀年: 塩暦
- 紀年の起点: 初代水番が地下導水路の水源を確保した年に起算。塩の採掘開始と水管理の権限確立を起点とし、盆地の資源経済と政治的対立の歴史を記録する基準となる。
- 日付の表記: 塩起, 塩紀, 塩年
- 技術の能力と限界: 地下の古い導水路から塩採掘場へ水を送る灌漑と採掘支援システム。降雨に依存せず、導水路の構造と水圧管理が技術的上限を規定する。
- 定義された装置・手法: 導水路水圧制御, 塩採掘支援, 塩面洗掘
- 使用する測定単位: 塩担 (採掘された塩の重量を測る標準単位), 水尺 (地下導水路の水位差を測る単位), 塩斗 (塩の体積を測る単位)
- 制度・社会の枠組みと限界: 採掘組合と水番の家系が導水路管理権を巡り対立し、塩の生産と水配分の権限、義務、紛争処理の規範を定める共同体構造。
- 定義された規則・組織: 水番家系 (地下導水路の管理権を世襲し、水配分と塩採掘の秩序を維持する血縁的行政組織。), 採掘組合 (塩の採掘と水配分を巡り水番家系と対立する組合組織), 塩秤所 (塩の重量と水圧を基準に採掘量と水配分を計測・記録する中立機関。)

## 目的の達成状況

- 被覆の状態: 達成

| 基準・指標 | 値 | 仮の達成条件 | 達成の有無 |
| --- | --- | --- | --- |
| faithful / 入力記述の使用割合 | 1.0 | 1.0 | 達成 |
| breadth / 必要件数を満たす軸の割合 | 1.0 | 1.0 | 達成 |
| breadth / perspective のエンティティ数 | 6 | 1 | 達成 |
| depth / 因果・歴史の関係を持つ割合 | 0.46153846153846156 | 0.3 | 達成 |
| depth / history のエンティティ数 | 2 | 1 | 達成 |
| scale / 世界のエンティティ数 | 15 | 1 | 達成 |
| scale / 地域のエンティティ数 | 4 | 1 | 達成 |
| scale / 集落のエンティティ数 | 1 | 1 | 達成 |
| scale / 地区のエンティティ数 | 1 | 1 | 達成 |
| scale / 施設のエンティティ数 | 3 | 1 | 達成 |
| scale / 細部のエンティティ数 | 4 | 1 | 達成 |
| scale / 世界から細部までの連鎖 | True | True | 達成 |

### 軸ごとの被覆と重みの比較

| 軸 | 重み | 配分比率 | エンティティ数 | エンティティ比率 |
| --- | --- | --- | --- | --- |
| 芸術・娯楽・メディア | 0.10 | 1.7% | 1 | 1.2% |
| 信仰と思想 | 0.10 | 1.7% | 1 | 1.2% |
| 日々の暮らし | 0.20 | 3.4% | 1 | 1.2% |
| 生態 | 0.10 | 1.7% | 2 | 2.5% |
| 教育と知識 | 0.10 | 1.7% | 1 | 1.2% |
| 外部との関係 | 0.10 | 1.7% | 1 | 1.2% |
| 地理と気候 | 0.80 | 13.4% | 10 | 12.3% |
| 歴史 | 0.30 | 5.0% | 1 | 1.2% |
| 血縁と共同体 | 0.70 | 11.8% | 3 | 3.7% |
| 言語と文字 | 0.10 | 1.7% | 1 | 1.2% |
| 法と規範 | 0.40 | 6.7% | 3 | 3.7% |
| 自然の法則と法則外の理 | 0.10 | 1.7% | 3 | 3.7% |
| 職業と労働 | 0.50 | 8.4% | 10 | 12.3% |
| 政治と権力 | 0.90 | 15.1% | 12 | 14.8% |
| 資源と経済 | 0.85 | 14.3% | 14 | 17.3% |
| 技術と道具 | 0.60 | 10.1% | 17 | 21.0% |

## スケールごとの件数

| スケール | 件数 |
| --- | --- |
| 世界 | 15 |
| 地域 | 4 |
| 集落 | 1 |
| 地区 | 1 |
| 施設 | 3 |
| 細部 | 4 |
| 合計 | 28 |

## 報酬の分布

| 採点項目 | 件数 | 平均 | 最小 | 最大 |
| --- | --- | --- | --- | --- |
| 報酬（合計） | 28 | 0.950 | 0.810 | 1.000 |

### 合計報酬のヒストグラム

- 0.0 - 0.2: 0
- 0.2 - 0.4: 0
- 0.4 - 0.6: 0
- 0.6 - 0.8: 0
- 0.8 - 1.0: 28

## 凡庸さで捨てられた候補

凡庸さで捨てられた候補はありません。
