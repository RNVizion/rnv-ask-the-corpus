#!/usr/bin/env bash
# One commit, three changes: re-ingest so the committed index matches
# sources.json, flip trap-margin now that its post is live, and stop
# eval/README.md printing a split that this very change moves.
#
#   bash flip-margin.sh                     # no keywords
#   bash flip-margin.sh translat margin     # with keywords, if you have them picked
#
# Fails closed at every step. Commits locally; does NOT push, because the push
# is the step that spends 60 Claude calls.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
TODAY="$(date +%F)"

echo "== 0. preflight =="
[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] || { echo "  not on main"; exit 1; }
git diff --quiet && git diff --cached --quiet || { echo "  working tree is dirty; commit or stash first"; exit 1; }
echo "  clean, on main"

echo "== 1. re-ingest =="
python scripts/ingest.py 2>&1 | tee /tmp/ingest.log
if grep -q "SKIP" /tmp/ingest.log; then
  echo "  a source was SKIPPED, so the index still will not match the manifest. Stopping."
  exit 1
fi
echo "  no sources skipped"

echo "== 2. flip trap-margin, de-figure eval/README.md =="
python3 - "$TODAY" "$@" <<'PYEOF'
import io, json, sys
today, kws = sys.argv[1], sys.argv[2:]

note = ("Was out_of_corpus until the post went live; flipped %s in the same commit "
        "as the re-ingest that indexed it." % today)
if not kws:
    note += (" keywords deliberately omitted: evaluate.py sets keyword_hit=None when a "
             "case has none, so the row drops out of the groundedness denominator "
             "rather than scoring as a miss. Add them when the post is read.")

# --- cases.jsonl: locate by parsed id, edit only the fields that change ---
p = "eval/cases.jsonl"
lines = io.open(p, encoding="utf-8").read().split("\n")
hits = [i for i, l in enumerate(lines) if l.strip() and json.loads(l).get("id") == "trap-margin"]
if len(hits) != 1:
    sys.exit("ABORT: found %d trap-margin lines" % len(hits))
i = hits[0]
line = lines[i]
if json.loads(line)["kind"] != "out_of_corpus":
    sys.exit("ABORT: trap-margin is not out_of_corpus")
line = line.replace('"kind": "out_of_corpus", ', '"kind": "in_corpus",     ', 1)
kwpart = ('"keywords": [%s], ' % ", ".join(json.dumps(k) for k in kws)) if kws else ""
line = (line[:line.index('"note":')]
        + '"expect_source": "the-margin-not-the-price", '
        + kwpart + '"note": ' + json.dumps(note) + "}")
json.loads(line)                      # fails loudly if the rebuild is malformed
lines[i] = line
io.open(p, "w", encoding="utf-8").write("\n".join(lines))

# --- eval/README.md: stop printing a split this change moves ---
p = "eval/README.md"
s = io.open(p, encoding="utf-8").read()
old = ('It currently sits at 38/22, and two flips are already armed: `trap-margin` waits on '
       '"The Margin, Not the Price," and `trap-compass` on the unpublished "Without a Compass."')
if s.count(old) != 1:
    sys.exit("ABORT eval/README.md: anchor matched %d times" % s.count(old))
new = ('`trap-compass` is the one flip still armed, waiting on the unpublished "Without a '
       'Compass"; `trap-margin` flipped on %s when its post went live. The split is not '
       'printed here, for the same reason it is not printed anywhere else:' % today)
io.open(p, "w", encoding="utf-8").write(s.replace(old, new))
print("  cases.jsonl and eval/README.md edited")
PYEOF

echo "== 3. verify the gated assertion locally, no Claude calls =="
python eval/check_index_coverage.py --strict

echo "== 4. commit =="
git add chroma eval/cases.jsonl eval/README.md
git status --short
git commit -m "corpus: index the-margin-not-the-price, flip trap-margin to in_corpus"
echo
echo "Committed, not pushed. The push is the 60-call step:"
echo "  git push origin main"
