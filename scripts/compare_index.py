#!/usr/bin/env python3
"""
compare_index.py: say whether two Chroma indexes hold the same thing.

WHY THIS EXISTS
ship-index.yml decides whether a rebuilt index needs committing, gating and
deploying. It used to decide by comparing bytes, and the bytes always differ:
ingest.py deletes chroma/ and creates the collection afresh, so every rebuild
carries a new collection id, new segment ids and new timestamps. The path that
should have skipped an unchanged index never fired. Four of the first six
committed rebuilds held the same text as the index they replaced, and each one
spent a full eval (about sixty Claude calls) and a Space redeploy anyway.

This compares what an index says instead of how it is stored.

WHERE THE CONTENT LIVES, MEASURED ON chromadb 1.5.9
Below 1,000 chunks every vector sits in the database's embeddings queue, and
Chroma serves it from there: read through Chroma, all 64 vectors of a674f00
equal the queue's bit for bit. The files in the segment directory carry
nothing Chroma reads at that size. At 64 chunks data_level0.bin is all zeros
and length.bin changes on every build. From 100 chunks data_level0.bin also
changes between two builds of the same input, and both builds answer the same
query identically. So those files are compared by name, never by bytes.

At 1,000 chunks Chroma writes its vector index to those files
(index_metadata.pickle appears) and empties the queue. This script then
refuses to judge, and the ship falls back to comparing bytes, with a warning
on every run until it learns to read them.

WHAT IS COMPARED
  format       every schema migration applied to the database
  collections  name, dimension, configuration and schema (as parsed JSON:
               Chroma does not write their keys in a stable order), metadata,
               and each segment's type and metadata
  chunks       every chunk id with every metadata value, which is where the
               chunk text lives (key "chroma:document")
  writes       every queued write, in order: id, operation, encoding, and
               metadata as parsed JSON
  vectors      every queued vector, to within TOLERANCE per component
  layout       the files in each directory of chroma/, by name, and the
               number of directories. An orphaned directory is a change.

WHY VECTORS GET A TOLERANCE
The embedding model is not bit-reproducible across CI runners. Of the four
rebuilds whose text matched their parent's, two carried vectors that differed
by up to 2.1e-07 per component and two matched exactly. A real change to a
chunk changes its text, which is compared exactly. A change to the embedding
stack moves vectors by orders of magnitude more than the tolerance.

WHAT IS LEFT OUT, AND WHY
  ids of collections, segments and databases   random on every rebuild
  directory names                              they are segment ids
  timestamps, sequence numbers, queue topics   bookkeeping; a topic embeds
                                               the collection id
  the bytes of the segment files               see above

USAGE
  python scripts/compare_index.py OLD NEW

Exits 0 when the two hold the same thing, 1 when they differ, naming what
differs, and 2 when it cannot say. A missing directory is not an error: it
differs from any real index. Deliberately biased toward "differ": anything it
does not understand counts as a difference or as "cannot say", so a mistake
costs one unneeded ship, never a skipped one. Standard library only. It opens
the database read-only and immutable, and refuses one with a -wal, -shm or
-journal file beside it, because a read-only open of that database writes a
-shm file into the directory, and one of the two directories is about to be
committed.
"""
from __future__ import annotations

import json
import sqlite3
import struct
import sys
from pathlib import Path

SQLITE = "chroma.sqlite3"
PERSISTED_HNSW = "index_metadata.pickle"
TOLERANCE = 1e-05


class CannotJudge(Exception):
    pass


def _canonical_json(text):
    """The same JSON with its keys sorted; anything unparseable passes as is."""
    if text is None:
        return None
    try:
        return json.dumps(json.loads(text), sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return text


def _decode(vector, encoding):
    if vector is not None and encoding == "FLOAT32" and len(vector) % 4 == 0:
        return struct.unpack(f"<{len(vector) // 4}f", vector)
    return vector


def read_index(root: Path) -> dict | None:
    """Everything this script compares, or None when there is no index at all."""
    if not root.exists():
        return None
    db = root / SQLITE
    if not db.is_file():
        raise CannotJudge(f"{root} has no {SQLITE}")
    sidecars = [p.name for p in root.iterdir() if p.name.startswith(SQLITE + "-")]
    if sidecars:
        raise CannotJudge(f"{root}: the database has unmerged sidecar files ({', '.join(sorted(sidecars))})")
    dirs = sorted(p for p in root.iterdir() if p.is_dir())
    if any((d / PERSISTED_HNSW).exists() for d in dirs):
        raise CannotJudge(f"{root}: Chroma has written its vector index to files "
                          f"({PERSISTED_HNSW}), so the queue no longer holds every vector")

    # immutable: no locks and no -shm, so reading cannot write a file into a
    # directory that is about to be committed. Safe only because sidecars were
    # refused above.
    con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        q = con.execute
        index = {}
        index["format"] = q("SELECT dir, version, hash FROM migrations "
                            "ORDER BY dir, version").fetchall()
        index["collections"] = (
            [(n, dim, _canonical_json(cfg), _canonical_json(schema)) for n, dim, cfg, schema in
             q("SELECT name, dimension, config_json_str, schema_str FROM collections ORDER BY name")]
            + q("SELECT c.name, m.key, m.str_value, m.int_value, m.float_value, m.bool_value "
                "FROM collection_metadata m JOIN collections c ON c.id = m.collection_id "
                "ORDER BY c.name, m.key").fetchall()
            + q("SELECT type, scope FROM segments ORDER BY type, scope").fetchall()
            + q("SELECT s.type, m.key, m.str_value, m.int_value, m.float_value, m.bool_value "
                "FROM segment_metadata m JOIN segments s ON s.id = m.segment_id "
                "ORDER BY s.type, m.key").fetchall()
        )
        ids = [r[0] for r in q("SELECT embedding_id FROM embeddings ORDER BY embedding_id")]
        index["chunks"] = [("id", i) for i in ids] + q(
            "SELECT e.embedding_id, m.key, m.string_value, m.int_value, m.float_value, m.bool_value "
            "FROM embedding_metadata m JOIN embeddings e ON e.id = m.id "
            "ORDER BY e.embedding_id, m.key").fetchall()
        queue = q("SELECT id, operation, encoding, vector, metadata "
                  "FROM embeddings_queue ORDER BY seq_id").fetchall()
    finally:
        con.close()

    missing = set(ids) - {row[0] for row in queue}
    if missing:
        raise CannotJudge(f"{root}: {len(missing)} chunk(s) have no vector in the queue")
    index["writes"] = [(i, op, enc, _canonical_json(meta)) for i, op, enc, _, meta in queue]
    index["vectors"] = [_decode(vec, enc) for _, _, enc, vec, _ in queue]
    index["layout"] = sorted(
        [("file", p.name) for p in root.iterdir() if p.is_file() and p.name != SQLITE]
        + [("dir", tuple(sorted(f.relative_to(d).as_posix() for f in d.rglob("*"))))
           for d in dirs])
    return index


def vector_gap(old: list, new: list) -> float | None:
    """The largest per-component difference, or None if the vectors cannot be matched."""
    if len(old) != len(new):
        return None
    gap = 0.0
    for a, b in zip(old, new):
        if isinstance(a, tuple) and isinstance(b, tuple) and len(a) == len(b):
            for x, y in zip(a, b):
                d = abs(x - y)
                if d != d:  # NaN on either side never passes
                    return float("nan")
                if d > gap:
                    gap = d
        elif a != b:
            return None
    return gap


def compare(old: dict | None, new: dict | None) -> tuple[bool, str]:
    if old is None or new is None:
        if old is None and new is None:
            return True, "no index on either side"
        return False, "index changed: " + ("no index on main" if old is None else "rebuilt index missing")

    differ = [k for k in ("format", "collections", "chunks", "writes", "layout") if old[k] != new[k]]
    gap = vector_gap(old["vectors"], new["vectors"])
    if gap is None or not gap <= TOLERANCE:
        differ.append("vectors" if gap is None else f"vectors (up to {gap:.2g})")
    if differ:
        return False, "index changed: " + ", ".join(differ)

    n = sum(1 for row in old["chunks"] if len(row) == 2)
    return True, (f"index unchanged: {n} chunks, same text and metadata; "
                  f"vectors within {gap:.2g} (tolerance {TOLERANCE:.0e})")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: compare_index.py OLD NEW", file=sys.stderr)
        return 2
    try:
        old, new = (read_index(Path(a)) for a in argv)
    except Exception as exc:  # unreadable means "cannot say", never "unchanged"
        print(f"cannot compare: {type(exc).__name__}: {exc}")
        return 2
    same, message = compare(old, new)
    print(message)
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
