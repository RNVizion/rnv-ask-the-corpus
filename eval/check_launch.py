#!/usr/bin/env python3
"""
check_launch.py: launch app.py as the Space does, and fail if the page does not
stay up or does not serve its fonts.

WHY THIS EXISTS
The eval imports app.py and never launches it, so anything that fails only in
launch() passes the eval and stops the Space after the deploy. On 2026-10-18 a
theme whose fonts were all plain strings did exactly that, in a local run: the
server answered, and then launch() raised while Gradio's analytics compared the
theme with its built-in ones. A check that stopped when the server answered
counted that as a start. So does anything that only asks whether the import
works. Two lines in app.py can also be lost with every other gate green, the one
that has Gradio serve the font folder and the one that names its files; this
fetches what the page actually serves.

WHAT IT DOES
  1. Runs `python app.py` from the repository root, with the environment it is
     given. eval.yml sets Gradio's analytics on and server rendering, as on the
     Space, and a placeholder API key: nothing here asks the page a question.
  2. Waits up to START_S for the page and its config to answer.
  3. Waits LINGER_S more, then fails if the process has exited or its output
     holds a traceback. launch() goes on working after the server answers, and
     the crash of 2026-10-18 came in that window.
  4. Checks the page was rendered where it was asked to be: a page rendered on
     the server carries the server renderer's data and its footer in the HTML,
     and one rendered in the browser carries no footer.
  5. Reads the stylesheet from the page's config and fetches every font file
     its @font-face rules name. Each must answer 200 and begin with the woff2
     signature, and there must be at least one.

Exits 0, or 1 with the reason and the end of the server's output. Stops the
server either way.

USAGE
  GRADIO_ANALYTICS_ENABLED=True GRADIO_SSR_MODE=true python eval/check_launch.py
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:7860"      # app.py launches on port 7860; see LAUNCH there
START_S = 300                       # the embedding model loads at import; on a cold runner it downloads
LINGER_S = 12                       # the 2026-10-18 crash came within a few seconds of the server answering
FONT_URL = re.compile(r'url\("(/gradio_api/file=[^"]+\.woff2)"\)')
WOFF2 = b"wOF2"


def get(path: str, timeout: float = 10) -> tuple[int, bytes]:
    with urllib.request.urlopen(BASE + urllib.parse.quote(path, safe="/=:?&"), timeout=timeout) as r:
        return r.status, r.read()


def main() -> int:
    ssr = os.environ.get("GRADIO_SSR_MODE", "").lower() == "true"      # the one value Gradio reads as on
    log = tempfile.NamedTemporaryFile("w+", prefix="check_launch_", suffix=".log", delete=False)
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=REPO_ROOT, stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True)
    failure = None
    try:
        failure = run(proc, ssr, Path(log.name))
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=15)
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
    log.flush()
    if failure:
        tail = Path(log.name).read_text(encoding="utf-8", errors="replace")[-4000:]
        print(f"FAIL: {failure}\n--- the end of the server's output ---\n{tail}", flush=True)
        return 1
    return 0


def run(proc: subprocess.Popen, ssr: bool, log_path: Path) -> str | None:
    t0 = time.time()
    while True:
        if proc.poll() is not None:
            return f"app.py exited with {proc.returncode} before the page answered"
        try:
            if get("/")[0] == 200 and get("/config")[0] == 200:
                break
        except Exception:
            pass
        if time.time() - t0 > START_S:
            return f"the page did not answer within {START_S}s"
        time.sleep(1)
    print(f"page answered after {time.time() - t0:.0f}s; waiting {LINGER_S}s for launch() to finish", flush=True)

    time.sleep(LINGER_S)
    if proc.poll() is not None:
        return f"app.py exited with {proc.returncode} after the page answered"
    output = log_path.read_text(encoding="utf-8", errors="replace")
    if "Traceback" in output:
        return "the server's output holds a traceback"
    print(f"still running {LINGER_S}s later, with no traceback", flush=True)

    html = get("/")[1].decode("utf-8", "replace")
    on_server = "__sveltekit" in html and "<footer" in html
    if on_server != ssr:
        return (f"asked for server rendering={ssr}, but the page was rendered "
                f"{'on the server' if on_server else 'in the browser'}")
    print(f"rendered {'on the server' if on_server else 'in the browser'}, as asked", flush=True)

    css = json.loads(get("/config")[1]).get("css") or ""
    urls = sorted(set(FONT_URL.findall(css)))
    if not urls:
        return "the page's stylesheet names no font file"
    bad = []
    for url in urls:
        try:
            status, body = get(url)
        except Exception as exc:
            bad.append(f"{url.rsplit('/', 1)[-1]}: {exc}")
            continue
        if status != 200 or not body.startswith(WOFF2):
            bad.append(f"{url.rsplit('/', 1)[-1]}: status {status}, starts {body[:4]!r}")
    if bad:
        return f"{len(bad)} of {len(urls)} font files did not load: " + "; ".join(bad)
    print(f"all {len(urls)} font files the stylesheet names were served as woff2", flush=True)
    print("ok: the page launched, stayed up and served its fonts", flush=True)
    return None


if __name__ == "__main__":
    sys.exit(main())
