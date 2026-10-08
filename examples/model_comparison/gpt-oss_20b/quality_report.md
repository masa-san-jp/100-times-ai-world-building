# Quality Report

- World: `.`
- Overall: **WARN**

## Summary

- graph: **PASS**
- axis_coverage: **WARN**
- scale_depth: **WARN**
- reward_distribution: **PASS**
- genericity: **PASS**
- provenance: **PASS**
- duplicates: **PASS**
- exploration: **PASS**

## 1. Graph

- Entities: 5
- Validation errors: 0

## 2. Axis coverage

- Axes: 16 (each should own at least 1 entities)
- Uncovered: ecology, laws_of_nature, technology_tools, language_writing, education_knowledge, arts_media, external_relations

| axis | weight share | entities | entity share |
| --- | --- | --- | --- |
| 地理と気候 | 10.8% | 1 | 7.1% |
| 生態 | 8.1% | 0 | 0.0% |
| 自然の法則と法則外の理 | 0.7% | 0 | 0.0% |
| 技術と道具 | 8.1% | 0 | 0.0% |
| 資源と経済 | 12.2% | 3 | 21.4% |
| 政治と権力 | 10.8% | 3 | 21.4% |
| 法と規範 | 10.8% | 2 | 14.3% |
| 信仰と思想 | 0.7% | 1 | 7.1% |
| 言語と文字 | 0.7% | 0 | 0.0% |
| 血縁と共同体 | 9.5% | 1 | 7.1% |
| 日々の暮らし | 9.5% | 1 | 7.1% |
| 職業と労働 | 9.5% | 1 | 7.1% |
| 教育と知識 | 0.7% | 0 | 0.0% |
| 芸術・娯楽・メディア | 0.7% | 0 | 0.0% |
| 歴史 | 6.8% | 1 | 7.1% |
| 外部との関係 | 0.7% | 0 | 0.0% |

## 3. Scale depth

- Deepest scale reached: world (target: detail)
- Scales below the minimum: region, settlement, district, site, detail

| scale | entities |
| --- | --- |
| world | 5 |
| region | 0 |
| settlement | 0 |
| district | 0 |
| site | 0 |
| detail | 0 |

## 4. Reward distribution

- Reward: mean 0.962, min 0.827, max 1.000 over 5 entities
- Low-reward entities: 0
- Unscored entities: 0
- 0.0 - 0.2: 0
- 0.2 - 0.4: 0
- 0.4 - 0.6: 0
- 0.6 - 0.8: 0
- 0.8 - 1.0: 5

## 5. Genericity

- Mean genericity score: - (threshold 0.5)
- Entities below threshold: 0
- Candidates rejected as generic: 0

## 6. Provenance

- Entities without any grounding: none

## 7. Duplicates

- Entity texts: exact=0, normalized=0, near pairs=0
- Repeated names: 0

## 8. Exploration

- Run status: completed
- Stop reason: max_iterations
- Iterations: 12 (accepted 5 of 12 logged)
