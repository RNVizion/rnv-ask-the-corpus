# Ask the Corpus — Eval Report

_2026-09-22T11:11:01+00:00 · commit `b0d77df`_

_13 sources · 64 chunks · 60 cases · model `claude-haiku-4-5` · temp 0 · top-k 5_

_Gates: retrieval ≥ 85.0% · out-of-corpus refusal ≥ 90.0% · false refusal ≤ 10.0% · public claims 100.0%_

| Metric | Value |
| --- | --- |
| Retrieval accuracy (in-corpus) | 100.0% |
| Out-of-corpus refusal accuracy | 100.0% |
| False-refusal rate (in-corpus) | 2.6% |
| Public claims stated correctly | 100.0% (2 case(s)) |
| Keyword groundedness (proxy) | 100.0% |
| Overall pass rate | 98.3% |
| Cases scored / total | 60 / 60 |
| Errored (unscored) | 0 |
| Claude calls | 60 |

## In-corpus
| id | retrieved right source | refused? | keyword | claim | pass |
| --- | :---: | :---: | :---: | :---: | :---: |
| squish-def | ✅ | — | ✅ | — | ✅ |
| squish-origin | ✅ | — | ✅ | — | ✅ |
| squish-mario | ✅ | — | ✅ | — | ✅ |
| squish-ai | ✅ | — | ✅ | — | ✅ |
| squish-loved | ✅ | — | ✅ | — | ✅ |
| squish-hollow | ✅ | — | ✅ | — | ✅ |
| sloth-leverage | ✅ | — | ✅ | — | ✅ |
| sloth-two-kinds | ✅ | — | ✅ | — | ✅ |
| sloth-machine | ✅ | — | ✅ | — | ✅ |
| sloth-strength | ✅ | — | ✅ | — | ✅ |
| sloth-general | ✅ | — | — | — | ✅ |
| fod-two-systems | ✅ | — | ✅ | — | ✅ |
| tools-resources | ✅ | — | ✅ | — | ✅ |
| tools-constraint | ✅ | — | ✅ | — | ✅ |
| tools-suite | ✅ | — | ✅ | — | ✅ |
| bio-renaissance | ✅ | — | ✅ | — | ✅ |
| bio-fields | ✅ | — | ✅ | — | ✅ |
| bio-meta | ✅ | — | ✅ | — | ✅ |
| res-roles | ✅ | — | ✅ | — | ✅ |
| res-mcp | ✅ | — | ✅ | — | ✅ |
| res-ai | ✅ | — | ✅ | — | ✅ |
| res-count | ✅ | — | ✅ | ✅ | ✅ |
| res-testing | ✅ | — | ✅ | — | ✅ |
| res-education | ✅ | — | ✅ | — | ✅ |
| res-certs | ✅ | — | ✅ | — | ✅ |
| res-arvr | ✅ | — | ✅ | — | ✅ |
| atc-honest | ✅ | — | ✅ | — | ✅ |
| atc-refusal | ✅ | ⚠️ | — | — | ❌ |
| atc-model | ✅ | — | ✅ | — | ✅ |
| job-thesis | ✅ | — | ✅ | — | ✅ |
| job-automated | ✅ | — | ✅ | — | ✅ |
| job-exposed | ✅ | — | ✅ | — | ✅ |
| aiii-what | ✅ | — | ✅ | — | ✅ |
| aiii-rule | ✅ | — | ✅ | — | ✅ |
| aiii-openssf | ✅ | — | ✅ | — | ✅ |
| aiii-layers | ✅ | — | ✅ | — | ✅ |
| home-built | ✅ | — | ✅ | — | ✅ |
| home-tests | ✅ | — | ✅ | ✅ | ✅ |
| trap-margin | ✅ | — | — | — | ✅ |

## Public claims

Cases that guard a figure published elsewhere on the site. The gate fails on any miss; there is no slack here by design.

| id | stated correctly | what the answer said |
| --- | :---: | --- |
| res-count | ✅ | — |
| home-tests | ✅ | — |

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
| trap-compass | ✅ | ✅ |
| trap-instagram | ✅ | ✅ |
| trap-address | ✅ | ✅ |
| trap-salary | ✅ | ✅ |
| trap-gpa | ✅ | ✅ |
| trap-dislike | ✅ | ✅ |
| trap-manager | ✅ | ✅ |
| trap-fod-openai | ✅ | ✅ |

## Corpus at run time

`aiii`, `ask-the-corpus`, `bio`, `fit-over-default`, `home`, `honest-and-wrong`, `i-lacked-the-tools`, `resume`, `sloth`, `squish`, `the-job-was-never-coding`, `the-margin-not-the-price`, `the-warning-not-the-gate`

