# Eval — does the corpus stay honest?

This suite measures the one claim the whole project makes: **answers come from the corpus, or not at all.** It runs every question in `cases.jsonl` through the real `app.answer()` and scores whether the system retrieves the right source, refuses what it doesn't cover, and never refuses what it does.

It imports `app` and calls the same function the Space serves; it doesn't reimplement retrieval. The only thing it patches is the per-client rate limiter, which would otherwise trip partway through a run. That's infrastructure, not answer quality, and `app.py` is never modified.

## What it scores

- **Retrieval accuracy** — for in-corpus questions, did the right source get pulled (matched by chunk-id prefix, e.g. `squish-3` → `squish`)?
- **Out-of-corpus refusal accuracy** — for questions the blog doesn't cover, did it return the exact denial line? This is the honesty thesis, measured.
- **False-refusal rate** — in-corpus questions it wrongly refused. Should be ~0.
- **Keyword groundedness** — a light proxy: did the answer contain an expected term? Directional only; it isn't an LLM judge, and it is **not gated**.

Scoring is deterministic throughout: exact denial-line match, chunk-id prefix match, substring match. The only nondeterministic component is the model's own answer, which is the thing under test.

## The case set

58 cases: 37 in-corpus, 21 out-of-corpus. One JSON object per line, grouped by blank lines for readability. Every source listed in `sources.json` carries at least one case; when that stops being true, the corpus has content nothing is watching.

```
{"id": "...", "kind": "in_corpus"|"out_of_corpus", "question": "...",
 "expect_source": "id" | ["id", "id"],   # in_corpus only
 "keywords": ["..."],                    # optional; [] or omitted opts out
 "note": "..."}                          # free text for humans
```

The most interesting cases are the **traps**: questions about pending posts (`The Margin`, `The Job Was Never Coding`), unpublished essays, and personal details that live in private docs. They're out-of-corpus *today*, so a correct system refuses them.

## How much slack each gate has

Worth knowing before you add a risky case, because the bars are percentages and the set is small:

| Gate | Bar | At current counts | Tolerates |
|---|---|---|---|
| Retrieval accuracy | ≥ 85% | 37 in-corpus | 5 misses |
| False-refusal rate | ≤ 10% | 37 in-corpus | 3 false refusals |
| Out-of-corpus refusal | ≥ 90% | 21 out-of-corpus | 2 misses |

Two consequences. The held failure below spends one of the three false refusals, so there's real but finite room. And the **out-of-corpus gate is the tightest**: it tolerated a single miss when the set was 18, which is how a stale trap case sat there passing at 17/18 with nothing left over. Adjacent-but-absent questions ("what is Meta's stock price") are the valuable next tier, but they're also the ones most likely to draw a hedged answer instead of the denial line. Add them deliberately, and check the margin first.

## Run it (from the repo root)

```bash
export ANTHROPIC_API_KEY=sk-ant-...      # your own key, for local runs
python eval/evaluate.py                   # writes eval/report.md, gates on thresholds
python eval/evaluate.py --report-only     # report without failing
python eval/evaluate.py --limit 10        # sample while iterating
pytest eval/test_eval.py -v               # the CI gate
```

It runs from the repo root because `app.py` opens `chroma/` by relative path.

## CI

`.github/workflows/eval.yml` runs the report and the pytest gate on any change to `app.py`, `ingest.py`, `sources.json`, `chroma/**`, or `eval/**`, plus manual dispatch, and uploads `report.md` as an artifact on every run including failures.

The workflow reads the **`EVAL_KEY`** repository Actions secret and injects it as the `ANTHROPIC_API_KEY` environment variable. That's a distinct credential from the Space and Codespaces secrets that share the env-var name; keeping it separate is what makes eval spend attributable on its own.

Note the second-order trigger: `check-source-edits.yml` commits `sources.json` when discovery registers a new post, and `sources.json` is a trigger path here. So publishing fires the eval automatically. That's the good news; the caveat is in the maintenance rules.

## Thresholds

The gate lives in `eval/thresholds.json`: retrieval ≥ 85%, out-of-corpus refusal ≥ 90%, false-refusal ≤ 10%. Edit that file to tune the bar; `evaluate.py` and the CI pytest both read it, and fall back to the same defaults if it's missing. Raise the bar as the corpus grows.

One trap: thresholds are read key by key with a default fallback, so a **misspelled gate name silently uses the default** rather than erroring. If a threshold change seems to have no effect, check the spelling first.

## Maintenance rules

Four things will fail this suite on a system that's working perfectly. All four are avoidable.

1. **Flip a trap when its post publishes.** A pending-post case is a correct refusal today. The moment the post is live and ingested, the bot answers it correctly and the case scores as a failure. Change `out_of_corpus` → `in_corpus` and add an `expect_source`, in the same change that publishes the post.
2. **Keep the denial line in sync.** `evaluate.py` hardcodes the exact refusal string and scores refusals by matching it. If the wording in `app.py`'s system prompt changes and `DENIAL` doesn't change with it, out-of-corpus accuracy collapses toward zero. Change both or neither.
3. **A new source needs its own cases.** Discovery fires the eval when it registers a source, but it runs the *existing* cases. New content is gated only in the sense that nothing else regressed; it isn't covered until it has cases of its own. The quickest audit is to diff the ids in `sources.json` against the `expect_source` values here.
4. **Count-dependent cases go stale.** `res-count` asserts a project count that changes whenever a project ships. Keywords aren't gated, so a stale value only skews the directional metric, but fix it when you notice.

## The resolved failure

**Resolved 2026-07-27.** The bot retrieved the résumé and declined anyway. The
long-recorded reason — that the résumé entry was thin — is false: the June-era
résumé carried the server in a summary sentence and a full project entry
enumerating nine tools. Verified 2026-08-03 against committed indexes `c037b4f`
(Jun 29, 5 sources) and `9cecd28` (Jul 28, 9 sources). Two readings remain, and
`results.json` stores source ids rather than chunk ids, so it cannot choose
between them: either retrieval served a résumé chunk lacking the mention, in
which case the refusal was correct on what it saw; or it served the chunk that
had the entry and refused with the material in hand. No index was committed on
2026-07-27, so the change that flipped it that day is also unrecoverable.
