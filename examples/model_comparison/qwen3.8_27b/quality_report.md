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

- Entities: 9
- Validation errors: 0

## 2. Axis coverage

- Axes: 16 (each should own at least 1 entities)
- Uncovered: ecology, belief_thought, language_writing, occupations_labor, education_knowledge, arts_media, external_relations

| axis | weight share | entities | entity share |
| --- | --- | --- | --- |
| 地理と気候 | 14.5% | 3 | 11.1% |
| 生態 | 3.2% | 0 | 0.0% |
| 自然の法則と法則外の理 | 1.6% | 1 | 3.7% |
| 技術と道具 | 9.7% | 7 | 25.9% |
| 資源と経済 | 14.5% | 3 | 11.1% |
| 政治と権力 | 12.9% | 7 | 25.9% |
| 法と規範 | 4.8% | 2 | 7.4% |
| 信仰と思想 | 3.2% | 0 | 0.0% |
| 言語と文字 | 1.6% | 0 | 0.0% |
| 血縁と共同体 | 11.3% | 1 | 3.7% |
| 日々の暮らし | 4.8% | 1 | 3.7% |
| 職業と労働 | 4.8% | 0 | 0.0% |
| 教育と知識 | 1.6% | 0 | 0.0% |
| 芸術・娯楽・メディア | 1.6% | 0 | 0.0% |
| 歴史 | 8.1% | 2 | 7.4% |
| 外部との関係 | 1.6% | 0 | 0.0% |

## 3. Scale depth

- Deepest scale reached: site (target: detail)
- Scales below the minimum: detail

| scale | entities |
| --- | --- |
| world | 2 |
| region | 1 |
| settlement | 1 |
| district | 2 |
| site | 3 |
| detail | 0 |

## 4. Reward distribution

- Reward: mean 0.974, min 0.948, max 1.000 over 9 entities
- Low-reward entities: 0
- Unscored entities: 0
- 0.0 - 0.2: 0
- 0.2 - 0.4: 0
- 0.4 - 0.6: 0
- 0.6 - 0.8: 0
- 0.8 - 1.0: 9

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
- Iterations: 12 (accepted 9 of 12 logged)
