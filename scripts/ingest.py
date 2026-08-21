import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from sentence_transformers import SentenceTransformer
import chromadb

REPO_ROOT = Path(__file__).resolve().parent.parent   # scripts/ -> repo root
SOURCES_FILE = REPO_ROOT / "sources.json"
CHUNK_WORDS, OVERLAP = 300, 50


class SkipSource(Exception):
    """Raised when a source can't be ingested (dead URL, not published, etc.)."""


def load_sources():
    """Read the live source list from sources.json (the '_pending' list is ignored)."""
    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    return data.get("sources", [])


def fetch_source(url, scope="article"):
    """Fetch and clean a source page. Returns (title, text).

    scope="article" (default): prefer <article>, then <main>, then <body>. Right
    for blog posts, where the surrounding site chrome is noise.
    scope="full": ingest the whole <body>. Use for pages whose content spans
    several top-level sections (the AIII page, landing pages) where an
    <article>/<main> slice would miss part of it.

    Raises SkipSource if the page is missing, errored, or has no readable content."""
    try:
        resp = requests.get(url, timeout=20)
    except requests.RequestException as e:
        raise SkipSource(f"request failed: {e}")
    if resp.status_code != 200:
        raise SkipSource(f"HTTP {resp.status_code}")
    soup = BeautifulSoup(resp.text, "html.parser")

    # Container + which chrome to strip depends on scope.
    if scope == "full":
        # The whole page: keep <header>, <footer>, and every section. Drop only
        # the repeated site menu and non-content tags, so "totality" doesn't mean
        # re-ingesting the same nav boilerplate that sits on every page.
        container = soup.body
        chrome = "nav, script, style"
    else:
        container = soup.find("article") or soup.find("main") or soup.body
        chrome = "nav, footer, script, style"
    if container is None:
        raise SkipSource("no readable content")

    for tag in container.select(chrome):
        tag.decompose()
    bio = container.find("div", class_="bio")  # author blurb on blog posts
    if bio:
        bio.decompose()

    t = soup.find("meta", property="og:title")
    title = t["content"] if t else url
    return title, re.sub(r"\s+", " ", container.get_text(" ", strip=True))


def chunk(text):
    words, step = text.split(), CHUNK_WORDS - OVERLAP
    for i in range(0, len(words), step):
        piece = words[i:i + CHUNK_WORDS]
        if piece:
            yield " ".join(piece)


def main():
    sources = load_sources()
    if not sources:
        sys.exit(f"no sources found in {SOURCES_FILE}")

    model = SentenceTransformer("all-MiniLM-L6-v2")
    client = chromadb.PersistentClient(path=str(REPO_ROOT / "chroma"))
    try:
        client.delete_collection("corpus")
    except Exception:
        pass
    col = client.get_or_create_collection("corpus")

    total = 0
    ingested, skipped = [], []
    for src in sources:
        sid, url = src["id"], src["url"]
        try:
            title, text = fetch_source(url, src.get("scope", "article"))
        except SkipSource as why:
            skipped.append((sid, str(why)))
            print(f"  SKIP {sid}: {why}  ({url})")
            continue
        chunks = list(chunk(text))
        col.add(
            ids=[f"{sid}-{i}" for i in range(len(chunks))],
            embeddings=model.encode(chunks).tolist(),
            documents=chunks,
            metadatas=[{"source": sid, "title": title} for _ in chunks],
        )
        total += len(chunks)
        ingested.append(sid)
        print(f"  ok   {sid}: {len(chunks)} chunks ({title})")

    print(f"\ndone — {total} chunks from {len(ingested)} sources → ./chroma")
    if skipped:
        print(f"skipped {len(skipped)}: " + ", ".join(f"{s} ({w})" for s, w in skipped))
        print("the corpus excludes these for now; deploy or fix them, then re-run.")


if __name__ == "__main__":
    main()
