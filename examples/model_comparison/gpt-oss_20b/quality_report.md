# Quality Report

- World: `.`
- Overall: **WARN**

## Summary

- graph: **PASS**
- axis_coverage: **WARN**
- scale_depth: **PASS**
- reward_distribution: **PASS**
- genericity: **PASS**
- provenance: **PASS**
- duplicates: **PASS**
- exploration: **PASS**

## 1. Graph

- Entities: 13
- Validation errors: 0

## 2. Axis coverage

- Axes: 16 (each should own at least 1 entities)
- Uncovered: laws_of_nature, belief_thought, language_writing, education_knowledge, arts_media, external_relations

| axis | weight share | entities | entity share |
| --- | --- | --- | --- |
| 地理と気候 | 13.4% | 7 | 17.9% |
| 生態 | 6.0% | 1 | 2.6% |
| 自然の法則と法則外の理 | 0.8% | 0 | 0.0% |
| 技術と道具 | 11.9% | 6 | 15.4% |
| 資源と経済 | 12.7% | 8 | 20.5% |
| 政治と権力 | 13.4% | 9 | 23.1% |
| 法と規範 | 10.4% | 4 | 10.3% |
| 信仰と思想 | 0.8% | 0 | 0.0% |
| 言語と文字 | 0.8% | 0 | 0.0% |
| 血縁と共同体 | 9.0% | 1 | 2.6% |
| 日々の暮らし | 7.5% | 1 | 2.6% |
| 職業と労働 | 10.4% | 1 | 2.6% |
| 教育と知識 | 0.8% | 0 | 0.0% |
| 芸術・娯楽・メディア | 0.8% | 0 | 0.0% |
| 歴史 | 0.8% | 1 | 2.6% |
| 外部との関係 | 0.8% | 0 | 0.0% |

## 3. Scale depth

- Deepest scale reached: detail (target: detail)
- Scales below the minimum: none

| scale | entities |
| --- | --- |
| world | 6 |
| region | 1 |
| settlement | 1 |
| district | 1 |
| site | 1 |
| detail | 3 |

## 4. Reward distribution

- Reward: mean 0.963, min 0.890, max 1.000 over 13 entities
- Low-reward entities: 0
- Unscored entities: 0
- 0.0 - 0.2: 0
- 0.2 - 0.4: 0
- 0.4 - 0.6: 0
- 0.6 - 0.8: 0
- 0.8 - 1.0: 13

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
- Iterations: 18 (accepted 13 of 18 logged)
