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

VERIFY THE INDEX, NOT THE PAGE
`ingest.py` fetches live URLs, so a source's git history describes what was
published, never what was ingested; a page commit and an index commit on the same
day are two different documents. `--at` exists because that rule had no tool. It
reads the committed `chroma/` as of any commit, which is what settled the res-mcp
question: four resume chunks, 1,043 words, zero mentions of the thing the live
page had been carrying for four days.

The index is extracted with `git archive` rather than checked out with
`git worktree`. A worktree writes state under .git/ and has to be pruned if the
process dies; an archive extraction leaves nothing behind to strand.

USAGE
  python eval/why.py "What does Christian say made the refusal the design goal?"
  python eval/why.py "..." -k 10                      # look past the top-k cutoff
  python eval/why.py --contains "design goal"         # which chunks hold a string
  python eval/why.py --at c037b4f --dump resume --find color-mcp
  python eval/why.py --at c037b4f "..."               # rank against a past index

  -k         how many results to rank (default 8; the app serves 5, so the extra
             rows show what just missed and by how much)
  --contains locate a phrase across the whole index (--find is an alias)
  --dump     list every chunk for a source prefix, with word counts, and mark the
             ones holding --contains
  --at       read the committed chroma/ as of a commit instead of the working tree
  --source   restrict the ranking to one source id
  --full     print whole chunks instead of a preview

Reads only. It never writes to the working-tree index and never mutates the repo.
"""
from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

try:
    import chromadb
    from sentence_transformers import SentenceTransformer
except ImportError as e:                                    # pragma: no cover
    sys.exit(f"missing dependency: {e}. This runs in the corpus repo's environment.")

MODEL = "all-MiniLM-L6-v2"      # must match ingest.py
COLLECTION = "corpus"           # must match ingest.py
CHROMA_PATH = "chroma"          # relative, like app.py


# --------------------------------------------------------------------------
# reading a historical index
# --------------------------------------------------------------------------
def extract_index_at(commit: str, dest: Path) -> Path:
    """Extract chroma/ as of `commit` into dest. Returns the extracted path.

    Fails loudly and usefully. The two failures that actually happen are a commit
    the local clone has never fetched, and a commit predating the committed index;
    both look like generic git noise unless they are named."""
    probe = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        capture_output=True, text=True,
    )
    if probe.returncode != 0:
        sys.exit(
            f"commit {commit} is not in this clone.\n"
            f"  A Codespace often has a shallow or partial history; run:\n"
            f"      git fetch --all --tags\n"
            f"  then try again."
        )

    archive = subprocess.run(
        ["git", "archive", "--format=tar", commit, CHROMA_PATH],
        capture_output=True,
    )
    if archive.returncode != 0:
        err = archive.stderr.decode("utf-8", "replace").strip()
        if "did not match any files" in err:
            sys.exit(
                f"commit {commit} has no {CHROMA_PATH}/ directory.\n"
                f"  The index was not committed at that point in history."
            )
        sys.exit(f"git archive failed: {err}")

    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tf:
        members = [m for m in tf.getmembers()
                   if not m.name.startswith("/") and ".." not in m.name]
        tf.extractall(dest, members=members)

    out = dest / CHROMA_PATH
    if not out.exists():
        sys.exit(f"extraction produced no {CHROMA_PATH}/ for {commit}")
    print(f"\nREADING the index as committed at {commit}")
    print("  extracted to a temporary copy; the working tree is untouched.")
    print("  note: an older index may be schema-migrated on open by the installed")
    print("  chromadb. That happens to the temporary copy only.")
    return out


# --------------------------------------------------------------------------
def open_collection(path: Path):
    client = chromadb.PersistentClient(path=str(path))
    names = [c.name for c in client.list_collections()]
    if COLLECTION not in names:
        sys.exit(f"no '{COLLECTION}' collection at {path}; found {names or 'nothing'}. "
                 f"Run from the repo root, or run ingest.py first.")
    return client.get_collection(COLLECTION)


def preview(text: str, full: bool, width: int = 220) -> str:
    text = " ".join(text.split())
    if full or len(text) <= width:
        return text
    return text[:width] + "\u2026"


def source_of(chunk_id: str) -> str:
    """Chunk ids are {source_id}-{n}; the scorer rsplits on the last hyphen and
    so does this, or a source id containing a hyphen gets truncated."""
    return chunk_id.rsplit("-", 1)[0]


def chunk_index(chunk_id: str) -> int:
    tail = chunk_id.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else -1


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


def find_containing(got, needle: str, full: bool, quiet: bool = False):
    hits = [(cid, doc) for cid, doc in zip(got["ids"], got["documents"])
            if needle.lower() in doc.lower()]
    if not quiet:
        print(f"\nCONTAINS  \"{needle}\"  \u2014  {len(hits)} chunk(s)")
        print("-" * 70)
        if not hits:
            print("  nothing. The phrase is not in this index, which is a finding in\n"
                  "  itself: either the page changed after this index was built, or a\n"
                  "  chunk boundary split the phrase in two.")
        for cid, doc in hits:
            print(f"  {cid}   ({len(doc.split())} words)")
            print(f"    {preview(doc, full)}\n")
    return {cid for cid, _ in hits}


def dump_source(got, prefix: str, needle: str | None, marked: set[str], full: bool):
    """Every chunk for a source, in order. This is the query that answers 'what
    did the index actually hold', which is a different question from 'what did
    the page say'."""
    rows = [(cid, doc) for cid, doc in zip(got["ids"], got["documents"])
            if source_of(cid) == prefix or cid.startswith(prefix + "-")]
    rows.sort(key=lambda r: chunk_index(r[0]))

    print(f"\nDUMP  source \"{prefix}\"  \u2014  {len(rows)} chunk(s)")
    print("-" * 70)
    if not rows:
        sources = sorted({source_of(c) for c in got["ids"]})
        print(f"  no chunks. Sources in this index: {', '.join(sources)}")
        return
    words = 0
    for cid, doc in rows:
        n = len(doc.split())
        words += n
        flag = ""
        if needle:
            flag = "  HOLDS IT" if cid in marked else "  no"
        print(f"  {cid:<24} {n:>4} words{flag}")
        if full:
            print(f"      {preview(doc, True)}\n")
    print("-" * 70)
    hits = len([c for c, _ in rows if c in marked]) if needle else None
    summary = f"  {len(rows)} chunks, {words:,} words"
    if needle:
        summary += f", {hits} containing \"{needle}\""
    print(summary)
    if needle and hits == 0:
        print(f"  This index does not contain \"{needle}\" for this source at all.\n"
              f"  Check the page's own history before concluding anything about the\n"
              f"  page: what was published and what was ingested are two different\n"
              f"  documents, and only one of them is what the bot answered from.")


def rank(col, question: str, k: int, source: str | None, marked: set[str], full: bool):
    model = SentenceTransformer(MODEL)
    vec = model.encode([question]).tolist()
    kwargs = {"query_embeddings": vec, "n_results": k}
    if source:
        kwargs["where"] = {"source": source}
    res = col.query(**kwargs)
    ids, docs, dists = res["ids"][0], res["documents"][0], res["distances"][0]

    print(f"\nRANKED  \"{question}\"")
    print(f"  top {k}; the app serves 5, so rows 6+ are what just missed")
    print("-" * 70)
    seen: list[str] = []
    for pos, (cid, doc, dist) in enumerate(zip(ids, docs, dists), start=1):
        seen.append(source_of(cid))
        cut = "  " if pos <= 5 else "\u00b7 "
        flag = "  <-- holds the phrase" if cid in marked else ""
        print(f"{cut}{pos:>2}. {dist:.4f}  {cid:<24} ({len(doc.split())} words){flag}")
        print(f"       {preview(doc, full)}")
    print("-" * 70)
    print(f"  sources in top 5: {', '.join(dict.fromkeys(seen[:5]))}")

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

    # Separation, not source spread. An earlier version of this note counted
    # distinct sources in the top 5 and called five-for-five a weak query vector;
    # that misread a run where rank 1 led rank 2 by 0.25 while everything below
    # was packed inside 0.10. One strong match above a noise floor is the opposite
    # of a flat query. Measure the gap instead of counting labels.
    if len(dists) >= 3:
        lead = dists[1] - dists[0]
        floor = dists[-1] - dists[1]
        if floor > 0 and lead <= floor / 4:
            print(f"  note: rank 1 leads rank 2 by only {lead:.4f} while ranks 2-{len(dists)} "
                  f"span {floor:.4f}. Nothing matches strongly, so the window is being "
                  f"filled by whatever was nearest rather than by anything on topic")
        elif lead >= floor:
            print(f"  note: rank 1 leads rank 2 by {lead:.4f}, more than the {floor:.4f} "
                  f"spanning the rest. One clear match above a noise floor")


def _normalise_argv(argv):
    """Repair flags mangled by smart punctuation before argparse sees them.

    iOS rewrites "--" to an en or em dash as you type, so a correct command comes
    back as "unrecognized arguments: —dump". This is a phone-first workflow and
    the keyboard is not going to stop; fighting it every invocation is worse than
    absorbing it here. Only leading dashes are touched, so a question containing
    a dash is left exactly as written."""
    out, fixed = [], False
    for a in argv:
        if a[:1] in ("\u2013", "\u2014"):      # en dash, em dash
            a = "--" + a[1:]
            fixed = True
        out.append(a)
    if fixed:
        print("note: smart-punctuation dashes in the command were read as '--'")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect retrieval against a corpus index.")
    ap.add_argument("question", nargs="?", help="the question to rank")
    ap.add_argument("-k", type=int, default=8, help="results to rank (default 8)")
    ap.add_argument("--contains", "--find", dest="contains",
                    help="locate a phrase in the index")
    ap.add_argument("--dump", help="list every chunk for this source id")
    ap.add_argument("--at", help="read the committed chroma/ as of this commit")
    ap.add_argument("--source", help="restrict the ranking to one source id")
    ap.add_argument("--full", action="store_true", help="print whole chunks")
    ap.add_argument("--path", default=CHROMA_PATH, help="path to the chroma dir")
    args = ap.parse_args(_normalise_argv(sys.argv[1:]))

    if not (args.question or args.contains or args.dump):
        ap.error("give a question, --contains, --dump, or a combination")

    tmp = None
    try:
        if args.at:
            tmp = tempfile.mkdtemp(prefix="why-idx-")
            index_path = extract_index_at(args.at, Path(tmp))
        else:
            index_path = Path(args.path)
            if not index_path.exists():
                sys.exit(f"no {index_path} here. Run from the repo root, "
                         f"or pass --at <commit> to read a committed index.")

        col = open_collection(index_path)
        got = show_inventory(col)

        marked: set[str] = set()
        if args.contains:
            marked = find_containing(got, args.contains, args.full,
                                     quiet=bool(args.dump))

        if args.dump:
            dump_source(got, args.dump, args.contains, marked, args.full)

        if args.question:
            rank(col, args.question, args.k, args.source, marked, args.full)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
