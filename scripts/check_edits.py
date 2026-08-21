import hashlib
import json
import os
from pathlib import Path

# Reuse the ingester's own extraction so the hash reflects exactly what gets
# ingested (article -> main -> body, bio stripped), not nav chrome that drifts.
from ingest import load_sources, fetch_source, SkipSource

REPO_ROOT = Path(__file__).resolve().parent.parent   # scripts/ -> repo root
HASH_FILE = REPO_ROOT / ".source-hashes.json"


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_hashes():
    if HASH_FILE.exists():
        return json.loads(HASH_FILE.read_text(encoding="utf-8"))
    return {}


def write_output(changed, summary):
    """Expose results to the workflow via GITHUB_OUTPUT."""
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    with open(out, "a", encoding="utf-8") as f:
        f.write(f"changed={'true' if changed else 'false'}\n")
        f.write(f"summary={summary or 'none'}\n")


def main():
    old = load_hashes()
    new = {}
    changed = []

    for src in load_sources():
        sid, url = src["id"], src["url"]
        try:
            title, text = fetch_source(url, src.get("scope", "article"))
        except SkipSource as e:
            # A temporarily-down page shouldn't force a rebuild; keep its old hash.
            print(f"SKIP {sid}: {e}")
            if sid in old:
                new[sid] = old[sid]
            continue
        h = text_hash(f"{title}\n{text}")
        new[sid] = h
        if old.get(sid) != h:
            changed.append(sid)
            print(f"CHANGED {sid}")
        else:
            print(f"ok {sid}")

    # Sources removed from sources.json naturally drop here; the other workflow
    # (which fires on sources.json edits) already rebuilds for removals.
    HASH_FILE.write_text(json.dumps(new, indent=2) + "\n", encoding="utf-8")

    summary = ",".join(changed)
    print(f"\nchanged={bool(changed)}  ({summary or 'no edits'})")
    write_output(bool(changed), summary)


if __name__ == "__main__":
    main()
