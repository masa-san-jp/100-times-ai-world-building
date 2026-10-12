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

- Entities: 25
- Validation errors: 0

## 2. Axis coverage

- Axes: 16 (each should own at least 1 entities)
- Uncovered: none

| axis | weight share | entities | entity share |
| --- | --- | --- | --- |
| Geography and climate | 10.5% | 6 | 8.1% |
| Ecology | 6.3% | 3 | 4.0% |
| Physical and extra-natural laws | 5.3% | 2 | 2.7% |
| Technology and tools | 8.4% | 10 | 13.5% |
| Resources and economy | 7.4% | 3 | 4.0% |
| Politics and power | 9.5% | 3 | 4.0% |
| Law and norms | 8.4% | 10 | 13.5% |
| Belief and thought | 2.1% | 1 | 1.4% |
| Language and writing | 9.5% | 10 | 13.5% |
| Kinship and community | 5.3% | 2 | 2.7% |
| Daily life | 7.4% | 3 | 4.0% |
| Occupations and labor | 8.4% | 16 | 21.6% |
| Education and knowledge | 6.3% | 2 | 2.7% |
| Arts, entertainment, and media | 1.1% | 1 | 1.4% |
| History | 3.2% | 1 | 1.4% |
| External relations | 1.1% | 1 | 1.4% |

## 3. Scale depth

- Deepest scale reached: detail (target: detail)
- Scales below the minimum: none

| scale | entities |
| --- | --- |
| world | 11 |
| region | 5 |
| settlement | 2 |
| district | 2 |
| site | 4 |
| detail | 1 |

## 4. Reward distribution

- Reward: mean 0.973, min 0.797, max 1.000 over 25 entities
- Low-reward entities: 0
- Unscored entities: 0
- 0.0 - 0.2: 0
- 0.2 - 0.4: 0
- 0.4 - 0.6: 0
- 0.6 - 0.8: 1
- 0.8 - 1.0: 24

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
- Iterations: 33 (accepted 25 of 33 logged)
