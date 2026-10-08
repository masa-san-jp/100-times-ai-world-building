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
- Uncovered: ecology, laws_of_nature, technology_tools, law_norms, belief_thought, kinship_community, daily_life, occupations_labor, education_knowledge, arts_media, history, external_relations

| axis | weight share | entities | entity share |
| --- | --- | --- | --- |
| 地理と気候 | 15.0% | 5 | 33.3% |
| 生態 | 0.8% | 0 | 0.0% |
| 自然の法則と法則外の理 | 13.3% | 0 | 0.0% |
| 技術と道具 | 0.8% | 0 | 0.0% |
| 資源と経済 | 16.7% | 5 | 33.3% |
| 政治と権力 | 16.7% | 4 | 26.7% |
| 法と規範 | 0.8% | 0 | 0.0% |
| 信仰と思想 | 0.8% | 0 | 0.0% |
| 言語と文字 | 0.8% | 1 | 6.7% |
| 血縁と共同体 | 15.0% | 0 | 0.0% |
| 日々の暮らし | 0.8% | 0 | 0.0% |
| 職業と労働 | 15.0% | 0 | 0.0% |
| 教育と知識 | 0.8% | 0 | 0.0% |
| 芸術・娯楽・メディア | 0.8% | 0 | 0.0% |
| 歴史 | 0.8% | 0 | 0.0% |
| 外部との関係 | 0.8% | 0 | 0.0% |

## 3. Scale depth

- Deepest scale reached: district (target: detail)
- Scales below the minimum: site, detail

| scale | entities |
| --- | --- |
| world | 1 |
| region | 1 |
| settlement | 1 |
| district | 2 |
| site | 0 |
| detail | 0 |

## 4. Reward distribution

- Reward: mean 0.976, min 0.966, max 1.000 over 5 entities
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
