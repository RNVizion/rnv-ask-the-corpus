import json
import os
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent   # scripts/ -> repo root
SOURCES_FILE = REPO_ROOT / "sources.json"
FEED_URL = os.environ.get("FEED_URL", "https://rnvizion.dev/feed.xml")


def slug_from_url(url):
    """Derive a stable id from a post URL: .../blog/sloth/ -> 'sloth'."""
    path = urlparse(url).path.rstrip("/")
    return path.rsplit("/", 1)[-1] or "post"


def feed_links(xml_text):
    """Every <item><link> in the RSS feed: the canonical list of live posts.
    RSS item/link sit in the empty namespace, so no prefix handling is needed."""
    root = ET.fromstring(xml_text)
    return [link.strip() for item in root.iter("item")
            if (link := item.findtext("link"))]


def norm(url):
    return url.rstrip("/")


def main():
    resp = requests.get(FEED_URL, timeout=20)
    resp.raise_for_status()
    links = feed_links(resp.text)

    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    sources = data.get("sources", [])
    known = {norm(s["url"]) for s in sources}

    added = []
    for url in links:
        if norm(url) in known:
            continue
        sid = slug_from_url(url)
        ids = {s["id"] for s in sources}
        n = 2
        while sid in ids:  # collision guard; URL-match above means this is rare
            sid = f"{slug_from_url(url)}-{n}"
            n += 1
        # Posts use the default article extraction, so no scope flag.
        sources.append({"id": sid, "url": url})
        known.add(norm(url))
        added.append(sid)
        print(f"ADDED {sid}: {url}")

    # Additive only: never removes bio/resume/aiii/home or any non-feed source.
    if added:
        data["sources"] = sources
        SOURCES_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"\n{len(added)} new post(s) registered from the feed.")
    else:
        print("no new posts in the feed.")


if __name__ == "__main__":
    main()
