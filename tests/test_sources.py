"""
test_sources.py: the shape of sources.json, asserted on this side of a two-writer file.

WHY THIS EXISTS
Two programs in two repositories write entries into `sources.json`, and neither
reads the other. `scripts/discover.py` registers posts it finds in the feed; the
publishing agent's `update_corpus` registers a post it has just deployed. They
write the same `{"id": ..., "url": ...}` shape today because the code happens to
agree, which is the same arrangement that held between this repo's pinned
requirements and the Space's unpinned ones for three months, and ended with the
demo answering nothing for weeks.

So each side pins its own half rather than keeping a hand-copied duplicate of the
other's contract (a second copy of a contract goes stale; see the practices doc).
The agent's tests hold its writer to this shape. These hold ours: a change here
fails loudly, in the same run, instead of quietly disagreeing with a program in
another repository.

These assertions are read off the current file and off `discover.py`, not
invented. What they cannot see: whether a URL is live, or whether the agent
still derives ids the same way.

Every assertion here gates a commit. The file runs right after discovery
writes, before that write is committed; at the head of every ship, before an
index is built; and in the eval's cheap band. So it holds only checks on what a
writer writes. A reminder to a human does not belong here: a check on the old
pending list sat in this file until 2026-09-29, and it failed precisely when
discovery had correctly registered a live post, so in front of a commit it
would have held that post back until someone edited a field nothing read. The
list was retired rather than the check moved.

No API key, no network, no index.
"""
import json
import re
from pathlib import Path

import pytest

def _repo_root():
    """Find the repo root by locating sources.json, not by counting directories.

    This file was written into eval/ and moved to tests/ the next day. A hardcoded
    parent.parent survived that move by luck, both being one level down, and would
    break at any other depth — in a file whose entire job is to fail loudly about
    a drifting artifact. Locate the artifact instead of assuming where it sits.
    """
    here = Path(__file__).resolve()
    for d in here.parents:
        if (d / "sources.json").is_file():
            return d
    raise RuntimeError(f"sources.json not found in any parent of {here}")


REPO_ROOT = _repo_root()
SOURCES_FILE = REPO_ROOT / "sources.json"

SITE = "https://rnvizion.dev/"
# discover.py derives an id from the URL's last path segment and, on a collision,
# appends -2, -3. Both forms are legal; anything else is a hand-written id.
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
KNOWN_SCOPES = {"full"}          # absent means the default article extraction


@pytest.fixture(scope="module")
def data():
    return json.loads(SOURCES_FILE.read_text(encoding="utf-8"))


def norm(url):
    """discover.py's own normalisation, so 'already registered?' means the same
    thing on both sides of the file."""
    return url.rstrip("/")


def test_entries_carry_an_id_and_a_url(data):
    sources = data.get("sources")
    assert isinstance(sources, list) and sources, "sources must be a non-empty list"
    for entry in sources:
        assert isinstance(entry, dict), entry
        assert set(entry) <= {"id", "url", "scope"}, f"unknown key in {entry}"
        assert entry.get("id") and entry.get("url"), entry


def test_ids_are_unique_and_slug_shaped(data):
    ids = [s["id"] for s in data["sources"]]
    assert len(ids) == len(set(ids)), "duplicate source id"
    bad = [i for i in ids if not SLUG.match(i)]
    assert not bad, f"ids must be lowercase slugs: {bad}"


def test_urls_are_unique_and_on_the_site(data):
    urls = [norm(s["url"]) for s in data["sources"]]
    assert len(urls) == len(set(urls)), "the same page is registered twice"
    off_site = [u for u in urls if not u.startswith(norm(SITE))]
    assert not off_site, f"sources must be published pages on the site: {off_site}"


def test_post_ids_match_their_slug(data):
    """A post's id is its URL slug, optionally with discover.py's -N collision
    suffix. Both writers derive it this way, so a mismatch means one of them
    changed and the other was not told."""
    wrong = []
    for s in data["sources"]:
        path = norm(s["url"]).split(norm(SITE), 1)[-1].lstrip("/")
        if not path.startswith("blog/"):
            continue                      # home, bio, resume, aiii carry hand-set ids
        slug = path.rsplit("/", 1)[-1]
        if s["id"] != slug and not re.fullmatch(rf"{re.escape(slug)}-\d+", s["id"]):
            wrong.append((s["id"], slug))
    assert not wrong, f"post id does not match its slug: {wrong}"


def test_scope_flags_are_known(data):
    unknown = [(s["id"], s["scope"]) for s in data["sources"]
               if "scope" in s and s["scope"] not in KNOWN_SCOPES]
    assert not unknown, f"unknown scope: {unknown}; ingest.py implements {KNOWN_SCOPES}"
