# Quality Report

- World: `.`
- Overall: **PASS**

## Summary

- graph: **PASS**
- axis_coverage: **PASS**
- scale_depth: **PASS**
- reward_distribution: **PASS**
- genericity: **PASS**
- provenance: **PASS**
- duplicates: **PASS**
- exploration: **PASS**

## 1. Graph

- Entities: 28
- Validation errors: 0

## 2. Axis coverage

- Axes: 16 (each should own at least 1 entities)
- Uncovered: none

| axis | weight share | entities | entity share |
| --- | --- | --- | --- |
| 地理と気候 | 13.5% | 10 | 12.3% |
| 生態 | 1.7% | 2 | 2.5% |
| 自然の法則と法則外の理 | 1.7% | 3 | 3.7% |
| 技術と道具 | 10.1% | 17 | 21.0% |
| 資源と経済 | 14.3% | 14 | 17.3% |
| 政治と権力 | 15.1% | 12 | 14.8% |
| 法と規範 | 6.7% | 3 | 3.7% |
| 信仰と思想 | 1.7% | 1 | 1.2% |
| 言語と文字 | 1.7% | 1 | 1.2% |
| 血縁と共同体 | 11.8% | 3 | 3.7% |
| 日々の暮らし | 3.4% | 1 | 1.2% |
| 職業と労働 | 8.4% | 10 | 12.3% |
| 教育と知識 | 1.7% | 1 | 1.2% |
| 芸術・娯楽・メディア | 1.7% | 1 | 1.2% |
| 歴史 | 5.0% | 1 | 1.2% |
| 外部との関係 | 1.7% | 1 | 1.2% |

## 3. Scale depth

- Deepest scale reached: detail (target: detail)
- Scales below the minimum: none

| scale | entities |
| --- | --- |
| world | 15 |
| region | 4 |
| settlement | 1 |
| district | 1 |
| site | 3 |
| detail | 4 |

## 4. Reward distribution

- Reward: mean 0.951, min 0.810, max 1.000 over 28 entities
- Low-reward entities: 0
- Unscored entities: 0
- 0.0 - 0.2: 0
- 0.2 - 0.4: 0
- 0.4 - 0.6: 0
- 0.6 - 0.8: 0
- 0.8 - 1.0: 28

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
- Stop reason: coverage_met
- Iterations: 31 (accepted 28 of 31 logged)
