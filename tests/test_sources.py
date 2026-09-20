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
invented. What they cannot see: whether a URL is live, whether the agent still
derives ids the same way, or whether a pending entry has since deployed. The
last of those has one cheap proxy, asserted below.

No API key, no network, no index.
"""
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
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


def test_pending_entries_are_not_already_live(data):
    """The pending list is a note to a human: pages drafted but not deployed. The
    ingester ignores it, so an entry that has since deployed sits there forever,
    which is what happened to the-job-was-never-coding (deployed 2026-07-15,
    removed from pending twelve days later).

    The cheap proxy: once a page is live, discover.py registers it from the feed,
    so a pending URL that also appears in `sources` means the move never happened.
    This cannot catch a pending entry whose URL never existed at all — the-margin
    sat there from a working slug that was never published, found by a reader in
    another chat rather than by this file."""
    pending = data.get("_pending_not_yet_deployed", [])
    live = {norm(s["url"]) for s in data["sources"]}
    stale = [p for p in pending if norm(p.get("url", "")) in live]
    assert not stale, f"deployed, but still listed as pending: {stale}"
    for entry in pending:
        assert entry.get("id") and entry.get("url"), entry
