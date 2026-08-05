# Eval — does the corpus stay honest?

This suite measures the one claim the whole project makes: **answers come from the corpus, or not at all.** It runs every question in `cases.jsonl` through the real `app.answer()` and scores whether the system retrieves the right source, refuses what it doesn't cover, and never refuses what it does.

It imports `app` and calls the same function the Space serves; it doesn't reimplement retrieval. The only thing it patches is the per-client rate limiter, which would otherwise trip partway through a run. That's infrastructure, not answer quality, and `app.py` is never modified.

## What it scores

- **Retrieval accuracy** — for in-corpus questions, did the right source get pulled (matched by chunk-id prefix, e.g. `squish-3` → `squish`)?
- **Out-of-corpus refusal accuracy** — for questions the blog doesn't cover, did it return the exact denial line? This is the honesty thesis, measured.
- **False-refusal rate** — in-corpus questions it wrongly refused. Should be ~0.
- **Keyword groundedness** — a light proxy: did the answer contain an expected term? Directional only; it isn't an LLM judge, and it is **not gated**.

Scoring is deterministic throughout: exact denial-line match, chunk-id prefix match, substring match. The only nondeterministic component is the model's own answer, which is the thing under test.

**Known limit: `retrieval_hit` is source-level, not chunk-level.** A case scores a hit when a chunk from an expected source appears in the top-k, regardless of whether the answer was built from it. `atc-model` demonstrates this: it hits on an `ask-the-corpus` chunk at rank 3, then answers largely from `fit-over-default`. The metric measures presence in the window, not provenance of the answer. Documented limit, not a defect — but don't read a green `retrieval_hit` as proof the answer came from the right place.

## The case set

**60 cases, frozen at 60 by decision (August 5, 2026).** One JSON object per line, grouped by blank lines for readability.

The suite no longer grows because a source arrived. **Admission requires that a case teach the suite something it cannot already see:** a new content shape, a new failure mode, or a public claim that depends on it. `home-tests` guards the published 5,000+ floor and `res-count` guards the nine-project figure; those earn their places. "A new post shipped" does not.

**The total is stable; the split is not.** A trap flips `out_of_corpus` → `in_corpus` when its post publishes — edited, not added — so the count holds at 60 while the split slides. It currently sits at 38/22, and two flips are already armed: `trap-margin` waits on "The Margin, Not the Price," and `trap-compass` on the unpublished "Without a Compass." That is why the split is machine-checked in `rnv-brand/profile.json` and never printed on a public surface: **publish a figure only if it changes on a human decision the publisher makes.**

```
{"id": "...", "kind": "in_corpus"|"out_of_corpus", "question": "...",
 "expect_source": "id" | ["id", "id"],   # in_corpus only
 "keywords": ["..."],                    # optional; [] or omitted opts out
 "note": "..."}                          # free text for humans
```

**Every source in `sources.json` currently carries at least one case** — ten sources, ten covered, first met on August 5, 2026 when `fit-over-default` gained `fod-two-systems` and `trap-fod-openai`. Treat that as the current state, not an invariant: under the freeze, **a future source may deliberately go uncovered**, and the coverage guard reports it as a note rather than a failure. An uncovered source is a decision to be able to defend, not a gap to close by reflex — but it does mean the corpus holds content nothing is watching, so make the call knowingly.

Keep notes short. They're free text for humans, but this is a data file, not a document: a note that runs past a few hundred characters belongs in the Ecosystem Master with a pointer here. Long lines also stop syntax highlighting in most editors, which is a useful smell.

The most interesting cases are the **traps**: questions about pending posts (`The Margin, Not the Price`), unpublished essays (`Without a Compass`), and personal details that live in private docs. They're out-of-corpus *today*, so a correct system refuses them.

## How much slack each gate has

Worth knowing before you add a risky case, because the bars are percentages and the set is small:

| Gate | Bar | At current counts | Tolerates |
|---|---|---|---|
| Retrieval accuracy | ≥ 85% | 38 in-corpus | 5 misses |
| False-refusal rate | ≤ 10% | 38 in-corpus | 3 false refusals |
| Out-of-corpus refusal | ≥ 90% | 22 out-of-corpus | 2 misses |

Two consequences. **One false refusal is currently spent** — `atc-refusal`, diagnosed below — so there is real but finite room. And the **out-of-corpus gate is the tightest**: it tolerated a single miss back when the set was 18, which is how a stale trap case once sat there passing at 17/18 with nothing left over. Adjacent-but-absent questions ("what is Meta's stock price") are the valuable next tier, but they're also the ones most likely to draw a hedged answer instead of the denial line. Add them deliberately, and check the margin first.

## Run it (from the repo root)

```bash
export ANTHROPIC_API_KEY=sk-ant-...        # your own key, for local runs
python eval/check_index_coverage.py        # FIRST: fails in ~1s if the index is missing a source a case expects
python eval/evaluate.py                    # writes eval/report.md, gates on thresholds
python eval/evaluate.py --report-only      # report without failing
python eval/evaluate.py --limit 10         # sample while iterating
python eval/why.py "<question>" "<phrase>" # rank a question, locate a phrase, see if its chunk made the window
pytest eval/test_eval.py -v                # the CI gate
```

It runs from the repo root because `app.py` opens `chroma/` by relative path.

Run the coverage guard before anything that spends money. It reads the index directly, needs no network and no API key, and it turns the single most misleading failure mode in this suite into a one-second error instead of a full run's worth of Claude calls.

## CI

`.github/workflows/eval.yml` runs on any change to `app.py`, `ingest.py`, `sources.json`, `chroma/**`, or `eval/**`, plus manual dispatch. Steps:

1. **Install deps**
2. **`check_index_coverage.py`** — the guard; fails fast, before any Claude spend
3. **`evaluate.py --report-only`** — always writes the report
4. **`pytest eval/test_eval.py -v`** — the gate
5. Upload `report.md` as an artifact, on every run including failures

**CI does not ingest.** It evaluates the **committed `chroma/`**, which is itself a trigger path. The invariant is not "the index is current" but **"the index contains every source the cases reference"** — an index a post behind is harmless; an index missing a source a case expects is fatal and reads as a broken bot. The guard enforces exactly that, and nothing else does.

The workflow reads the **`EVAL_KEY`** repository Actions secret and injects it as the `ANTHROPIC_API_KEY` environment variable. That's a distinct credential from the Space and Codespaces secrets that share the env-var name; keeping it separate is what makes eval spend attributable on its own.

Note the second-order trigger: `check-source-edits.yml` commits `sources.json` when discovery registers a new post, and `sources.json` is a trigger path here. So publishing fires the eval automatically. That's the good news; the caveat is in the maintenance rules.

## Thresholds

The gate lives in `eval/thresholds.json`: retrieval ≥ 85%, out-of-corpus refusal ≥ 90%, false-refusal ≤ 10%. Edit that file to tune the bar; `evaluate.py` and the CI pytest both read it, and fall back to the same defaults if it's missing. Raise the bar as the corpus grows.

One trap: thresholds are read key by key with a default fallback, so a **misspelled gate name silently uses the default** rather than erroring. If a threshold change seems to have no effect, check the spelling first.

## Maintenance rules

Five things will fail this suite on a system that's working perfectly. All five are avoidable.

1. **Flip a trap when its post publishes.** A pending-post case is a correct refusal today. The moment the post is live and ingested, the bot answers it correctly and the case scores as a failure. Change `out_of_corpus` → `in_corpus` and add an `expect_source`, in the same change that publishes the post.
2. **Keep the denial line in sync.** `evaluate.py` hardcodes the exact refusal string and scores refusals by matching it. If the wording in `app.py`'s system prompt changes and `DENIAL` doesn't change with it, out-of-corpus accuracy collapses toward zero. Change both or neither.
3. **A new source needs its own cases.** Discovery fires the eval when it registers a source, but it runs the *existing* cases. New content is gated only in the sense that nothing else regressed; it isn't covered until it has cases of its own. The quickest audit is to diff the ids in `sources.json` against the `expect_source` values here.
4. **A new source also perturbs the cases you already have.** At `top_k = 5` over roughly 49 chunks, an added source competes for slots across a dozen-plus cases — it took one inside the `atc-refusal` window. Adding a source changes the behaviour of cases that are already gated, not just the coverage of ones that aren't.
5. **Count-dependent cases go stale.** `res-count` asserts a project count that changes whenever a project ships. Keywords aren't gated, so a stale value only skews the directional metric, but fix it when you notice. `home-tests` is the same shape and deliberately keyed to the public **5,000+ floor**, so it changes when the floor steps, not when the underlying number moves.

**Retired rule, kept for the reasoning.** "A stale local index reads as a broken bot" used to live here: a run once read 73% retrieval and 24.3% false refusal, and a single re-ingest took the identical cases to 97.3% and 5.4% — the bot had been correctly refusing content it genuinely didn't have. `check_index_coverage.py` now catches that class before a run starts, which is why it's a guard and not a rule.

## Design note: the corpus describes the machine

Deterministic scoring is this suite's strength and its one recurring trap. A cheap string test run against *this* corpus can collide with the corpus describing itself, because the blog writes about the bot in the bot's own words. It happened three times in one week, in different directions.

- **Over-firing.** `is_refusal` was a plain substring check for the denial line. "The Honest Machine" reproduces that line verbatim, so a correct answer *about that post* contained the string and scored as a refusal.
- **Phantom keyword hits.** The denial line itself contains "corpus", "knowledge", "information", "found" and "here", so a case keyed on any of those scored a groundedness hit *while refusing*. Refused rows now drop out of the metric.
- **Under-firing, twice.** A ratio test missed refusals that append context. A remainder cap missed refusals that add a "here is what the sources do cover" clause, which runs long without being any less of a refusal.

**The settled shape: test structure, not size.** A refusal *leads* with the denial; an answer that quotes the line has to set the quotation up first. `is_refusal` returns true when the normalised answer **starts with** the denial. `REFUSAL_REMAINDER_MAX` survives only as a secondary path, for a refusal that opens with a brief preamble and then says nothing else.

**Residual risk, recorded rather than papered over:** an answer that *opens* by quoting the denial and then discusses it would still be misread. None has appeared. If one does, the fix is a structural marker emitted by `app.py` — a sentinel, or refusal status returned separately from the text — not a fourth heuristic. Three iterations is where string matching stops earning its keep.

**Standing rule:** before adding any string-matching heuristic here, ask whether the corpus contains writing about the system itself. It does, and it will contain more.

## The current failure: `atc-refusal`

One in-corpus case refuses: **`atc-refusal`** — *"What does Christian say made the refusal the design goal?"* Retrieval hits, and it refuses anyway.

**The corpus does contain the answer.** "The Honest Machine" states it in one sentence under "The part that matters," and repeats it in the dek and `og:description`. But a retrieval trace ranks the chunk holding that sentence, `ask-the-corpus-2`, at **position 8**, and the app serves top 5. What reached the model was the essay's closing section — which asserts the machine refuses without saying what made refusal the goal — plus four topically adjacent chunks from other posts. **Given that context, refusing was correct.** `false_refusal` is scoring the pipeline here, not the model's honesty.

**The pattern worth internalising: short chunks outrank long ones.** Ranks 1 and 2 are 126 and 47 words; the 300-word chunks cluster below them. Mean pooling over 300 words averages more topics together and pulls the vector toward the corpus centroid. The short chunks are tail remainders left by the 250-word step — short by accident, winning by construction. That's a chunking artifact presenting as a retrieval preference, and the real fix is structure-aware chunking, not a wider `TOP_K`.

**Not repaired yet, on purpose.** The gate passes with two misses unspent, and a reproducible case where the machine refused correctly while the index under it came up short is worth more as evidence than as a fix.

## The resolved failure

`res-mcp` was this suite's held false refusal: the bot retrieved the résumé and declined rather than answer from it.

**Cause, established 2026-08-04 from the committed index.** `c037b4f` holds four résumé chunks, 1,043 words, and **zero** `color-mcp` mentions — a snapshot fetched around June 21–22, three days before the term entered the page on June 25. The page was never thin. The corpus was, and only the corpus refused.

**It resolved on the 2026-07-27 re-ingest** — the same event described under the maintenance rules, where one `ingest.py` moved the identical cases from 73% retrieval and 24.3% false refusal to 97.3% and 5.4%. `res-mcp` was one of the false refusals that re-ingest cured.

Two earlier explanations are retired. "The résumé entry was too thin" is false. "It began passing when the home page entered the corpus" credits one item for a batch: the home page arrived in the same re-ingest as a month of résumé updates, and `res-mcp` now answers from the résumé with no `home` chunk retrieved at all.

**Related trap: verify the index, not the page.** `ingest.py` fetches live URLs, so a page's git history describes what was published, never what was ingested; a page commit and an index commit on the same day are different documents. Chunk ids compound this — they're positional, so `resume-3` in the June index and `resume-3` today are different spans.

The case now passes on the résumé alone; `home-3` has since fallen to rank 6, outside the five slots the app serves. **A green case can quietly change what it is testing.**

The dated refusal is preserved as `docs/eval-history/2026-06-29-baseline.{md,json}` (retrieval hit, refused, pass fail). It is historical evidence, not a live failure.
