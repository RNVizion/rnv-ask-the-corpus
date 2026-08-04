cd "$(git rev-parse --show-toplevel)" && \
git mv docs/eval-history/2026-07-28-baseline.md docs/eval-history/2026-06-29-baseline.md && \
git mv docs/eval-history/2026-07-28-baseline.json docs/eval-history/2026-06-29-baseline.json && \
F=docs/eval-history/2026-06-29-baseline.md && \
{ head -1 "$F"; printf '\n_40-case suite (22 in-corpus, 18 out-of-corpus). Predates the 58-case expansion committed 2026-07-28 in `9cecd28`. Dated 2026-06-29 from case coverage: the run references only the five sources present in the June index._\n'; tail -n +2 "$F"; } > "$F.tmp" && mv "$F.tmp" "$F" && \
grep -rn '2026-07-28-baseline' --exclude-dir=.git . || echo '-- no stale references --'
