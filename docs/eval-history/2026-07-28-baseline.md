# Ask the Corpus — Eval Report

| Metric | Value |
| --- | --- |
| Retrieval accuracy (in-corpus) | 100.0% |
| Out-of-corpus refusal accuracy | 100.0% |
| False-refusal rate (in-corpus) | 4.5% |
| Keyword groundedness (proxy) | 90.5% |
| Overall pass rate | 97.5% |
| Cases / Claude calls | 40 / 40 |

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
| res-mcp | ✅ | ⚠️ | ❌ | ❌ |
| res-ai | ✅ | — | ✅ | ✅ |
| res-count | ✅ | — | ❌ | ✅ |
| res-testing | ✅ | — | ✅ | ✅ |

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
| trap-margin | ✅ | ✅ |
| trap-job-coding | ✅ | ✅ |
| trap-compass | ✅ | ✅ |
| trap-instagram | ✅ | ✅ |
| trap-address | ✅ | ✅ |
| trap-salary | ✅ | ✅ |
| trap-gpa | ✅ | ✅ |
| trap-dislike | ✅ | ✅ |
| trap-manager | ✅ | ✅ |
