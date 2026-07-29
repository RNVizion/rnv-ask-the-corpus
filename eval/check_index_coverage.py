"""
check_index_coverage.py — does the committed index contain every source the eval
cases actually reference?

The invariant is NOT "the index is current." An index a post or two behind is
harmless for regression detection. The fatal condition is narrower: a case that
expects a source the index does not hold. That case cannot pass, the run reads as
catastrophe, and nothing is actually broken.

On 2026-07-27 the committed index sat four sources behind sources.json. The eval
reported 73.0% retrieval and 24.3% false refusal on a completely healthy bot,
because twelve cases pointed at content that was not in the index to find. This
check catches that in about a second, before the eval spends one Claude call per
case learning it the expensive way.

    python eval/check_index_coverage.py          # exit 1 if a referenced source is missing
    python eval/check_index_coverage.py --strict # also fail on any drift from sources.json

Run from the repo root; app.py and the index use relative paths.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CASES = REPO_ROOT / "eval" / "cases.jsonl"
SOURCES = REPO_ROOT / "sources.json"
CHROMA = REPO_ROOT / "chroma"
COLLECTION = "corpus"


def indexed_source_ids():
    """Source ids present in the committed index. Chunk ids are '{source_id}-{n}',
    so rsplit on the last hyphen recovers ids that contain hyphens themselves."""
    try:
        import chromadb
    except ImportError:
        sys.exit("chromadb is not installed; run pip install -r requirements.txt")

    if not CHROMA.exists():
        sys.exit(f"no index at {CHROMA} — run: python ingest.py")

    client = chromadb.PersistentClient(path=str(CHROMA))
    try:
        col = client.get_collection(COLLECTION)
    except Exception as exc:
        sys.exit(f"collection '{COLLECTION}' not readable at {CHROMA}: {exc}")

    try:
        ids = col.get(include=[])["ids"]
    except Exception:
        ids = col.get()["ids"]          # older chromadb ignores include=[]
    return {cid.rsplit("-", 1)[0] for cid in ids}, len(ids)


def referenced_source_ids():
    """Source ids the in-corpus cases expect to retrieve."""
    want = set()
    for line in CASES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        case = json.loads(line)
        if case["kind"] != "in_corpus":
            continue
        exp = case.get("expect_source")
        if exp is None:
            continue
        want |= set(exp if isinstance(exp, list) else [exp])
    return want


def declared_source_ids():
    data = json.loads(SOURCES.read_text(encoding="utf-8"))
    return {s["id"] for s in data.get("sources", [])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="also fail when the index drifts from sources.json at all")
    args = ap.parse_args()

    indexed, chunk_count = indexed_source_ids()
    referenced = referenced_source_ids()
    declared = declared_source_ids()

    print(f"index:      {len(indexed)} sources, {chunk_count} chunks")
    print(f"cases:      {len(referenced)} sources referenced")
    print(f"sources.json: {len(declared)} sources declared")

    # informational: drift is normal and harmless until a case depends on it
    behind = sorted(declared - indexed)
    orphaned = sorted(indexed - declared)
    if behind:
        print(f"\nnote: declared but not indexed (harmless until a case needs one): {behind}")
    if orphaned:
        print(f"note: indexed but no longer declared (stale chunks): {orphaned}")

    # ungated content: live in the index, but nothing is watching it
    unwatched = sorted(indexed & declared - referenced)
    if unwatched:
        print(f"note: indexed with no eval case covering it: {unwatched}")

    # the one fatal condition
    missing = sorted(referenced - indexed)
    if missing:
        print(
            f"\nFAIL: the committed index is missing sources the cases expect: {missing}\n"
            f"      Those cases cannot pass and the run will read as a broken bot.\n"
            f"      Fix: python ingest.py && git add chroma/ && commit it with this change."
        )
        sys.exit(1)

    if args.strict and (behind or orphaned):
        print("\nFAIL (--strict): index does not match sources.json exactly.")
        sys.exit(1)

    print(f"\nOK: all {len(referenced)} referenced sources are present in the index.")


if __name__ == "__main__":
    main()
