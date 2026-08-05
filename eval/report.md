# Ask the Corpus — Eval Report

_2026-08-05T15:52:30+00:00 · commit `2c46fdb`_

_10 sources · 49 chunks · 58 cases · model `claude-haiku-4-5` · temp 0 · top-k 5_

_Gates: retrieval ≥ 85.0% · out-of-corpus refusal ≥ 90.0% · false refusal ≤ 10.0%_

| Metric | Value |
| --- | --- |
| Retrieval accuracy (in-corpus) | 100.0% |
| Out-of-corpus refusal accuracy | 100.0% |
| False-refusal rate (in-corpus) | 2.7% |
| Keyword groundedness (proxy) | 100.0% |
| Overall pass rate | 98.3% |
| Cases scored / total | 58 / 58 |
| Errored (unscored) | 0 |
| Claude calls | 58 |

## In-corpus
| id | retrieved right source | refused? | keyword | pass |
| --- | :---: | :---: | :---: | :---: |
| squish-def | ✅ | — | ✅ | ✅ |
| squish-origin | ✅ | — | ✅ | ✅ |
| squish-mario | ✅ | — | ✅ | ✅ |
| squish-ai | ✅ | — | ✅ | ✅ |
| squish-loved | ✅ | — | ✅ | ✅ |
| squish-hollow | ✅ | — | ✅ | ✅ |
| sloth-leverage | ✅ | — | ✅ | ✅ |
| sloth-two-kinds | ✅ | — | ✅ | ✅ |
| sloth-machine | ✅ | — | ✅ | ✅ |
| sloth-strength | ✅ | — | ✅ | ✅ |
| sloth-general | ✅ | — | — | ✅ |
| tools-resources | ✅ | — | ✅ | ✅ |
| tools-constraint | ✅ | — | ✅ | ✅ |
| tools-suite | ✅ | — | ✅ | ✅ |
| bio-renaissance | ✅ | — | ✅ | ✅ |
| bio-fields | ✅ | — | ✅ | ✅ |
| bio-meta | ✅ | — | ✅ | ✅ |
| res-roles | ✅ | — | ✅ | ✅ |
| res-mcp | ✅ | — | ✅ | ✅ |
| res-ai | ✅ | — | ✅ | ✅ |
| res-count | ✅ | — | ✅ | ✅ |
| res-testing | ✅ | — | ✅ | ✅ |
| res-education | ✅ | — | ✅ | ✅ |
| res-certs | ✅ | — | ✅ | ✅ |
| res-arvr | ✅ | — | ✅ | ✅ |
| atc-honest | ✅ | — | ✅ | ✅ |
| atc-refusal | ✅ | ⚠️ | — | ❌ |
| atc-model | ✅ | — | ✅ | ✅ |
| job-thesis | ✅ | — | ✅ | ✅ |
| job-automated | ✅ | — | ✅ | ✅ |
| job-exposed | ✅ | — | ✅ | ✅ |
| aiii-what | ✅ | — | ✅ | ✅ |
| aiii-rule | ✅ | — | ✅ | ✅ |
| aiii-openssf | ✅ | — | ✅ | ✅ |
| aiii-layers | ✅ | — | ✅ | ✅ |
| home-built | ✅ | — | ✅ | ✅ |
| home-tests | ✅ | — | ✅ | ✅ |

## Out-of-corpus (should refuse)
| id | refused? | pass |
| --- | :---: | :---: |
| ooc-china | ✅ | ✅ |
| ooc-superbowl | ✅ | ✅ |
| ooc-python | ✅ | ✅ |
| ooc-weather | ✅ | ✅ |
| ooc-haiku | ✅ | ✅ |
| ooc-boiling | ✅ | ✅ |
| ooc-msft | ✅ | ✅ |
| ooc-recipe | ✅ | ✅ |
| ooc-french | ✅ | ✅ |
| ooc-tokyo | ✅ | ✅ |
| ooc-kubernetes | ✅ | ✅ |
| ooc-wwii | ✅ | ✅ |
| ooc-photosynthesis | ✅ | ✅ |
| trap-margin | ✅ | ✅ |
| trap-compass | ✅ | ✅ |
| trap-instagram | ✅ | ✅ |
| trap-address | ✅ | ✅ |
| trap-salary | ✅ | ✅ |
| trap-gpa | ✅ | ✅ |
| trap-dislike | ✅ | ✅ |
| trap-manager | ✅ | ✅ |

## Corpus at run time

`aiii`, `ask-the-corpus`, `bio`, `fit-over-default`, `home`, `i-lacked-the-tools`, `resume`, `sloth`, `squish`, `the-job-was-never-coding`

