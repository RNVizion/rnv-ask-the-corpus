"""
evaluate.py — honesty + retrieval eval for Ask the Corpus.

Runs every case in eval/cases.jsonl through the REAL pipeline in app.py and scores:

  - retrieval accuracy : for in-corpus questions, did the right source get retrieved?
  - refusal accuracy   : out-of-corpus -> did it return the exact denial line?
                         in-corpus     -> did it NOT refuse (no false refusals)?
  - keyword groundedness: a light proxy — did the answer contain an expected term?
                         (cheap signal, not an LLM judge; treat as directional.
                          Refused rows are excluded, since a denial line can
                          match its own keywords.)

Run from the repo root (app.py uses a relative chroma/ path):

    python eval/evaluate.py                # gate on thresholds, exit 1 on fail
    python eval/evaluate.py --report-only  # never fail; just write the report
    python eval/evaluate.py --limit 10     # sample the first N cases
    python eval/evaluate.py --tag baseline # label the run in the report header

Needs ANTHROPIC_API_KEY in the environment (same key the Space uses).
Writes eval/report.md and eval/results.json.

Every report carries a provenance line: timestamp, commit, model, corpus
fingerprint, and thresholds. Two reports of the same run are otherwise
indistinguishable, and an undated table is weak evidence.

THIS FILE IS THE ONLY THING THAT SPENDS CLAUDE CALLS.
test_eval.py reads the artifact this writes rather than running the suite again.
It used to call run() a second time and overwrite the report, which doubled the
per-run cost, discarded the first run's output, and meant the metrics printed in
the CI log belonged to a run that neither gated nor survived as an artifact.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent
CASES = EVAL_DIR / "cases.jsonl"
REPORT_MD = EVAL_DIR / "report.md"
RESULTS_JSON = EVAL_DIR / "results.json"

# app.py loads the chroma index from a relative "chroma/" path and reads the
# question's client host for rate limiting; run everything as if from the repo root.
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

import app  # noqa: E402  (the real pipeline: answer_with_status(), col, embedder, TOP_K, SYSTEM)

# The eval hammers the pipeline in a tight loop; the per-client rate limiter would
# trip after a handful of calls and poison the run. It's infra, not answer
# quality, so we disable it for the eval only. app.py is left untouched.
app._rate_ok = lambda key=None: True

DENIAL = "The corpus has knowledge, but the information you seek will not be found here."

# A refusal that doesn't lead with the denial is still a refusal if it has little
# else to say. Past this much left over, the denial was quoted inside a real answer.
REFUSAL_REMAINDER_MAX = 200

# One retry on a transport failure before a case is marked errored. A single 529
# should not red a build; a real outage still will, because the retry fails too.
ERROR_RETRIES = 1
ERROR_BACKOFF_SECONDS = 3

# Valid source ids (the prefix on every chunk id, e.g. "squish-3" -> "squish").
LIVE_SOURCE_IDS = {
    s["id"] for s in json.loads((REPO_ROOT / "sources.json").read_text(encoding="utf-8")).get("sources", [])
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def is_refusal(answer_text: str) -> bool:
    """Is the denial line the answer, or is it being quoted inside one?

    Three real failure modes, seen in live runs within one week, pulling in
    different directions:

      - A plain substring test over-fires. "The Honest Machine" reproduces the
        denial verbatim, so a correct answer *about that post* contained the
        string and scored as a refusal. Three in-corpus cases failed on a
        healthy system.
      - A ratio test under-fires. A genuine refusal that appends context falls
        below any fixed share of the answer; two real out-of-corpus refusals
        went undetected and the gate passed by a single case.
      - A remainder cap alone under-fires too. A refusal may add a helpful
        "here's what the sources *do* cover" clause, which runs long without
        making it any less of a refusal.

    So test structure rather than size. A refusal **leads** with the denial;
    an answer that quotes the line has to set the quotation up first. The
    remainder cap stays as a secondary path, for a refusal that opens with a
    brief preamble and then says nothing else.

    Residual risk, recorded rather than papered over: an answer that opens by
    quoting the denial and then discusses it would be misread as a refusal. No
    such answer has appeared; if one does, this needs a marker from app.py
    rather than a fourth heuristic. The error path took exactly that route in
    2026-08: app.answer_with_status returns a status instead of the scorer
    matching on the friendly failure string.
    """
    norm, denial = _norm(answer_text), _norm(DENIAL)
    if denial not in norm:
        return False
    if norm.startswith(denial):
        return True
    return len(norm.replace(denial, "").strip()) < REFUSAL_REMAINDER_MAX


def retrieve(question: str):
    """Re-run retrieval the same way app.answer_with_status does. Returns
    (chunk_ids, source_ids).

    Chunk ids look like '{source_id}-{n}', so rsplit on the last hyphen recovers
    the source id even when the id itself contains hyphens (i-lacked-the-tools-3).
    Both are recorded: the source ids are what the metric scores, the chunk ids
    are what a post-mortem needs. Dropping the chunk ids is why answering one
    question about a June index took a git worktree and a hand-typed query."""
    res = app.col.query(
        query_embeddings=app.embedder.encode([question]).tolist(),
        n_results=app.TOP_K,
        include=["metadatas"],
    )
    chunk_ids = res.get("ids", [[]])[0]
    source_ids = []
    for cid in chunk_ids:
        sid = cid.rsplit("-", 1)[0]
        source_ids.append(sid if sid in LIVE_SOURCE_IDS else cid)
    return chunk_ids, source_ids


def ask(question: str):
    """One question through the real pipeline, with a single retry on error.

    Returns (text, error). An errored case is not a wrong answer; it is an
    unmeasured one, and the difference matters to every denominator below."""
    err = None
    for attempt in range(ERROR_RETRIES + 1):
        text, err = app.answer_with_status(question)
        if err is None:
            return text, None
        if attempt < ERROR_RETRIES:
            time.sleep(ERROR_BACKOFF_SECONDS)
    return text, err


def load_cases(limit=None):
    rows = []
    for line in CASES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows[:limit] if limit else rows


def expected_ids(case):
    exp = case.get("expect_source")
    if exp is None:
        return []
    return exp if isinstance(exp, list) else [exp]


def run(limit=None):
    cases = load_cases(limit)
    rows, calls = [], 0

    for c in cases:
        kind = c["kind"]
        q = c["question"]
        chunk_ids, retrieved = retrieve(q)
        ans, err = ask(q)             # the real path, denial line included
        calls += 1
        refused = is_refusal(ans)

        row = {
            "id": c["id"], "kind": kind, "question": q,
            "retrieved": retrieved,
            "retrieved_chunks": chunk_ids,
            "refused": refused,
            "answer_preview": _norm(ans)[:120],
        }

        if err:
            # Unmeasured, not failed. It scores nothing, gates nothing, and is
            # counted separately so a run full of these cannot read as green.
            row["error"] = err
            row["refused"] = None
            row["pass"] = None
            rows.append(row)
            continue

        if kind == "in_corpus":
            exp = expected_ids(c)
            row["expect_source"] = exp
            row["retrieval_hit"] = any(e in retrieved for e in exp)
            row["false_refusal"] = refused          # in-corpus should NEVER refuse
            kws = [k.lower() for k in c.get("keywords", [])]
            # A refusal can match its own keywords by accident: the denial line
            # contains "corpus", "knowledge", "information", "found" and "here",
            # so a case keyed on any of those scores a hit while refusing.
            # Groundedness is meaningless for a refusal anyway, so refused rows
            # drop out of the proxy metric instead of inflating it.
            row["keyword_hit"] = (
                None if refused
                else (any(k in _norm(ans) for k in kws) if kws else None)
            )
            row["pass"] = row["retrieval_hit"] and not refused
        else:  # out_of_corpus
            row["refusal_correct"] = refused        # should refuse
            row["pass"] = refused
            if c.get("note"):
                row["note"] = c["note"]

        rows.append(row)

    err_rows = [r for r in rows if r.get("error")]
    ok_rows = [r for r in rows if not r.get("error")]
    in_rows = [r for r in ok_rows if r["kind"] == "in_corpus"]
    out_rows = [r for r in ok_rows if r["kind"] == "out_of_corpus"]

    def pct(xs):
        return round(100 * sum(xs) / len(xs), 1) if xs else None

    kw_rows = [r for r in in_rows if r.get("keyword_hit") is not None]
    metrics = {
        "total_cases": len(rows),
        "scored_cases": len(ok_rows),
        "error_cases": len(err_rows),
        "claude_calls": calls,
        "retrieval_accuracy": pct([r["retrieval_hit"] for r in in_rows]),
        "false_refusal_rate": pct([r["false_refusal"] for r in in_rows]),
        "ooc_refusal_accuracy": pct([r["refusal_correct"] for r in out_rows]),
        "keyword_groundedness": pct([r["keyword_hit"] for r in kw_rows]),
        "overall_pass_rate": pct([r["pass"] for r in ok_rows]),
    }
    return metrics, rows


def _git(*args):
    """Best-effort git read; never let a missing git break a run."""
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, cwd=REPO_ROOT, timeout=5
        )
        return out.stdout.strip()
    except Exception:
        return ""


def index_fingerprint():
    """What the index actually holds, not what sources.json says it should.

    These are different documents and have been out of step for a month at a
    time. A report that records the manifest and calls it the corpus repeats,
    inside the instrument, the exact error the res-mcp investigation spent two
    write-ups getting wrong: a page's history describes what was published,
    never what was ingested."""
    try:
        got = app.col.get(include=[])
    except Exception:
        try:
            got = app.col.get()
        except Exception:
            return [], 0
    ids = got.get("ids", [])
    return sorted({cid.rsplit("-", 1)[0] for cid in ids}), len(ids)


def provenance(tag=None):
    """What makes a report self-identifying: when, from which commit, against
    which corpus, with which model and bars. Without this, two runs a month
    apart are indistinguishable tables."""
    sha = _git("rev-parse", "--short", "HEAD") or "unknown"
    dirty = bool(_git("status", "--porcelain"))
    if dirty:
        sha += "-dirty"
    indexed, chunk_count = index_fingerprint()
    declared = sorted(LIVE_SOURCE_IDS)
    return {
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "commit": sha,
        "dirty": dirty,
        "tag": tag,
        "model": getattr(app, "MODEL", "unknown"),
        "temperature": getattr(app, "TEMPERATURE", None),
        "top_k": getattr(app, "TOP_K", None),
        # the index is the thing that was actually queried
        "source_count": len(indexed),
        "sources": indexed,
        "chunk_count": chunk_count,
        # the manifest, kept alongside so drift between them is visible
        "declared_count": len(declared),
        "declared_sources": declared,
        "index_matches_manifest": indexed == declared,
        "thresholds": dict(THRESHOLDS),
    }


def write_report(metrics, rows, tag=None):
    prov = provenance(tag)
    RESULTS_JSON.write_text(
        json.dumps({"provenance": prov, "metrics": metrics, "rows": rows}, indent=2),
        encoding="utf-8",
    )

    def b(v):
        return "✅" if v else "❌"

    label = f" · **{prov['tag']}**" if prov.get("tag") else ""
    lines = ["# Ask the Corpus — Eval Report", ""]
    lines += [
        f"_{prov['generated_at']} · commit `{prov['commit']}`{label}_",
        "",
        f"_{prov['source_count']} sources · {prov['chunk_count']} chunks · "
        f"{metrics['total_cases']} cases · model `{prov['model']}` · "
        f"temp {prov['temperature']} · top-k {prov['top_k']}_",
        "",
        f"_Gates: retrieval ≥ {THRESHOLDS['retrieval_accuracy']}% · "
        f"out-of-corpus refusal ≥ {THRESHOLDS['ooc_refusal_accuracy']}% · "
        f"false refusal ≤ {THRESHOLDS['false_refusal_rate']}%_",
        "",
    ]
    if not prov["index_matches_manifest"]:
        behind = sorted(set(prov["declared_sources"]) - set(prov["sources"]))
        orphan = sorted(set(prov["sources"]) - set(prov["declared_sources"]))
        lines += [
            f"> **Index and manifest differ.** Declared but not indexed: "
            f"{behind or '—'}. Indexed but not declared: {orphan or '—'}. "
            f"Scores below describe the index, which is what the bot answers from.",
            "",
        ]
    if metrics["error_cases"]:
        lines += [
            f"> **{metrics['error_cases']} case(s) errored and were not scored.** "
            f"Percentages below are over {metrics['scored_cases']} cases, not "
            f"{metrics['total_cases']}. A run with errored cases is not a valid "
            f"measurement.",
            "",
        ]
    lines += [
        "| Metric | Value |",
        "| --- | --- |",
        f"| Retrieval accuracy (in-corpus) | {metrics['retrieval_accuracy']}% |",
        f"| Out-of-corpus refusal accuracy | {metrics['ooc_refusal_accuracy']}% |",
        f"| False-refusal rate (in-corpus) | {metrics['false_refusal_rate']}% |",
        f"| Keyword groundedness (proxy) | {metrics['keyword_groundedness']}% |",
        f"| Overall pass rate | {metrics['overall_pass_rate']}% |",
        f"| Cases scored / total | {metrics['scored_cases']} / {metrics['total_cases']} |",
        f"| Errored (unscored) | {metrics['error_cases']} |",
        f"| Claude calls | {metrics['claude_calls']} |",
        "",
        "## In-corpus",
        "| id | retrieved right source | refused? | keyword | pass |",
        "| --- | :---: | :---: | :---: | :---: |",
    ]
    for r in [r for r in rows if r["kind"] == "in_corpus"]:
        if r.get("error"):
            lines.append(f"| {r['id']} | ⚠️ | ⚠️ | ⚠️ | errored |")
            continue
        kw = "—" if r.get("keyword_hit") is None else b(r["keyword_hit"])
        lines.append(f"| {r['id']} | {b(r['retrieval_hit'])} | {'⚠️' if r['refused'] else '—'} | {kw} | {b(r['pass'])} |")

    lines += ["", "## Out-of-corpus (should refuse)", "| id | refused? | pass |", "| --- | :---: | :---: |"]
    for r in [r for r in rows if r["kind"] == "out_of_corpus"]:
        if r.get("error"):
            lines.append(f"| {r['id']} | ⚠️ | errored |")
            continue
        lines.append(f"| {r['id']} | {b(r['refused'])} | {b(r['pass'])} |")

    if metrics["error_cases"]:
        lines += ["", "## Errored cases", "| id | reason |", "| --- | --- |"]
        for r in [r for r in rows if r.get("error")]:
            lines.append(f"| {r['id']} | `{r['error'][:120]}` |")

    lines += ["", "## Corpus at run time", "", ", ".join(f"`{s}`" for s in prov["sources"]), ""]

    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


# Gate thresholds live in eval/thresholds.json so the bar is easy to find and
# tune without editing code. Defaults below are the fallback if the file is gone.
THRESHOLDS_FILE = EVAL_DIR / "thresholds.json"
_DEFAULT_THRESHOLDS = {
    "retrieval_accuracy": 85.0,     # >= this
    "ooc_refusal_accuracy": 90.0,   # >= this
    "false_refusal_rate": 10.0,     # <= this
}


def load_thresholds():
    """A missing FILE falls back to the defaults, deliberately. A missing KEY
    inside a file that exists does not.

    data.get(k, default) treats a typo, a rename, or a half-finished edit as an
    intention to use the default, so the suite keeps passing against a bar
    nobody declared and the resume keeps quoting a gate that enforces nothing.
    Fail loudly instead: an unresolved threshold is an unresolved threshold."""
    try:
        data = json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return dict(_DEFAULT_THRESHOLDS)
    missing = [k for k in _DEFAULT_THRESHOLDS if k not in data]
    if missing:
        raise SystemExit(
            f"{THRESHOLDS_FILE.name} exists but is missing {missing}. "
            f"Falling back to defaults here would enforce a bar nobody declared; "
            f"add the key or delete the file to use defaults on purpose."
        )
    # ignore the _comment key and any stray fields; keep only known gates
    return {k: float(data[k]) for k in _DEFAULT_THRESHOLDS}


THRESHOLDS = load_thresholds()


def gate(metrics):
    failures = []
    if metrics.get("error_cases"):
        failures.append(
            f"{metrics['error_cases']} case(s) errored and were not scored; "
            f"a run with unmeasured cases is not a valid measurement"
        )
    if (metrics["retrieval_accuracy"] or 0) < THRESHOLDS["retrieval_accuracy"]:
        failures.append(f"retrieval_accuracy {metrics['retrieval_accuracy']}% < {THRESHOLDS['retrieval_accuracy']}%")
    if (metrics["ooc_refusal_accuracy"] or 0) < THRESHOLDS["ooc_refusal_accuracy"]:
        failures.append(f"ooc_refusal_accuracy {metrics['ooc_refusal_accuracy']}% < {THRESHOLDS['ooc_refusal_accuracy']}%")
    if (metrics["false_refusal_rate"] or 0) > THRESHOLDS["false_refusal_rate"]:
        failures.append(f"false_refusal_rate {metrics['false_refusal_rate']}% > {THRESHOLDS['false_refusal_rate']}%")
    return failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-only", action="store_true", help="write the report but never exit non-zero")
    ap.add_argument("--limit", type=int, default=None, help="run only the first N cases")
    ap.add_argument("--tag", default=None, help="label this run in the report header (e.g. 'baseline')")
    args = ap.parse_args()

    metrics, rows = run(limit=args.limit)
    write_report(metrics, rows, tag=args.tag)

    print(json.dumps(metrics, indent=2))
    print(f"\nReport: {REPORT_MD}")

    failures = gate(metrics)
    if failures and not args.report_only:
        print("\nGATE FAILED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\nGate passed." if not failures else "\n(report-only: gate not enforced)")


if __name__ == "__main__":
    main()
