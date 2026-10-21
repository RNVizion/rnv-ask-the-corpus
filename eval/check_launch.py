#!/usr/bin/env python3
"""
check_launch.py: launch app.py as the Space does, and fail if the page does not
stay up, does not serve its fonts, or carries a Space id in its config.

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

The page carries no Space id in its config, since 2026-10-20: on a Space, Gradio
puts the id there, and a page opened at its own .hf.space address then draws
Hugging Face's header and asks Google Fonts for the header's faces. app.py
clears the id, and checks at import that Gradio's config reads the attribute it
clears. That check cannot see what launch() does afterwards, so this launches
the page with a Space's environment and reads the config it serves.

WHAT IT DOES
  1. Runs `python app.py` from the repository root, with the environment it is
     given plus a Space's: SYSTEM=spaces and a SPACE_ID, the two values Gradio
     reads to decide it is on a Space. eval.yml sets Gradio's analytics on and
     server rendering, as on the Space, and a placeholder API key: nothing here
     asks the page a question. Before launching, it checks that a new
     gr.Blocks() in the installed Gradio takes those two values as its Space id,
     so the check cannot pass because Gradio stopped noticing the environment.
  2. Waits up to START_S for the page and its config to answer.
  3. Waits LINGER_S more, then fails if the process has exited or its output
     holds a traceback. launch() goes on working after the server answers, and
     the crash of 2026-10-18 came in that window. One traceback is expected and
     allowed, by its exact last line: on a Space, Gradio starts a hot-reload
     thread that needs Hugging Face's `spaces` package, which the runner does
     not have. The thread stops; the server does not. Any other line that
     mentions a traceback fails, an exception group's included.
  4. Checks the page was rendered where it was asked to be: a page rendered on
     the server carries the server renderer's data and its footer in the HTML,
     and one rendered in the browser carries no footer.
  5. Reads the stylesheet from the page's config and fetches every font file
     its @font-face rules name. Each must answer 200 and begin with the woff2
     signature, and there must be at least one.
  6. Fails if the config the page serves carries a Space id.

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
PROBE_SPACE_ID = "check-launch/probe"   # any id does: the check is whether it reaches /config
SPACE_ENV = {"SYSTEM": "spaces", "SPACE_ID": PROBE_SPACE_ID}
# The one traceback a Space's environment brings on a runner, by its last line.
SPACES_RELOADER = "RuntimeError: `spaces` package is required to run hot-reloading in Spaces"


def get(path: str, timeout: float = 10) -> tuple[int, bytes]:
    with urllib.request.urlopen(BASE + urllib.parse.quote(path, safe="/=:?&"), timeout=timeout) as r:
        return r.status, r.read()


def unexpected_tracebacks(output: str) -> list[str]:
    """Every traceback in the output that is not the allowed one.

    Any line that mentions a traceback counts. Only a plain header at the start of
    a line, whose exception line is exactly SPACES_RELOADER, is allowed; anything
    else, an exception group's indented header included, is returned.
    """
    lines = output.splitlines()
    found = []
    for i, line in enumerate(lines):
        if "Traceback" not in line:
            continue
        if not line.startswith("Traceback (most recent call last):"):
            found.append(line.strip())
            continue
        last = next((ln for ln in lines[i + 1:] if ln and not ln[0].isspace()), "(no exception line)")
        if last != SPACES_RELOADER:
            found.append(last)
    return found


def main() -> int:
    ssr = os.environ.get("GRADIO_SSR_MODE", "").lower() == "true"      # the one value Gradio reads as on
    env = {**os.environ, **SPACE_ENV}
    try:
        seen = subprocess.run(
            [sys.executable, "-c", "import gradio as gr; print(gr.Blocks().space_id)"],
            env=env, capture_output=True, text=True, timeout=120).stdout.strip()
    except Exception as exc:
        seen = f"{type(exc).__name__}: {exc}"
    if seen != PROBE_SPACE_ID:
        print(f"FAIL: given SYSTEM=spaces and SPACE_ID={PROBE_SPACE_ID}, a new gr.Blocks() "
              f"has space_id {seen!r}, so this cannot launch the page as on a Space. See SPACE_ENV.",
              flush=True)
        return 1
    print(f"Gradio reads the Space environment given: {seen}", flush=True)
    log = tempfile.NamedTemporaryFile("w+", prefix="check_launch_", suffix=".log", delete=False)
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=REPO_ROOT, stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True, env=env)
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
    unexpected = unexpected_tracebacks(output)
    if unexpected:
        return "the server's output holds a traceback: " + "; ".join(unexpected)
    allowed = output.count(SPACES_RELOADER)
    print(f"still running {LINGER_S}s later, with no traceback"
          + (f" but the allowed one ({SPACES_RELOADER.split(': ', 1)[1]})" if allowed else ""), flush=True)

    html = get("/")[1].decode("utf-8", "replace")
    on_server = "__sveltekit" in html and "<footer" in html
    if on_server != ssr:
        return (f"asked for server rendering={ssr}, but the page was rendered "
                f"{'on the server' if on_server else 'in the browser'}")
    print(f"rendered {'on the server' if on_server else 'in the browser'}, as asked", flush=True)

    config = json.loads(get("/config")[1])
    css = config.get("css") or ""
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

    if config.get("space_id") is not None:
        return (f"the page's config carries the Space id {config.get('space_id')!r}, so opened at "
                f"its own .hf.space address it draws Hugging Face's header and asks Google Fonts "
                f"for its faces. See _without_space_header in app.py.")
    print("the page's config carries no Space id", flush=True)
    print("ok: the page launched, stayed up, served its fonts and carries no Space id", flush=True)
    return None


if __name__ == "__main__":
    sys.exit(main())
