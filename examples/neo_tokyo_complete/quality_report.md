# Quality Report

- World: `examples/neo_tokyo_complete`
- Overall: **WARN**

## Summary

- duplicates: **WARN**
- character_consistency: **WARN**
- novel_text: **PASS**
- chapter_structure: **PASS**

## 1. 100-item list duplicates

- `01_desire_list`: warn — items=100, exact_duplicates=2, normalized_duplicates=2, near_pairs=0, unique=98
- `02_ability_list`: pass — items=100, exact_duplicates=0, normalized_duplicates=0, near_pairs=0, unique=100
- `03_role_list`: warn — items=100, exact_duplicates=1, normalized_duplicates=1, near_pairs=0, unique=99
- `18_people_list`: pass — items=100, exact_duplicates=0, normalized_duplicates=0, near_pairs=0, unique=100

## 2. Character consistency

- `カエデ・アキラ (19歳)`: warn — plot chapters=[], novel chapters=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
- `ミドリ (実年齢非公開)`: warn — plot chapters=[], novel chapters=[2, 3, 4, 6, 7, 8, 9, 10]
- `レン (24歳)`: warn — plot chapters=[], novel chapters=[2, 3, 4, 6, 7, 8, 9, 10]
- `ノア (AI人格/実体不明)`: warn — plot chapters=[], novel chapters=[2, 3, 4, 6, 7, 9, 10]
- 章プロットに主要キャラクター名が1件も見つからない（カエデ・アキラ (19歳)、ミドリ (実年齢非公開)、レン (24歳)、ノア (AI人格/実体不明)）: 章プロットとキャラクター一覧の名前が一致していない可能性

## 3. Novel text

- Character counts: min=2585, max=3745, average=3008.9
- Below minimum: `[]`
- Truncation suspected: `[]`
- chapter_01: pass, 2585 characters
- chapter_02: pass, 3119 characters
- chapter_03: pass, 3286 characters
- chapter_04: pass, 2791 characters
- chapter_05: pass, 2678 characters
- chapter_06: pass, 3423 characters
- chapter_07: pass, 2611 characters
- chapter_08: pass, 3745 characters
- chapter_09: pass, 3018 characters
- chapter_10: pass, 2833 characters

## 4. Chapter structure

- Plot chapters: 10/10
- Novel chapters: 10/10
