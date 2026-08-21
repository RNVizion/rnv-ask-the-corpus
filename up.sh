#!/usr/bin/env bash
# Move ingest.py, discover.py, check_edits.py into scripts/ and update all 24
# references. Run from anywhere in the repo. Verifies itself; fails closed.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
PAT='(^|[^/[:alnum:]_-])(ingest|discover|check_edits)\.py'
INC="--include=*.py --include=*.yml --include=*.md"

echo "== 1. move =="
mkdir -p scripts
git mv ingest.py discover.py check_edits.py scripts/

echo "== 2. re-anchor =="
sed -i 's|^HERE = Path(__file__)\.resolve()\.parent$|REPO_ROOT = Path(__file__).resolve().parent.parent   # scripts/ -> repo root|' \
  scripts/ingest.py scripts/discover.py scripts/check_edits.py
sed -i 's|HERE / "|REPO_ROOT / "|g' scripts/ingest.py scripts/discover.py scripts/check_edits.py
sed -i 's|chromadb\.PersistentClient(path="chroma")|chromadb.PersistentClient(path=str(REPO_ROOT / "chroma"))|' scripts/ingest.py

echo "== 3. rewrite references =="
grep -rlE "$PAT" $INC . | grep -v '^\./chroma/' \
  | xargs sed -i -E "s@$PAT@\1scripts/\2.py@g"

echo "== 4. verify =="
python3 -m py_compile scripts/ingest.py scripts/discover.py scripts/check_edits.py && echo "  compile: ok"
R=$(cd scripts && python3 -c 'from pathlib import Path; print(Path("ingest.py").resolve().parent.parent)')
for f in sources.json .source-hashes.json; do
  [ -f "$R/$f" ] && echo "  anchor -> $f: ok" || { echo "  ANCHOR BROKEN: $f"; exit 1; }
done
if grep -rlE "$PAT" $INC . | grep -v '^\./chroma/' | grep -q .; then
  echo "  STALE REFERENCES REMAIN:"; grep -rnE "$PAT" $INC . | grep -v '^\./chroma/'; exit 1
fi
echo "  stale references: 0"
echo; git diff --stat HEAD | tail -14
