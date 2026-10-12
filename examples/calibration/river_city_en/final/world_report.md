# Exploration Report

[World Reference](world_bible/README.md)

## Run summary

- Generation model: qwen3.8:27b
- Judge model: qwen3.8:27b
- Stop reason: world criteria met
- Iterations: 33
- Generation calls: 682
- Accepted: 25
- Discarded: 8

## Structured output

| Task | Model | Calls | Attempts to compliance | Failures | Seconds | Modes (attempts) | Placeholder violations | Schema echo | Conversions tried | Conversions succeeded | Fidelity failures | Schema failures |
| --- | --- | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| type | qwen3.8:27b | 12 | {"1": 12} | 0 | 592.740 | {"constrained": 12} | 0 | 0 | 0 | 0 | 0 | 0 |
| grounding | qwen3.8:27b | 12 | {"1": 12} | 0 | 615.276 | {"constrained": 12} | 0 | 0 | 0 | 0 | 0 | 0 |
| name | qwen3.8:27b | 14 | {"1": 14} | 0 | 352.495 | {"constrained": 14} | 0 | 0 | 0 | 0 | 0 | 0 |
| real_world_check | qwen3.8:27b | 26 | {"1": 26} | 0 | 598.859 | {"constrained": 26} | 0 | 0 | 0 | 0 | 0 | 0 |
| axes | qwen3.8:27b | 12 | {"1": 12} | 0 | 342.924 | {"constrained": 12} | 0 | 0 | 0 | 0 | 0 | 0 |
| summary | qwen3.8:27b | 12 | {"1": 12} | 0 | 617.589 | {"constrained": 12} | 0 | 0 | 0 | 0 | 0 | 0 |
| fact_element | qwen3.8:27b | 36 | {"1": 36} | 0 | 1042.250 | {"constrained": 36} | 0 | 0 | 0 | 0 | 0 | 0 |
| fact_text | qwen3.8:27b | 44 | {"1": 44} | 0 | 1156.467 | {"constrained": 44} | 0 | 0 | 0 | 0 | 0 | 0 |
| restatement_check | qwen3.8:27b | 40 | {"1": 40} | 0 | 821.230 | {"constrained": 40} | 0 | 0 | 0 | 0 | 0 | 0 |
| relations | qwen3.8:27b | 11 | {"1": 11} | 0 | 416.534 | {"constrained": 11} | 0 | 0 | 0 | 0 | 0 | 0 |
| review | qwen3.8:27b | 11 | {"1": 11} | 0 | 366.245 | {"constrained": 11} | 0 | 0 | 0 | 0 | 0 | 0 |

## Entity building

- Accepted entities: 25
- Failed entities: 8
- Failed entities by step: {"fact_text": 5, "commit": 3}

| Step | Calls | Attempt distribution | Failures | Reasons by criterion |
| --- | ---: | --- | ---: | --- |
| type | 33 | {"1": 33} | 0 | {} |
| grounding | 34 | {"1": 33} | 0 | {} |
| name | 35 | {"1": 31, "2": 2} | 0 | {"new_information": {"name must differ from existing names after normalization": 2}} |
| real_world_check | 67 | {"1": 67} | 0 | {} |
| axes | 33 | {"1": 33} | 0 | {} |
| summary | 33 | {"1": 33} | 0 | {} |
| fact_element | 108 | {"1": 61, "2": 18, "3": 1, "4": 2} | 0 | {"new_information": {"(value, unit) pair (120, DdgL) with a near subject ('Annual sediment removal quota per DredgeTriumvirate member') already appears in an existing fact": 3, "(value, unit) pair (120, DdgL) with a near subject ('Annual sediment removal quota per DredgeTriumvirate member in Verdant') already appears in an existing fact": 1, "(value, unit) pair (120, DdgL) with a near subject ('Sediment removal quota per guild member') already appears in an existing fact": 1, "(value, unit) pair (120, DdgL) with a near subject ('Sediment removal quota per guild member per FlwYr') already appears in an existing fact": 1, "(value, unit) pair (3, FlwCrd) with a near subject ('Standard record cord segment length') already appears in an existing fact": 1, "(value, unit) pair (120, DdgL) with a near subject ('Sediment removal quota per KnotBound laborer per cycle') already appears in an existing fact": 1}} |
| fact_text | 131 | {"1": 62, "2": 10, "3": 4, "8": 2, "6": 1, "5": 3} | 5 | {"new_information": {"fact text restates an existing fact: 'Annual sediment removal quota per DredgeTriumvirate member is 120 DdgL.'": 4, "fact text restates an existing fact: 'Verdant is the eastern channel district of Thalassia, managed by the DredgeTriumvirate to maintain 120 DdgL sediment removal per FlwYr.'": 1, "fact text restates an existing fact: 'The standard length of a record cord segment used in Verdant is 3 FlwCrd.'": 2, "fact text duplicates an existing fact: 'The Sediment removal quota per guild member per FlwYr at Gullspire is 120 DdgL.'": 1, "fact text restates an existing fact: 'CordQuotaGuild encodes the 120 DdgL Sediment removal quota per guild member at Gullspire into CrdKnot records each FlwYr.'": 1, "fact text restates an existing fact: 'QuotaDeck is the designated platform within PilingBench District where DredgeScoop instruments measure 120 DdgL sediment removal per FlwYr for the DredgeTriumvirate.'": 1, "fact text restates an existing fact: 'Sediment removal quota per CordWright per FlwYr is 120 DdgL.'": 1, "fact text duplicates an existing fact: 'CordShelf is the vertical storage unit within KnotVault that holds FlwCrdCord segments for CrdKnot records.'": 1, "fact text restates an existing fact: 'The standard record cord segment length in the CordLoft archive is 3 FlwCrd.'": 1, "fact text restates an existing fact: 'The Maximum archive cord length per CordKeeper is 3 FlwCrd.'": 1, "fact text restates an existing fact: 'KnotLedger is the designated registry within CordShelf for logging CrdKnot entries.'": 1, "fact text restates an existing fact: 'CordTender Ties 3 FlwCrd knot on FlwCrdCord at KnottingBench during the Drn phase of each FloodCount cycle.'": 1, "fact text duplicates an existing fact: 'KnotPin is the designated fastening element on CordHook for securing FlwCrdCord segments.'": 1, "fact text restates an existing fact: 'KnotPin is the designated fastening element on CordHook for securing FlwCrdCord segments.'": 1, "fact text duplicates an existing fact: 'CordTender ties 3 FlwCrd knot on FlwCrdCord at KnottingBench.'": 3}, "no_outside_premises": {"units and calendar markers must belong to the contract": 31}, "detail": {"number requires its value and non-time measurement unit in the fact text": 3, "period requires its calendar marker and value in the fact text": 1, "fact text must contain actor and action": 2}} |
| restatement_check | 152 | {"1": 152} | 17 | {"new_information": {"fact text restates an existing fact: 'Annual sediment removal quota per DredgeTriumvirate member is 120 DdgL.'": 4, "fact text restates an existing fact: 'Verdant is the eastern channel district of Thalassia, managed by the DredgeTriumvirate to maintain 120 DdgL sediment removal per FlwYr.'": 1, "fact text restates an existing fact: 'The standard length of a record cord segment used in Verdant is 3 FlwCrd.'": 2, "fact text restates an existing fact: 'The Sediment removal quota per guild member per FlwYr at Gullspire is 120 DdgL.'": 1, "fact text restates an existing fact: 'CordQuotaGuild encodes the 120 DdgL Sediment removal quota per guild member at Gullspire into CrdKnot records each FlwYr.'": 1, "fact text restates an existing fact: 'QuotaDeck is the designated platform within PilingBench District where DredgeScoop instruments measure 120 DdgL sediment removal per FlwYr for the DredgeTriumvirate.'": 1, "fact text restates an existing fact: 'Sediment removal quota per CordWright per FlwYr is 120 DdgL.'": 1, "fact text restates an existing fact: 'CordKeeper ties 3 FlwCrd knot on FlwCrdCord at CordShelf.'": 1, "fact text restates an existing fact: 'The standard record cord segment length in the CordLoft archive is 3 FlwCrd.'": 1, "fact text restates an existing fact: 'The Maximum archive cord length per CordKeeper is 3 FlwCrd.'": 1, "fact text restates an existing fact: 'KnotLedger is the designated registry within CordShelf for logging CrdKnot entries.'": 1, "fact text restates an existing fact: 'CordTender Ties 3 FlwCrd knot on FlwCrdCord at KnottingBench during the Drn phase of each FloodCount cycle.'": 1, "fact text restates an existing fact: 'KnotPin is the designated fastening element on CordHook for securing FlwCrdCord segments.'": 1}} |
| review | 29 | {"1": 27, "2": 1} | 0 | {"consistent": {"The fact states 'Kestrel is the primary dredging vessel,' but the world contract defines technology capabilities as 'DredgeRight' and does not list any specific vessel names or types. Introducing a specific named vessel 'Kestrel' is not supported by the provided input or contract, which only defines the general capability and units. Furthermore, the local context lists 'DredgeTriumvirate' as the institution, but no specific assets are named, making the introduction of a proper noun for a vessel an unsupported premise not derived from the input facts s1-s5.": 1}} |
| relations | 27 | {"1": 27} | 0 | {} |
| commit | 0 | {} | 3 | {"new_information": {"new_information: name must differ from existing names after normalization": 1, "new_information: fact text restates an existing fact: 'The Sediment removal quota per guild member per FlwYr at Gullspire is 120 DdgL.'": 1, "new_information: name must be new in the input, context and contract; already present: 'CordShelf'": 1, "new_information: fact text restates an existing fact: 'CordKeeper ties 3 FlwCrd knot on FlwCrdCord at CordShelf.'": 1}} |

## World contract generation

- Status: success
- Attempts: 20
- 1: duplicate: Flw already appears in calendar.markers
- 1: duplicate: Drn already appears in calendar.markers
- 2: duplicate: Flw already appears in calendar.markers
- 3: duplicate: Drn already appears in calendar.markers

## Contract items

| Item | Calls | Attempt distribution | Failures | Rejection reasons |
| --- | ---: | --- | ---: | --- |
| calendar_marker | 14 | {"1": 1, "2": 1, "4": 1} | 0 | {"duplicate: Drn already appears in calendar.markers": 2, "duplicate: Flw already appears in calendar.markers": 2} |
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
| calendar_marker | 1 | 4 | {"2": 1} | 0 | ["duplicate: Flw already appears in calendar.markers"] |
| calendar_marker | 2 | 8 | {"4": 1} | 0 | ["duplicate: Drn already appears in calendar.markers", "duplicate: Flw already appears in calendar.markers", "duplicate: Drn already appears in calendar.markers"] |
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

- Calendar: FloodCount
- Counting origin: Counting begins at the first documented annual delta flood, establishing a baseline for FloodCount cycles tied to the stilt city's hydraulic rhythm.
- Date markers: Flw, Drn, Slt
- Technical capabilities and limits: Stilt construction and channel dredging tools. No extra-natural physics. Knotted cords serve as records. Limits: annual flooding constrains infrastructure.
- Defined apparatus and methods: DredgeRight, FlwRead, CrdKnot
- Permitted measurement units: FlwCrd (Length of knotted cord used for records), DdgL (Volume of sediment removed from channels), FlwYr (Duration of one annual delta flood cycle)
- Social framework and limits: Three guilds hold shared DredgeRight, binding labor and record-keeping via CrdKnot. Obligations rotate by FlwYr; authority limits sediment removal to DdgL per c
- Defined rules and bodies: DredgeTriumvirate (Three guilds sharing channel rights with rotating labor and shared knotted cord.), CordKeepers (Guild managing knotted cord records and archive integrity.), StiltWard (Maintains stilt integrity during FlwYr; limits CrdKnot archive access.)

## Purpose achievement

- Coverage state: met

| Criterion / metric | Value | Provisional threshold | Achievement |
| --- | --- | --- | --- |
| faithful / input statement use | 1.0 | 1.0 | met |
| breadth / sufficient axes | 1.0 | 1.0 | met |
| breadth / perspective entities | 14 | 1 | met |
| depth / causal or historical relations | 0.42857142857142855 | 0.3 | met |
| depth / history entities | 1 | 1 | met |
| scale / world entities | 11 | 1 | met |
| scale / region entities | 5 | 1 | met |
| scale / settlement entities | 2 | 1 | met |
| scale / district entities | 2 | 1 | met |
| scale / site entities | 4 | 1 | met |
| scale / detail entities | 1 | 1 | met |
| scale / uninterrupted world-to-detail chain | True | True | met |

### Axis coverage against weight

| Axis | Weight | Budget share | Entities | Entity share |
| --- | --- | --- | --- | --- |
| Arts, entertainment, and media | 0.10 | 1.1% | 1 | 1.4% |
| Belief and thought | 0.20 | 2.1% | 1 | 1.4% |
| Daily life | 0.70 | 7.4% | 3 | 4.1% |
| Ecology | 0.60 | 6.3% | 3 | 4.1% |
| Education and knowledge | 0.60 | 6.3% | 2 | 2.7% |
| External relations | 0.10 | 1.1% | 1 | 1.4% |
| Geography and climate | 1.00 | 10.5% | 6 | 8.1% |
| History | 0.30 | 3.2% | 1 | 1.4% |
| Kinship and community | 0.50 | 5.3% | 2 | 2.7% |
| Language and writing | 0.90 | 9.5% | 10 | 13.5% |
| Law and norms | 0.80 | 8.4% | 10 | 13.5% |
| Physical and extra-natural laws | 0.50 | 5.3% | 2 | 2.7% |
| Occupations and labor | 0.80 | 8.4% | 16 | 21.6% |
| Politics and power | 0.90 | 9.5% | 3 | 4.1% |
| Resources and economy | 0.70 | 7.4% | 3 | 4.1% |
| Technology and tools | 0.80 | 8.4% | 10 | 13.5% |

## Entities per scale

| Scale | Entities |
| --- | --- |
| World | 11 |
| Region | 5 |
| Settlement | 2 |
| District | 2 |
| Site | 4 |
| Detail | 1 |
| Total | 25 |

## Reward distribution

| Score | Count | Mean | Min | Max |
| --- | --- | --- | --- | --- |
| reward (total) | 25 | 0.973 | 0.797 | 1.000 |

### Histogram of the total reward

- 0.0 - 0.2: 0
- 0.2 - 0.4: 0
- 0.4 - 0.6: 0
- 0.6 - 0.8: 1
- 0.8 - 1.0: 24

## Candidates discarded as generic

No candidates were discarded as generic.
