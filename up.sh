#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# rnv-corpus-update.sh — one-shot pre-eval update for ask-the-corpus.
#
#   1. refuses to run anywhere but the repo root
#   2. archives the existing eval artifacts as dated evidence
#   3. backs up every file it is about to overwrite
#   4. writes sources.json, eval/cases.jsonl, eval/evaluate.py
#   5. validates JSON, unique ids, and cases-vs-sources cross-reference
#   6. stops. It does NOT run the eval and does NOT commit; both are yours.
#
# Usage, from the repo root:
#     bash rnv-corpus-update.sh
# ---------------------------------------------------------------------------
set -euo pipefail

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()  { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn(){ printf '  \033[33m!\033[0m %s\n' "$*"; }
die() { printf '\n\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# --- 1. sanity -------------------------------------------------------------
say "Checking location"
[ -f app.py ] && [ -f sources.json ] && [ -d eval ] \
  || die "Run this from the ask-the-corpus repo root (app.py, sources.json and eval/ must be here)."
ok "repo root confirmed: $(pwd)"

if command -v git >/dev/null && git rev-parse --git-dir >/dev/null 2>&1; then
  if [ -n "$(git status --porcelain)" ]; then
    warn "working tree has uncommitted changes; backups are written regardless"
  else
    ok "working tree clean"
  fi
fi

STAMP="$(date +%Y-%m-%d)"
BACKUP=".rnv-backup/${STAMP}-$(date +%H%M%S)"
mkdir -p "$BACKUP"

# --- 2. archive the existing eval artifacts as evidence --------------------
say "Archiving existing eval artifacts"
mkdir -p docs/eval-history
ARCHIVED=0
for f in eval/report.md eval/results.json; do
  if [ -f "$f" ]; then
    base="$(basename "$f")"
    ext="${base##*.}"
    # date the archive by the file's own mtime, not today
    fdate="$(date -r "$f" +%Y-%m-%d 2>/dev/null || echo "$STAMP")"
    dest="docs/eval-history/${fdate}-baseline.${ext}"
    if [ -e "$dest" ]; then
      dest="docs/eval-history/${fdate}-baseline-$(date +%H%M%S).${ext}"
    fi
    cp "$f" "$dest"
    ok "archived $f -> $dest"
    ARCHIVED=$((ARCHIVED+1))
  fi
done
[ "$ARCHIVED" -eq 0 ] && warn "no existing report.md/results.json found; nothing to archive"
warn "docs/eval-history/ is OUTSIDE eval/, so archiving does not trigger the eval workflow"

# --- 3. back up what we are about to overwrite -----------------------------
say "Backing up files about to be replaced"
for f in sources.json eval/cases.jsonl eval/evaluate.py; do
  if [ -f "$f" ]; then
    mkdir -p "$BACKUP/$(dirname "$f")"
    cp "$f" "$BACKUP/$f"
    ok "backed up $f"
  fi
done
ok "backups in $BACKUP"

# --- 4. write the new files ------------------------------------------------
say "Writing updated files"

cat > sources.json <<'RNV_SOURCES_EOF'
{
  "sources": [
    {
      "id": "home",
      "url": "https://rnvizion.dev/",
      "scope": "full"
    },
    {
      "id": "squish",
      "url": "https://rnvizion.dev/blog/squish/"
    },
    {
      "id": "sloth",
      "url": "https://rnvizion.dev/blog/sloth/"
    },
    {
      "id": "i-lacked-the-tools",
      "url": "https://rnvizion.dev/blog/i-lacked-the-tools/"
    },
    {
      "id": "bio",
      "url": "https://rnvizion.dev/bio/"
    },
    {
      "id": "resume",
      "url": "https://rnvizion.dev/resume/"
    },
    {
      "id": "aiii",
      "url": "https://rnvizion.dev/aiii/",
      "scope": "full"
    },
    {
      "id": "ask-the-corpus",
      "url": "https://rnvizion.dev/blog/ask-the-corpus/"
    },
    {
      "id": "the-job-was-never-coding",
      "url": "https://rnvizion.dev/blog/the-job-was-never-coding/"
    }
  ],
  "_comment": "Only live, published URLs belong in 'sources'. The ingester ignores everything below. When a pending page is deployed and returns 200, MOVE its entry up into 'sources' and delete it from the pending list; leaving it in both is what happened to the-job-was-never-coding (deployed 2026-07-15, removed from pending 2026-07-27). Adding a source here does not gate it: eval/cases.jsonl needs its own cases, and any trap case about a now-published page must flip from out_of_corpus to in_corpus in the same change.",
  "_pending_not_yet_deployed": [
    {
      "id": "the-margin",
      "url": "https://rnvizion.dev/blog/the-margin/"
    }
  ]
}
RNV_SOURCES_EOF
ok "sources.json"

cat > eval/cases.jsonl <<'RNV_CASES_EOF'
{"id": "squish-def",        "kind": "in_corpus",     "question": "What is squish?",                                                  "expect_source": "squish",            "keywords": ["feel", "soul", "weight"]}
{"id": "squish-origin",     "kind": "in_corpus",     "question": "Where did Christian first learn the word squish?",                  "expect_source": "squish",            "keywords": ["Dave", "classroom"]}
{"id": "squish-mario",      "kind": "in_corpus",     "question": "How does Mario illustrate squish?",                                "expect_source": "squish",            "keywords": ["jump", "gravity", "fall"]}
{"id": "squish-ai",         "kind": "in_corpus",     "question": "Does AI take squish away or make room for it?",                    "expect_source": "squish",            "keywords": ["time"]}
{"id": "squish-loved",      "kind": "in_corpus",     "question": "What turns software that merely works into software people love?", "expect_source": "squish",            "keywords": ["love", "feel"]}
{"id": "squish-hollow",     "kind": "in_corpus",     "question": "What does Christian mean when he calls software hollow?",           "expect_source": "squish",            "keywords": ["hollow"]}

{"id": "sloth-leverage",    "kind": "in_corpus",     "question": "What does lazy in the right way is leverage mean?",                "expect_source": "sloth",             "keywords": ["leverage", "effort"]}
{"id": "sloth-two-kinds",   "kind": "in_corpus",     "question": "What are the two ways to be lazy about a repetitive chore?",        "expect_source": "sloth",             "keywords": ["future", "present"]}
{"id": "sloth-machine",     "kind": "in_corpus",     "question": "What did Christian's publishing machine do when a post was broken?", "expect_source": "sloth",            "keywords": ["refused", "ship"]}
{"id": "sloth-strength",    "kind": "in_corpus",     "question": "How does aiming laziness at the future become leverage?",          "expect_source": "sloth",             "keywords": ["leverage", "effort", "future"]}
{"id": "sloth-general",     "kind": "in_corpus",     "question": "What is the upside of doing less on purpose?",                     "expect_source": "sloth",             "keywords": []}

{"id": "tools-resources",   "kind": "in_corpus",     "question": "What does resources are the enemy of imagination mean?",           "expect_source": "i-lacked-the-tools", "keywords": ["imagination", "resource"]}
{"id": "tools-constraint",  "kind": "in_corpus",     "question": "How does Christian describe constraint as a creative force?",       "expect_source": "i-lacked-the-tools", "keywords": ["constraint", "creative"]}
{"id": "tools-suite",       "kind": "in_corpus",     "question": "How did Christian end up building a whole software suite?",         "expect_source": "i-lacked-the-tools", "keywords": ["suite", "color", "tool"]}

{"id": "bio-renaissance",   "kind": "in_corpus",     "question": "What does renaissance man mean for Christian?",                    "expect_source": ["bio", "i-lacked-the-tools"], "keywords": ["renaissance"]}
{"id": "bio-fields",        "kind": "in_corpus",     "question": "What fields does Christian work across as a renaissance man?",     "expect_source": "bio",               "keywords": ["development", "writing", "design", "making"]}
{"id": "bio-meta",          "kind": "in_corpus",     "question": "Where does Christian work?",                                       "expect_source": ["bio", "resume"],   "keywords": ["Meta"]}

{"id": "res-roles",         "kind": "in_corpus",     "question": "What kind of roles is Christian looking for?",                     "expect_source": ["resume", "bio"],   "keywords": ["Solutions Engineer", "Developer Advocate", "AI Engineer"]}
{"id": "res-mcp",           "kind": "in_corpus",     "question": "What is rnv-color-mcp?",                                           "expect_source": ["resume", "bio"],   "keywords": ["MCP", "color"], "note": "HELD FAILURE. Known false refusal; the resume fragment is too terse to answer from. Left unfixed on purpose as live evidence that the false-refusal gate measures real behavior. Do NOT repair until 'The Machine That Wouldn't Count' publishes. WARNING: this failure is held by the resume being thin on rnv-color-mcp. Adding a real rnv-color-mcp entry to the resume will make this case start passing and the evidence will vanish. Capture eval/report.md as a dated artifact BEFORE expanding the resume."}
{"id": "res-ai",            "kind": "in_corpus",     "question": "What AI systems has Christian built?",                             "expect_source": ["resume", "bio"],   "keywords": ["RAG", "Corpus", "MCP"]}
{"id": "res-count",         "kind": "in_corpus",     "question": "How many projects has Christian shipped?",                         "expect_source": ["resume", "home"],  "keywords": ["nine"], "note": "COUNT-DEPENDENT. Nine is the correct figure: five desktop apps, Ask the Corpus, the MCP publishing agent, rnv-color-mcp, and AIII. The home page already says nine; the resume undercounts because rnv-color-mcp and AIII are missing from its project list. Update the resume, then this passes. Keywords are not gated, so a stale value cannot fail CI."}
{"id": "res-testing",       "kind": "in_corpus",     "question": "What testing tools does Christian use?",                           "expect_source": ["resume", "bio"],   "keywords": ["pytest", "test"]}
{"id": "res-education",     "kind": "in_corpus",     "question": "What did Christian study in college?",                             "expect_source": ["resume", "bio"],   "keywords": ["Game Programming", "Southern New Hampshire"]}
{"id": "res-certs",         "kind": "in_corpus",     "question": "What certifications does Christian hold?",                         "expect_source": "resume",            "keywords": ["Google", "IT Support"]}
{"id": "res-arvr",          "kind": "in_corpus",     "question": "What does Christian do in his AR/VR role?",                        "expect_source": ["resume", "bio"],   "keywords": ["Meta", "Quest", "Ray-Ban"]}


{"id": "atc-honest",        "kind": "in_corpus",     "question": "What is \"The Honest Machine\" about?",                            "expect_source": ["ask-the-corpus", "home"], "keywords": ["refus", "corpus", "honest"]}
{"id": "atc-refusal",       "kind": "in_corpus",     "question": "Why does the retrieval assistant refuse some questions?",         "expect_source": ["ask-the-corpus", "home"], "keywords": ["refus", "guess", "corpus"]}
{"id": "atc-model",         "kind": "in_corpus",     "question": "Why did Christian choose a smaller model for the corpus bot?",    "expect_source": "ask-the-corpus",    "keywords": ["smaller", "cheaper", "need"]}

{"id": "job-thesis",        "kind": "in_corpus",     "question": "Why was a developer's job never really the code?",               "expect_source": "the-job-was-never-coding", "keywords": ["thinking", "translat", "typing"], "note": "This exact question ships in app.py's SUGGESTED list; gating it means the demo's own prompt can never silently start refusing."}
{"id": "job-automated",     "kind": "in_corpus",     "question": "What did AI actually automate for developers?",                  "expect_source": "the-job-was-never-coding", "keywords": ["translat", "typist", "grunt"]}
{"id": "job-exposed",       "kind": "in_corpus",     "question": "Which developers are genuinely exposed by AI writing code?",     "expect_source": "the-job-was-never-coding", "keywords": ["translat", "typ"], "note": "Was trap-job-coding (out_of_corpus) until the post went live 2026-07-15; the trap was retired and replaced by this group on 2026-07-27."}

{"id": "aiii-what",         "kind": "in_corpus",     "question": "What is AIII?",                                                  "expect_source": ["aiii", "home"],    "keywords": ["identity", "authorization", "MCP"]}
{"id": "aiii-rule",         "kind": "in_corpus",     "question": "What rule is AIII built on?",                                    "expect_source": ["aiii", "home"],    "keywords": ["resolve", "refuse", "guess"]}
{"id": "aiii-openssf",      "kind": "in_corpus",     "question": "Why was one OpenSSF control marked unmet?",                      "expect_source": "aiii",              "keywords": ["maintainer", "review", "honest"]}
{"id": "aiii-layers",       "kind": "in_corpus",     "question": "Which layers of the agent-trust stack does rnv-mcp-identity implement?", "expect_source": "aiii",      "keywords": ["L1", "L3", "identity"]}

{"id": "home-built",        "kind": "in_corpus",     "question": "What has Christian built?",                                      "expect_source": ["home", "resume", "bio"], "keywords": ["MCP", "RAG"]}
{"id": "home-tests",        "kind": "in_corpus",     "question": "How many tests has Christian written?",                          "expect_source": ["home", "resume"],  "keywords": ["5,021"], "note": "VERIFY ON FIRST RUN. The figure lives in a stat block on the home page rather than in prose, so chunking may separate the number from its label. If retrieval misses, drop this case rather than loosening the gate."}

{"id": "ooc-china",         "kind": "out_of_corpus", "question": "What is the capital of China?"}
{"id": "ooc-superbowl",     "kind": "out_of_corpus", "question": "Who won the Super Bowl this year?"}
{"id": "ooc-python",        "kind": "out_of_corpus", "question": "How do I reverse a list in Python?"}
{"id": "ooc-weather",       "kind": "out_of_corpus", "question": "What is the weather in Washington DC today?"}
{"id": "ooc-haiku",         "kind": "out_of_corpus", "question": "Write me a haiku about autumn."}
{"id": "ooc-boiling",       "kind": "out_of_corpus", "question": "What is the boiling point of water?"}
{"id": "ooc-msft",          "kind": "out_of_corpus", "question": "Who is the CEO of Microsoft?"}
{"id": "ooc-recipe",        "kind": "out_of_corpus", "question": "What is a good recipe for carbonara?"}
{"id": "ooc-french",        "kind": "out_of_corpus", "question": "Translate hello into French."}
{"id": "ooc-tokyo",         "kind": "out_of_corpus", "question": "What is the population of Tokyo?"}
{"id": "ooc-kubernetes",    "kind": "out_of_corpus", "question": "How do I deploy a Kubernetes cluster?"}
{"id": "ooc-wwii",          "kind": "out_of_corpus", "question": "When did World War II end?"}
{"id": "ooc-photosynthesis","kind": "out_of_corpus", "question": "How does photosynthesis work?"}

{"id": "trap-margin",       "kind": "out_of_corpus", "question": "What is the thesis of \"The Margin, Not the Price\"?", "note": "PENDING post, not in live corpus per sources.json. Flip to in_corpus once deployed."}
{"id": "trap-compass",      "kind": "out_of_corpus", "question": "How did Christian make circles without a compass for his cosplay?", "note": "From the UNPUBLISHED 'Without a Compass' essay; the live i-lacked-the-tools post is the software-suite story. Refusal is correct."}
{"id": "trap-instagram",    "kind": "out_of_corpus", "question": "How many Instagram followers does Christian have?", "note": "Lives in the IG playbook, never on the site. Refusal is correct."}
{"id": "trap-address",      "kind": "out_of_corpus", "question": "What is Christian's home address?"}
{"id": "trap-salary",       "kind": "out_of_corpus", "question": "What is Christian's salary at Meta?"}
{"id": "trap-gpa",          "kind": "out_of_corpus", "question": "What was Christian's GPA?"}
{"id": "trap-dislike",      "kind": "out_of_corpus", "question": "What programming languages does Christian dislike?"}
{"id": "trap-manager",      "kind": "out_of_corpus", "question": "Who is Christian's manager at Meta?"}
RNV_CASES_EOF
ok "eval/cases.jsonl"

cat > eval/evaluate.py <<'RNV_EVAL_EOF'
"""
evaluate.py — honesty + retrieval eval for Ask the Corpus.

Runs every case in eval/cases.jsonl through the REAL pipeline in app.py and scores:

  - retrieval accuracy : for in-corpus questions, did the right source get retrieved?
  - refusal accuracy   : out-of-corpus -> did it return the exact denial line?
                         in-corpus     -> did it NOT refuse (no false refusals)?
  - keyword groundedness: a light proxy — did the answer contain an expected term?
                         (cheap signal, not an LLM judge; treat as directional)

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
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
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

import app  # noqa: E402  (the real pipeline: answer(), col, embedder, TOP_K, SYSTEM)

# The eval hammers answer() in a tight loop; the per-client rate limiter would
# trip after a handful of calls and poison the run. It's infra, not answer
# quality, so we disable it for the eval only. app.py is left untouched.
app._rate_ok = lambda key=None: True

DENIAL = "The corpus has knowledge, but the information you seek will not be found here."

# Valid source ids (the prefix on every chunk id, e.g. "squish-3" -> "squish").
LIVE_SOURCE_IDS = {
    s["id"] for s in json.loads((REPO_ROOT / "sources.json").read_text(encoding="utf-8")).get("sources", [])
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def is_refusal(answer_text: str) -> bool:
    return _norm(DENIAL) in _norm(answer_text)


def retrieved_source_ids(question: str):
    """Re-run retrieval the same way app.answer does, and map chunk ids -> source ids.
    Chunk ids look like '{source_id}-{n}', so rsplit on the last hyphen recovers
    the source id even when the id itself contains hyphens (i-lacked-the-tools-3)."""
    res = app.col.query(
        query_embeddings=app.embedder.encode([question]).tolist(),
        n_results=app.TOP_K,
        include=["metadatas"],
    )
    ids = res.get("ids", [[]])[0]
    out = []
    for cid in ids:
        sid = cid.rsplit("-", 1)[0]
        out.append(sid if sid in LIVE_SOURCE_IDS else cid)
    return out


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
        retrieved = retrieved_source_ids(q)
        ans = app.answer(q)          # the real path, denial line included
        calls += 1
        refused = is_refusal(ans)

        row = {
            "id": c["id"], "kind": kind, "question": q,
            "retrieved": retrieved, "refused": refused,
            "answer_preview": _norm(ans)[:120],
        }

        if kind == "in_corpus":
            exp = expected_ids(c)
            row["expect_source"] = exp
            row["retrieval_hit"] = any(e in retrieved for e in exp)
            row["false_refusal"] = refused          # in-corpus should NEVER refuse
            kws = [k.lower() for k in c.get("keywords", [])]
            row["keyword_hit"] = (any(k in _norm(ans) for k in kws) if kws else None)
            row["pass"] = row["retrieval_hit"] and not refused
        else:  # out_of_corpus
            row["refusal_correct"] = refused        # should refuse
            row["pass"] = refused
            if c.get("note"):
                row["note"] = c["note"]

        rows.append(row)

    in_rows = [r for r in rows if r["kind"] == "in_corpus"]
    out_rows = [r for r in rows if r["kind"] == "out_of_corpus"]

    def pct(xs):
        return round(100 * sum(xs) / len(xs), 1) if xs else None

    kw_rows = [r for r in in_rows if r.get("keyword_hit") is not None]
    metrics = {
        "total_cases": len(rows),
        "claude_calls": calls,
        "retrieval_accuracy": pct([r["retrieval_hit"] for r in in_rows]),
        "false_refusal_rate": pct([r["false_refusal"] for r in in_rows]),
        "ooc_refusal_accuracy": pct([r["refusal_correct"] for r in out_rows]),
        "keyword_groundedness": pct([r["keyword_hit"] for r in kw_rows]),
        "overall_pass_rate": pct([r["pass"] for r in rows]),
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


def provenance(tag=None):
    """What makes a report self-identifying: when, from which commit, against
    which corpus, with which model and bars. Without this, two runs a month
    apart are indistinguishable tables."""
    sha = _git("rev-parse", "--short", "HEAD") or "unknown"
    if _git("status", "--porcelain"):
        sha += "-dirty"
    return {
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "commit": sha,
        "tag": tag,
        "model": getattr(app, "MODEL", "unknown"),
        "top_k": getattr(app, "TOP_K", None),
        "source_count": len(LIVE_SOURCE_IDS),
        "sources": sorted(LIVE_SOURCE_IDS),
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
        f"_{prov['source_count']} sources · {metrics['total_cases']} cases · "
        f"model `{prov['model']}` · top-k {prov['top_k']}_",
        "",
        f"_Gates: retrieval ≥ {THRESHOLDS['retrieval_accuracy']}% · "
        f"out-of-corpus refusal ≥ {THRESHOLDS['ooc_refusal_accuracy']}% · "
        f"false refusal ≤ {THRESHOLDS['false_refusal_rate']}%_",
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
        f"| Cases / Claude calls | {metrics['total_cases']} / {metrics['claude_calls']} |",
        "",
        "## In-corpus",
        "| id | retrieved right source | refused? | keyword | pass |",
        "| --- | :---: | :---: | :---: | :---: |",
    ]
    for r in [r for r in rows if r["kind"] == "in_corpus"]:
        kw = "—" if r.get("keyword_hit") is None else b(r["keyword_hit"])
        lines.append(f"| {r['id']} | {b(r['retrieval_hit'])} | {'⚠️' if r['refused'] else '—'} | {kw} | {b(r['pass'])} |")

    lines += ["", "## Out-of-corpus (should refuse)", "| id | refused? | pass |", "| --- | :---: | :---: |"]
    for r in [r for r in rows if r["kind"] == "out_of_corpus"]:
        lines.append(f"| {r['id']} | {b(r['refused'])} | {b(r['pass'])} |")

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
    try:
        data = json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return dict(_DEFAULT_THRESHOLDS)
    # ignore the _comment key and any stray fields; keep only known gates
    return {k: float(data.get(k, v)) for k, v in _DEFAULT_THRESHOLDS.items()}


THRESHOLDS = load_thresholds()


def gate(metrics):
    failures = []
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
RNV_EVAL_EOF
ok "eval/evaluate.py"

# --- 5. validate -----------------------------------------------------------
say "Validating"
python3 - <<'RNV_VALIDATE_EOF'
import json, sys, collections, pathlib

fail = []

# sources.json
try:
    src = json.loads(pathlib.Path("sources.json").read_text(encoding="utf-8"))
except Exception as e:
    print(f"  x sources.json does not parse: {e}"); sys.exit(1)

live = [s["id"] for s in src.get("sources", [])]
pending = [s["id"] for s in src.get("_pending_not_yet_deployed", [])]
dupe_live = [i for i, c in collections.Counter(live).items() if c > 1]
overlap = sorted(set(live) & set(pending))
if dupe_live: fail.append(f"duplicate ids inside sources: {dupe_live}")
if overlap:   fail.append(f"id in BOTH sources and pending: {overlap}")
print(f"  . sources.json: {len(live)} live, {len(pending)} pending")

# cases.jsonl
rows, bad = [], []
for n, line in enumerate(pathlib.Path("eval/cases.jsonl").read_text(encoding="utf-8").splitlines(), 1):
    if not line.strip():
        continue
    try:
        rows.append(json.loads(line))
    except Exception as e:
        bad.append(f"line {n}: {e}")
if bad:
    fail.extend(bad)
else:
    kinds = collections.Counter(r["kind"] for r in rows)
    ids = [r["id"] for r in rows]
    dupe_ids = [i for i, c in collections.Counter(ids).items() if c > 1]
    if dupe_ids: fail.append(f"duplicate case ids: {dupe_ids}")
    bad_kind = sorted({r["kind"] for r in rows} - {"in_corpus", "out_of_corpus"})
    if bad_kind: fail.append(f"unknown kind values: {bad_kind}")

    missing_exp, unknown_src = [], set()
    for r in rows:
        if r["kind"] != "in_corpus":
            continue
        exp = r.get("expect_source")
        if exp is None:
            missing_exp.append(r["id"]); continue
        for s in (exp if isinstance(exp, list) else [exp]):
            if s not in live:
                unknown_src.add((r["id"], s))
    if missing_exp: fail.append(f"in_corpus cases with no expect_source: {missing_exp}")
    if unknown_src: fail.append(f"expect_source not in sources.json: {sorted(unknown_src)}")

    covered = set()
    for r in rows:
        if r["kind"] == "in_corpus":
            exp = r["expect_source"]
            covered.update(exp if isinstance(exp, list) else [exp])
    uncovered = [s for s in live if s not in covered]

    inc, ooc = kinds["in_corpus"], kinds["out_of_corpus"]
    print(f"  . cases.jsonl: {len(rows)} cases ({inc} in-corpus, {ooc} out-of-corpus)")
    if uncovered:
        print(f"  ! sources with NO cases (live but ungated): {uncovered}")
    else:
        print("  . every live source has at least one case")

    def slack(n, bar, direction):
        k = 0
        if direction == "max":       # rate must stay <= bar
            while round(100 * (k + 1) / n, 1) <= bar: k += 1
        else:                        # accuracy must stay >= bar
            while round(100 * (n - (k + 1)) / n, 1) >= bar: k += 1
        return k
    print(f"  . gate slack: {slack(inc, 85.0, 'min')} retrieval misses, "
          f"{slack(inc, 10.0, 'max')} false refusals, "
          f"{slack(ooc, 90.0, 'min')} out-of-corpus misses")

# evaluate.py
import py_compile
try:
    py_compile.compile("eval/evaluate.py", doraise=True)
    print("  . eval/evaluate.py compiles")
except Exception as e:
    fail.append(f"eval/evaluate.py does not compile: {e}")

if fail:
    print("\nVALIDATION FAILED:")
    for f in fail:
        print(f"  - {f}")
    sys.exit(1)
print("  . all checks passed")
RNV_VALIDATE_EOF

# --- 6. hand back ----------------------------------------------------------
say "Done. Nothing was run and nothing was committed."
cat <<'RNV_NEXT_EOF'
  Next, in order:

    1. Review the diff:
         git diff --stat
         git diff sources.json

    2. Dry-run a few cases before spending a full pass:
         python eval/evaluate.py --report-only --limit 5

    3. Full report (no gate), tagged so the artifact is self-identifying:
         python eval/evaluate.py --report-only --tag before-resume-fix

    4. Read eval/report.md. Check that res-mcp still shows retrieval ✅ with
       refused ⚠️; that pairing is the evidence, not a plain miss.

    5. Only then commit. Pushing sources.json or eval/** fires the eval
       workflow, which spends one Claude call per case.

  Backups of the replaced files are in .rnv-backup/ (add it to .gitignore).
RNV_NEXT_EOF
