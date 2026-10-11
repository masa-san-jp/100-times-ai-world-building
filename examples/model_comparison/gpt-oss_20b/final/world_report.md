# 探索レポート

[世界設定資料](world_bible/README.md)

## 実行の概要

- 生成モデル: gpt-oss:20b
- 判定モデル: qwen3.8:27b
- 停止理由: 反復の上限に達した
- 反復回数: 18
- 生成呼び出し数: 429
- 採用: 13
- 破棄: 5

## Entity building

- Accepted entities: 13
- Failed entities: 5
- Failed entities by step: {"fact_text": 4, "review": 1}

| Step | Calls | Attempt distribution | Failures | Reasons by criterion |
| --- | ---: | --- | ---: | --- |
| type | 20 | {"1": 16} | 0 | {} |
| grounding | 20 | {"1": 18} | 0 | {} |
| name | 25 | {"1": 13, "2": 4, "4": 1} | 0 | {"no_outside_premises": {"塩井村: 日本の実在する自治体（村）の固有名詞。": 1, "塩湧郡: 日本の歴史的行政区画（郡）の名称であり、実在した地名として記録されている。": 1}, "new_information": {"name must differ from existing names after normalization": 1}} |
| real_world_check | 51 | {"1": 49, "2": 1} | 2 | {"no_outside_premises": {"塩井村: 日本の実在する自治体（村）の固有名詞。": 1, "塩湧郡: 日本の歴史的行政区画（郡）の名称であり、実在した地名として記録されている。": 1}} |
| axes | 18 | {"1": 18} | 0 | {} |
| summary | 21 | {"1": 16, "2": 1, "3": 1} | 0 | {"objective": {"quoted speech in the summary; move quotations into facts": 1}, "no_outside_premises": {"units and calendar markers must belong to the contract": 3}} |
| fact_element | 83 | {"1": 27, "2": 18, "3": 5} | 0 | {"new_information": {"(value, unit) pair (5000, shg) with a near subject ('年間塩採掘量') already appears in an existing fact": 2, "(value, unit) pair (2000, shg) with a near subject ('年間水使用許可量') already appears in an existing fact": 2, "(value, unit) pair (5000, shg) with a near subject ('年平均塩採掘量') already appears in an existing fact": 1}} |
| fact_text | 82 | {"1": 28, "2": 17, "5": 1, "3": 3, "4": 1} | 4 | {"new_information": {"fact text restates an existing fact: '塩水盆地の年平均塩の質量は5000 shgであり、塩暦の「塩路」「乾井」「水源」マーカーの下で水源監査委・塩水調整会・水源審査委員会が管理している。'": 1, "fact text restates an existing fact: '塩雲集落の年間塩採掘量は100 shgです。'": 1, "fact text restates an existing fact: '塩雲宿は塩雲集落内の宿泊施設で、塩暦の塩路・乾井・水源マーカーに沿い、水源監査委・塩水調整会の監査下で年間100 shgの塩を採掘する。'": 1, "fact text restates an existing fact: '水源調整集団は、塩暦の塩路・乾井・水源マーカーに沿って、水源監査委・塩水調整会・水源審査委員会と連携し、年間塩採掘量5000 shgを調整する。'": 2, "fact text restates an existing fact: '塩雲域の年間塩採掘量は25 shgで、塩暦の塩路・乾井・水源マーカーに沿い、水源監査委・塩水調整会・水源審査委員会の監査下で管理されている。'": 1, "fact text restates an existing fact: '塩雲小区の塩貯蔵タンクは塩暦の塩路・乾井・水源マーカーに沿い、5 shgの塩を保管し、水源監査委・塩水調整会・水源審査委員会の監査下で管理される。'": 2, "fact text restates an existing fact: '塩暦の「塩路」「乾井」「水源」マーカーに沿い、水源監査委が塩貯蔵タンクの塩密度を1.2 nshで測定する。'": 1, "fact text duplicates an existing fact: '塩雲小区の塩密度は1.2 nshで、塩暦の塩路・乾井・水源マーカーに沿い水源監査委・塩水調整会・水源審査委員会の監査下で管理される。'": 1, "fact text restates an existing fact: '水源監査委が塩暦の「塩路」「乾井」「水源」マーカーに沿い、塩雲小区倉庫の容量を測定する（5 shg）(水源監査委、塩水調整会、水源審査委員会)'": 2, "fact text restates an existing fact: '塩雲乾貯は、塩暦の塩路・乾井・水源マーカーに沿い水源監査委、塩水調整会、水源審査委員会の監査下で容量 5 shg を保つ。'": 3, "fact text restates an existing fact: '乾塩倉庫容量は5 shgで、塩暦の塩路・乾井・水源マーカーに沿い、水源監査委、塩水調整会、水源審査委員会が年次報告で測定・監査する。'": 1, "fact text restates an existing fact: '塩暦1125年の地下水配分証明書は、塩路・乾井・水源に沿い水源監査委、塩水調整会、水源審査委員会の監査下で、年間水使用許可量2000 shgを定めた。'": 1, "fact text duplicates an existing fact: '地下水配分証書は塩暦1125年に水源監査委が発行し、塩路・乾井・水源に沿った年間塩採掘量許可5000 shgを証明する。'": 1, "fact text restates an existing fact: '塩源管理集団は、塩暦の塩路・乾井・水源を基準に、年平均塩採掘量5000 shgを水源監査委・塩水調整会・水源審査委員会と連携して監査・調整する団体です。'": 1, "fact text restates an existing fact: '砂塩渓谷の塩採掘量は1200 shgで、塩暦の塩路・乾井・水源に沿って水源監査委・塩水調整会・水源審査委員会が管理する。'": 1, "fact text restates an existing fact: '乾塩渓谷の塩採掘量は1200 shgで、塩暦の塩路・乾井・水源マーカーに沿い、水源監査委・塩水調整会・水源審査委員会が管理している。'": 2}, "no_outside_premises": {"units and calendar markers must belong to the contract": 6}, "detail": {"fact text must contain actor and action": 1, "fact text must contain object": 1}} |
| restatement_check | 77 | {"1": 77} | 20 | {"new_information": {"fact text restates an existing fact: '塩水盆地の年平均塩の質量は5000 shgであり、塩暦の「塩路」「乾井」「水源」マーカーの下で水源監査委・塩水調整会・水源審査委員会が管理している。'": 1, "fact text restates an existing fact: '塩雲集落の年間塩採掘量は100 shgです。'": 1, "fact text restates an existing fact: '塩雲宿は塩雲集落内の宿泊施設で、塩暦の塩路・乾井・水源マーカーに沿い、水源監査委・塩水調整会の監査下で年間100 shgの塩を採掘する。'": 1, "fact text restates an existing fact: '水源調整集団は、塩暦の塩路・乾井・水源マーカーに沿って、水源監査委・塩水調整会・水源審査委員会と連携し、年間塩採掘量5000 shgを調整する。'": 2, "fact text restates an existing fact: '塩雲域の年間塩採掘量は25 shgで、塩暦の塩路・乾井・水源マーカーに沿い、水源監査委・塩水調整会・水源審査委員会の監査下で管理されている。'": 1, "fact text restates an existing fact: '塩雲小区の塩貯蔵タンクは塩暦の塩路・乾井・水源マーカーに沿い、5 shgの塩を保管し、水源監査委・塩水調整会・水源審査委員会の監査下で管理される。'": 2, "fact text restates an existing fact: '塩暦の「塩路」「乾井」「水源」マーカーに沿い、水源監査委が塩貯蔵タンクの塩密度を1.2 nshで測定する。'": 1, "fact text restates an existing fact: '水源監査委が塩暦の「塩路」「乾井」「水源」マーカーに沿い、塩雲小区倉庫の容量を測定する（5 shg）(水源監査委、塩水調整会、水源審査委員会)'": 2, "fact text restates an existing fact: '塩雲乾貯は、塩暦の塩路・乾井・水源マーカーに沿い水源監査委、塩水調整会、水源審査委員会の監査下で容量 5 shg を保つ。'": 3, "fact text restates an existing fact: '乾塩倉庫容量は5 shgで、塩暦の塩路・乾井・水源マーカーに沿い、水源監査委、塩水調整会、水源審査委員会が年次報告で測定・監査する。'": 1, "fact text restates an existing fact: '塩暦1125年の地下水配分証明書は、塩路・乾井・水源に沿い水源監査委、塩水調整会、水源審査委員会の監査下で、年間水使用許可量2000 shgを定めた。'": 1, "fact text restates an existing fact: '塩源管理集団は、塩暦の塩路・乾井・水源を基準に、年平均塩採掘量5000 shgを水源監査委・塩水調整会・水源審査委員会と連携して監査・調整する団体です。'": 1, "fact text restates an existing fact: '砂塩渓谷の塩採掘量は1200 shgで、塩暦の塩路・乾井・水源に沿って水源監査委・塩水調整会・水源審査委員会が管理する。'": 1, "fact text restates an existing fact: '乾塩渓谷の塩採掘量は1200 shgで、塩暦の塩路・乾井・水源マーカーに沿い、水源監査委・塩水調整会・水源審査委員会が管理している。'": 2}} |
| review | 18 | {"1": 13, "2": 1, "3": 1} | 1 | {"consistent": {"": 1, "false verdict has no issue identifying an affected field": 1, "facts[0]は年間塩採掘量許可を5000 shgとしており、facts[1]はその値を「年間塩採掘量5000 shgと年間水使用量2000 shg」の文脈で示しているが、単位の定義（shgは塩の質量）と文書の性質（水使用許可を含む）から、水使用量にも塩の質量単位であるshgが適用される点は契約上の定義と整合している。しかし、nameフィールドが「地下水配分証書」、facts[1]が「地下水配分証券」と別名を使用しており、同一文書の名称が統一されていない。また、summaryは「地下水配分証明書」と呼称しており、3つの異なる名称が混在しているため、実体としての同一性（consistency）が保たれていない。; 入力ターゲットe11のnameは「地下水配分証明書」であるが、アセンブルされたe12のnameは「地下水配分証書」、facts[1]は「地下水配分証券」となっており、同一オブジェクトの名称が不統一である。": 1, "入力TARGETのe11および関連文脈ではこの文書の名称は「地下水配分証明書」と定義されているが、組み立て済みのエンティティのnameフィールドは「地下水配分承認証」となっており、入力と矛盾している。; facts[1]のproper_nounにおいて、文書の名称が「地下水配分証典」とされているが、入力文脈では「地下水配分証明書」（または別名「水源配分証書」）とされており、名称が一致しない。; facts[0]のtextにおいて、文書の名称が「地下水配分証書」とされているが、入力文脈では正式名称は「地下水配分証明書」とされており、名称が一致しない。": 1, "ターゲットエンティティe11の名称は「地下水配分証明書」であるが、新エンティティe12の名称は「水源管理証明書」となっており、同一文書として扱う際に名称の不整合がある。; ターゲットe11の事実（facts）では「年間水使用許可量2000 shg」が記載されているが、e12のfacts[0]およびsummaryでは「年間塩採掘量許可 5000 shg」を証明する文書として記述されている。e11が水使用量（2000 shg）を定めた文書であるという前提と矛盾する。": 1, "ターゲット实体 e2 の名称は「乾塩渓谷」であるが、組み立てられた实体の名称は「砂塩渓谷」となっており、入力文書・LOCAL CONTEXT・WORLD CONTRACT で定義された名称と矛盾している。; facts[0] のテキスト内に「砂塩渓谷」という名称が含まれており、ターゲット实体 e2 の正式名称「乾塩渓谷」と一致しない。; facts[1] のテキスト内に「砂塩渓谷域」という名称が含まれており、ターゲット实体 e2 の文脈および名称「乾塩渓谷」との整合性がない。; サマリー内で「乾塩渓谷は、古代塩水協定により...」と説明されている一方、实体の name フィールドは「砂塩渓谷」であり、同一实体内の自己矛盾が存在する。": 1}, "no_outside_premises": {"「塩雲」は内陸盆地であり、海に接していないため、「海風」という名称は地理的・気候的設定（降雨がほとんどない内陸）と矛盾し、外部の海浜環境の前提を持ち込んでいる。; 「海風倉庫」という名称が用いられているが、内陸盆地という設定と矛盾する外部の前提（海風）が含まれている。": 1}} |
| relations | 14 | {"1": 14} | 0 | {} |

## 世界の契約生成

- 結果: success
- 試行回数: 16

## Contract items

| Item | Calls | Attempt distribution | Failures | Rejection reasons |
| --- | ---: | --- | ---: | --- |
| calendar_marker | 6 | {"1": 3} | 0 | {} |
| calendar_name | 2 | {"1": 1} | 0 | {} |
| calendar_origin | 1 | {"1": 1} | 0 | {} |
| capability | 6 | {"1": 3} | 0 | {} |
| institution | 6 | {"1": 3} | 0 | {} |
| society_description | 1 | {"1": 1} | 0 | {} |
| technology_description | 1 | {"1": 1} | 0 | {} |
| unit | 6 | {"1": 3} | 0 | {} |

| Item | Slot | Calls | Attempt distribution | Failures | Rejection reasons |
| --- | --- | ---: | --- | ---: | --- |
| calendar_name | None | 2 | {"1": 1} | 0 | [] |
| calendar_origin | None | 1 | {"1": 1} | 0 | [] |
| calendar_marker | 0 | 2 | {"1": 1} | 0 | [] |
| calendar_marker | 1 | 2 | {"1": 1} | 0 | [] |
| calendar_marker | 2 | 2 | {"1": 1} | 0 | [] |
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

- 暦・紀年: 塩暦
- 紀年の起点: 塩暦は、内陸盆地で初期塩採掘開始と古代導水路開通を記念し、採掘組合と水番家系の初期協議を基に塩と水の共同管理の基盤として定められた。
- 日付の表記: 塩路, 乾井, 水源
- 技術の能力と限界: 古い地下導水路を利用し、乾燥盆地で水を引く技術。水量は限定的で、塩採掘に不可欠だが、管理権争いが続く
- 定義された装置・手法: 水源管理, 乾井管理, 塩採掘
- 使用する測定単位: shg (塩の質量を測る単位), shp (塩の質量を測定する単位), nsh (塩の密度を測る単位)
- 制度・社会の枠組みと限界: 採掘組合と水番家系(血縁)が導水路管理権を協議し、共同決定で水使用と塩採掘量を制限。各組織は自らの役割を守り、法と規範に従う。
- 定義された規則・組織: 水源監査委 (水源管理と塩採掘量の合意を仲介し、使用権を監査する), 塩水調整会 (塩採掘と水使用を調整し年次報告を監査する), 水源審査委員会 (水源監査委補佐役で季節ごとに水源と塩採掘量を調査する)

## 目的の達成状況

- 被覆の状態: 未達

| 基準・指標 | 値 | 仮の達成条件 | 達成の有無 |
| --- | --- | --- | --- |
| faithful / 入力記述の使用割合 | 1.0 | 1.0 | 達成 |
| breadth / 必要件数を満たす軸の割合 | 0.375 | 1.0 | 未達 |
| breadth / perspective のエンティティ数 | 2 | 1 | 達成 |
| depth / 因果・歴史の関係を持つ割合 | 0.5714285714285714 | 0.3 | 達成 |
| depth / history のエンティティ数 | 1 | 1 | 達成 |
| scale / 世界のエンティティ数 | 6 | 1 | 達成 |
| scale / 地域のエンティティ数 | 1 | 1 | 達成 |
| scale / 集落のエンティティ数 | 1 | 1 | 達成 |
| scale / 地区のエンティティ数 | 1 | 1 | 達成 |
| scale / 施設のエンティティ数 | 1 | 1 | 達成 |
| scale / 細部のエンティティ数 | 3 | 1 | 達成 |
| scale / 世界から細部までの連鎖 | True | True | 達成 |

### 軸ごとの被覆と重みの比較

| 軸 | 重み | 配分比率 | エンティティ数 | エンティティ比率 |
| --- | --- | --- | --- | --- |
| 芸術・娯楽・メディア | 0.05 | 0.7% | 0 | 0.0% |
| 信仰と思想 | 0.05 | 0.7% | 0 | 0.0% |
| 日々の暮らし | 0.50 | 7.5% | 1 | 2.6% |
| 生態 | 0.40 | 6.0% | 1 | 2.6% |
| 教育と知識 | 0.05 | 0.7% | 0 | 0.0% |
| 外部との関係 | 0.05 | 0.7% | 0 | 0.0% |
| 地理と気候 | 0.90 | 13.4% | 7 | 17.9% |
| 歴史 | 0.05 | 0.7% | 1 | 2.6% |
| 血縁と共同体 | 0.60 | 9.0% | 1 | 2.6% |
| 言語と文字 | 0.05 | 0.7% | 0 | 0.0% |
| 法と規範 | 0.70 | 10.4% | 4 | 10.3% |
| 自然の法則と法則外の理 | 0.05 | 0.7% | 0 | 0.0% |
| 職業と労働 | 0.70 | 10.4% | 1 | 2.6% |
| 政治と権力 | 0.90 | 13.4% | 9 | 23.1% |
| 資源と経済 | 0.85 | 12.7% | 8 | 20.5% |
| 技術と道具 | 0.80 | 11.9% | 6 | 15.4% |

## スケールごとの件数

| スケール | 件数 |
| --- | --- |
| 世界 | 6 |
| 地域 | 1 |
| 集落 | 1 |
| 地区 | 1 |
| 施設 | 1 |
| 細部 | 3 |
| 合計 | 13 |

## 報酬の分布

| 採点項目 | 件数 | 平均 | 最小 | 最大 |
| --- | --- | --- | --- | --- |
| 報酬（合計） | 13 | 0.963 | 0.890 | 1.000 |

### 合計報酬のヒストグラム

- 0.0 - 0.2: 0
- 0.2 - 0.4: 0
- 0.4 - 0.6: 0
- 0.6 - 0.8: 0
- 0.8 - 1.0: 13

## 凡庸さで捨てられた候補

凡庸さで捨てられた候補はありません。
