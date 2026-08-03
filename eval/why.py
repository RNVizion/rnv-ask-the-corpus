#!/usr/bin/env python3
"""
why.py — ask the index directly why a case scored the way it did.

Drop in at eval/why.py and run from the repo root, the same place app.py expects
to find ./chroma.

WHY THIS EXISTS
results.json records `retrieved` as source ids, because that is what the retrieval
metric scores: chunk ids are {source_id}-{n} and the scorer rsplits on the last
hyphen. Useful for the gate, lossy for a post-mortem. When a case fails you want
the chunk, the distance, and the text; the artifact has thrown all three away by
the time you read it. This reads the index straight, so a failing case can be
taken apart without re-running 58 Claude calls to watch one of them.

It reads the index exactly the way ingest.py wrote it: the same model, the same
collection, and query_embeddings rather than query_texts. That last part matters.
ingest.py supplies vectors explicitly from sentence-transformers, while Chroma
attaches its own default embedding function to the collection; querying by text
would embed the question with a different implementation than the one that built
the index, and a diagnostic that reads the index differently from the writer is
measuring itself.

USAGE
  python eval/why.py "What does Christian say made the refusal the design goal?"
  python eval/why.py "..." -k 10                 # look past the top-k cutoff
  python eval/why.py --contains "design goal"    # which chunks hold a string
  python eval/why.py "..." --contains "design goal" --full

  -k         how many results to rank (default 8; the app serves 5, so the extra
             rows show what just missed and by how much)
  --contains locate a phrase in the corpus; combine with a question to see
             whether the chunk that holds it is anywhere near the top
  --full     print whole chunks instead of a preview
  --source   restrict the ranking to one source id

Reads only. It never writes to the index.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import chromadb
    from sentence_transformers import SentenceTransformer
except ImportError as e:                                    # pragma: no cover
    sys.exit(f"missing dependency: {e}. This runs in the corpus repo's environment.")

MODEL = "all-MiniLM-L6-v2"      # must match ingest.py
COLLECTION = "corpus"           # must match ingest.py
CHROMA_PATH = "chroma"          # relative, like app.py


def open_collection(path: str):
    client = chromadb.PersistentClient(path=path)
    names = [c.name for c in client.list_collections()]
    if COLLECTION not in names:
        sys.exit(f"no '{COLLECTION}' collection at ./{path}; found {names or 'nothing'}. "
                 f"Run from the repo root, or run ingest.py first.")
    return client.get_collection(COLLECTION)


def preview(text: str, full: bool, width: int = 220) -> str:
    text = " ".join(text.split())
    if full or len(text) <= width:
        return text
    return text[:width] + "…"


def source_of(chunk_id: str) -> str:
    """Chunk ids are {source_id}-{n}; the scorer rsplits on the last hyphen and
    so does this, or a source id containing a hyphen gets truncated."""
    return chunk_id.rsplit("-", 1)[0]


def show_inventory(col):
    got = col.get(include=["documents"])
    by_source: dict[str, list[int]] = {}
    for cid, doc in zip(got["ids"], got["documents"]):
        by_source.setdefault(source_of(cid), []).append(len(doc.split()))
    total = sum(len(v) for v in by_source.values())
    print(f"\nINDEX  {total} chunks across {len(by_source)} sources")
    print("-" * 70)
    for sid in sorted(by_source):
        sizes = by_source[sid]
        print(f"  {sid:<28} {len(sizes):>3} chunks   "
              f"{min(sizes):>3}-{max(sizes):>3} words   avg {sum(sizes)//len(sizes):>3}")
    return got


def find_containing(got, needle: str, full: bool):
    hits = [(cid, doc) for cid, doc in zip(got["ids"], got["documents"])
            if needle.lower() in doc.lower()]
    print(f"\nCONTAINS  \"{needle}\"  —  {len(hits)} chunk(s)")
    print("-" * 70)
    if not hits:
        print("  nothing. The phrase is not in the index, which is a finding in itself:\n"
              "  either the page changed since the last ingest, or the chunk boundary\n"
              "  split the phrase across two chunks.")
    for cid, doc in hits:
        print(f"  {cid}   ({len(doc.split())} words)")
        print(f"    {preview(doc, full)}\n")
    return {cid for cid, _ in hits}


def rank(col, question: str, k: int, source: str | None, marked: set[str], full: bool):
    model = SentenceTransformer(MODEL)
    vec = model.encode([question]).tolist()
    kwargs = {"query_embeddings": vec, "n_results": k}
    if source:
        kwargs["where"] = {"source": source}
    res = col.query(**kwargs)
    ids = res["ids"][0]
    docs = res["documents"][0]
    dists = res["distances"][0]

    print(f"\nRANKED  \"{question}\"")
    print(f"  top {k}; the app serves 5, so rows 6+ are what just missed")
    print("-" * 70)
    seen_sources: list[str] = []
    for pos, (cid, doc, dist) in enumerate(zip(ids, docs, dists), start=1):
        sid = source_of(cid)
        seen_sources.append(sid)
        cut = "  " if pos <= 5 else "· "
        flag = "  <-- holds the phrase" if cid in marked else ""
        print(f"{cut}{pos:>2}. {dist:.4f}  {cid:<24} ({len(doc.split())} words){flag}")
        print(f"       {preview(doc, full)}")
    print("-" * 70)
    print(f"  sources in top 5: {', '.join(dict.fromkeys(seen_sources[:5]))}")

    if marked:
        placed = [p for p, cid in enumerate(ids, start=1) if cid in marked]
        if not placed:
            print(f"  the chunk holding the phrase did not rank in the top {k} at all")
        elif min(placed) > 5:
            print(f"  the chunk holding the phrase ranked {min(placed)}; it missed the "
                  f"top-5 window the app retrieves from")
        else:
            print(f"  the chunk holding the phrase ranked {min(placed)}, so it WAS in "
                  f"front of the model. A refusal here is the prompt or the question's "
                  f"shape, not retrieval")

    spread = len(set(seen_sources[:5]))
    if spread >= 5:
        print("  note: five sources for five slots. A flat spread on a question whose "
              "wording appears in the corpus is the signature of a query vector that "
              "matches nothing strongly; check that app.py embeds queries the same way "
              "ingest.py embedded chunks")


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect retrieval for one question.")
    ap.add_argument("question", nargs="?", help="the question to rank")
    ap.add_argument("-k", type=int, default=8, help="results to rank (default 8)")
    ap.add_argument("--contains", help="locate a phrase in the index")
    ap.add_argument("--source", help="restrict the ranking to one source id")
    ap.add_argument("--full", action="store_true", help="print whole chunks")
    ap.add_argument("--path", default=CHROMA_PATH, help="path to the chroma dir")
    args = ap.parse_args()

    if not args.question and not args.contains:
        ap.error("give a question, --contains, or both")

    if not Path(args.path).exists():
        sys.exit(f"no ./{args.path} here. Run from the repo root.")

    col = open_collection(args.path)
    got = show_inventory(col)

    marked: set[str] = set()
    if args.contains:
        marked = find_containing(got, args.contains, args.full)

    if args.question:
        rank(col, args.question, args.k, args.source, marked, args.full)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
