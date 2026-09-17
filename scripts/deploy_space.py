#!/usr/bin/env python3
"""
deploy_space.py: ship the repo's copy of the demo to the Hugging Face Space, then
prove the live app answers.

WHY THIS EXISTS
The Space is a second copy of this repo, and for three months it ran a different
environment from the one CI tests. Its requirements.txt was uploaded once, unpinned,
on 2026-06-20, and every index upload afterwards rebuilt the Space with whatever
PyPI served that day. Anthropic SDK 1.0.0 (2026-08-20) removed `temperature` from
messages.create(), app.py passes it, and from the next rebuild on every question
failed before a request was sent. Nothing reported it: the eval tests the pinned
environment, and app.py showed visitors a polite message and discarded the reason.

This script removes that failure class instead of adding a reminder about it.

  --index  upload chroma/ exactly as built, delete everything else under the
           Space's chroma/, and delete the stray index files at the Space root.
  --app    upload app.py; a requirements.txt derived from the repo's with the
           gradio pin removed (the Space installs Gradio from its README's
           sdk_version); and that README with sdk_version set from the same pin.
           One source of truth: the repo's requirements.txt.
  --smoke  if the upload changed anything, wait for the rebuild, then call the
           app's undocumented `health` endpoint, which runs one real question and
           answers "ok" or names the failing layer. A deploy that cannot be shown
           to answer fails the run.
  --check  the health call on its own: upload nothing, wait for nothing, just ask
           whether the live demo still answers. Runs on the corpus schedule, so a
           Space that stops answering is found within hours rather than by someone
           opening it. Between 2026-08-21 and 2026-09-17 nothing asked, and the
           demo failed every question for weeks. Needs no token.

Everything goes into one Space commit, so one deploy is one rebuild.

USAGE
  python scripts/deploy_space.py --app --smoke        # CI, after the eval passes
  python scripts/deploy_space.py --index --smoke      # CI, after the index lands
  python scripts/deploy_space.py --check              # CI, on the corpus schedule
  python scripts/deploy_space.py --index --app --dry-run

Needs HF_TOKEN with write access to the Space (the CORPUS_CI secret in Actions).
Run from anywhere; paths resolve from the repo root.

Quirk to NOT "fix": this uses the Python API, never the `hf upload` CLI. The CLI
calls create_repo(space_sdk=...) on every Space upload, and the July 2026 free-tier
gate rejects that with a 402 before exist_ok is checked. create_commit() never
calls create_repo, so it commits straight to the existing Space, which cannot be
recreated on the free tier.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# The Space ID keeps the pre-rename name on purpose. Do not "fix" it.
SPACE_ID = "RNVizion/ask-the-corpus"
CHROMA = REPO_ROOT / "chroma"

# Only these may be deleted outside chroma/: leftovers of an early upload that
# put an index at the Space root, where app.py never reads.
UUID_DIR = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/")
ROOT_STRAYS = {"chroma.sqlite3"}

FAILED_STAGES = {"BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR", "NO_APP_FILE", "DELETING"}
BUILD_START_WINDOW_S = 300      # how long to wait for the rebuild to begin
BUILD_TIMEOUT_S = 1800          # torch alone is most of a rebuild
POLL_S = 15


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", flush=True)
    sys.exit(1)


def _normalise_argv(argv):
    """Repair flags mangled by smart punctuation, as eval/why.py does.

    iOS rewrites "--" to an en or em dash as you type. Only leading dashes are
    touched."""
    out, fixed = [], False
    for a in argv:
        if a[:1] in ("\u2013", "\u2014"):      # en dash, em dash
            a = "--" + a[1:]
            fixed = True
        out.append(a)
    if fixed:
        print("note: smart-punctuation dashes in the command were read as '--'")
    return out


# ---- what should be on the Space ---------------------------------------------

def space_requirements() -> tuple[bytes, str]:
    """The repo's requirements.txt minus the gradio pin, and that pin's version."""
    lines = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    pins = [ln for ln in lines if re.match(r"^gradio==", ln.strip())]
    if len(pins) != 1:
        fail(f"expected exactly one 'gradio==' pin in requirements.txt, found {len(pins)}")
    version = pins[0].split("==", 1)[1].strip()
    kept = [ln for ln in lines if not re.match(r"^gradio==", ln.strip())]
    return ("\n".join(kept) + "\n").encode("utf-8"), version


def space_readme(api, gradio_version: str) -> bytes:
    """The Space's own README with sdk_version set to the repo's gradio pin."""
    path = api.hf_hub_download(SPACE_ID, "README.md", repo_type="space", force_download=True)
    text = Path(path).read_text(encoding="utf-8")
    new, n = re.subn(r"(?m)^sdk_version:.*$", f"sdk_version: {gradio_version}", text)
    if n != 1:
        fail(f"expected one sdk_version line in the Space README, found {n}")
    return new.encode("utf-8")


def check_local_index() -> list[Path]:
    """chroma/ must be a clean build: one sqlite file and one segment directory."""
    if not (CHROMA / "chroma.sqlite3").is_file():
        fail(f"no index at {CHROMA}; run scripts/ingest.py first")
    segments = [p for p in CHROMA.iterdir() if p.is_dir()]
    if len(segments) != 1:
        fail(f"chroma/ holds {len(segments)} segment directories; ingest.py builds exactly one. "
             "Refusing to publish an index that is not a clean build.")
    return sorted(p for p in CHROMA.rglob("*") if p.is_file())


def plan(api, want_index: bool, want_app: bool):
    from huggingface_hub import CommitOperationAdd, CommitOperationDelete

    remote = set(api.list_repo_files(SPACE_ID, repo_type="space"))
    adds, deletes, expect_sdk = [], [], None

    if want_index:
        local = {f"chroma/{p.relative_to(CHROMA).as_posix()}": p for p in check_local_index()}
        adds += [CommitOperationAdd(path_in_repo=k, path_or_fileobj=str(v)) for k, v in sorted(local.items())]
        stale = sorted(r for r in remote if r.startswith("chroma/") and r not in local)
        strays = sorted(r for r in remote if r in ROOT_STRAYS or UUID_DIR.match(r))
        deletes += [CommitOperationDelete(path_in_repo=r) for r in stale + strays]

    if want_app:
        reqs, expect_sdk = space_requirements()
        adds += [
            CommitOperationAdd(path_in_repo="app.py", path_or_fileobj=str(REPO_ROOT / "app.py")),
            CommitOperationAdd(path_in_repo="requirements.txt", path_or_fileobj=reqs),
            CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=space_readme(api, expect_sdk)),
        ]
    return adds, deletes, expect_sdk


# ---- proving it answers --------------------------------------------------------

def wait_for_rebuild(api, expect_sdk: str | None) -> None:
    """Wait for the rebuild the commit started, then for the Space to run again.

    The runtime reports no commit sha, so "this is the new build" is established by
    seeing the Space leave RUNNING first. If no rebuild is seen within the window
    the check still runs, against whatever is live, and says so.
    """
    t0, seen_build = time.time(), False
    while True:
        rt = api.get_space_runtime(SPACE_ID)
        stage, elapsed = str(rt.stage), time.time() - t0
        if stage in FAILED_STAGES:
            fail(f"Space stage {stage}: {rt.raw.get('errorMessage') or 'no error message'}")
        if stage != "RUNNING":
            if not seen_build:
                print(f"rebuild started ({stage}) after {elapsed:.0f}s", flush=True)
            seen_build = True
        elif seen_build:
            print(f"Space RUNNING again after {elapsed:.0f}s", flush=True)
            break
        elif elapsed > BUILD_START_WINDOW_S:
            print(f"::warning::no rebuild seen in {BUILD_START_WINDOW_S}s; checking the app that is live now")
            break
        if elapsed > BUILD_TIMEOUT_S:
            fail(f"Space still {stage} after {BUILD_TIMEOUT_S}s")
        time.sleep(POLL_S)

    got_sdk = rt.raw.get("sdkVersion")
    if expect_sdk and got_sdk and got_sdk != expect_sdk:
        fail(f"Space reports Gradio {got_sdk}; the repo pins {expect_sdk}")


def check_health(inconclusive_ok: bool = False) -> None:
    """Ask the live app one real question through its health endpoint.

    inconclusive_ok is for the scheduled check: a rate-limited reply means the
    limiter answered, not the pipeline, and reddening the corpus schedule because
    the demo was busy would teach everyone to ignore it. A deploy still demands
    proof, so the deploy path leaves it False.
    """
    from gradio_client import Client

    last = "no attempt"
    for attempt in range(1, 7):
        try:
            result = Client(SPACE_ID, verbose=False).predict(api_name="/health")
        except Exception as exc:  # the app can take a moment after RUNNING
            last = f"{type(exc).__name__}: {exc}"
        else:
            if result == "ok":
                print("health: ok (one real question answered end to end)", flush=True)
                return
            if str(result).startswith("fail"):
                fail(f"health: {result}. The reason is in the Space's container log.")
            if result == "rate-limited" and inconclusive_ok:
                print("::warning::health: rate-limited, so the pipeline was not exercised")
                return
            last = f"health returned {result!r}"
        print(f"health attempt {attempt}: {last}; retrying", flush=True)
        time.sleep(20 * attempt)
    fail(f"could not verify the Space answers: {last}")


# ---- main ------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--index", action="store_true", help="upload chroma/ and prune the rest")
    ap.add_argument("--app", action="store_true", help="upload app.py, requirements, README")
    ap.add_argument("--smoke", action="store_true", help="after a change, prove the app answers")
    ap.add_argument("--check", action="store_true", help="only ask whether the live app answers")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; change nothing")
    args = ap.parse_args(_normalise_argv(sys.argv[1:]))
    if args.check and not (args.index or args.app):
        # Nothing is uploaded, so nothing needs a token: the endpoint is public.
        check_health(inconclusive_ok=True)
        return 0
    if not (args.index or args.app):
        ap.error("nothing to deploy: pass --index, --app, --check, or a combination")
    if not os.environ.get("HF_TOKEN"):
        fail("HF_TOKEN is not set")

    from huggingface_hub import HfApi
    api = HfApi()

    adds, deletes, expect_sdk = plan(api, args.index, args.app)
    print(f"plan: {len(adds)} upload(s), {len(deletes)} deletion(s)")
    for op in deletes:
        print(f"  delete {op.path_in_repo}")
    if args.dry_run:
        for op in adds:
            print(f"  upload {op.path_in_repo}")
        return 0

    before = api.space_info(SPACE_ID).sha
    parts = [p for p, on in (("index", args.index), ("app", args.app)) if on]
    sha = os.environ.get("GITHUB_SHA", "local")[:7]
    info = api.create_commit(
        SPACE_ID, repo_type="space", operations=adds + deletes,
        commit_message=f"deploy {' + '.join(parts)} from rnv-ask-the-corpus@{sha}",
    )
    if info.oid == before:
        print("Space already matches; nothing committed, no rebuild to check.")
        return 0
    print(f"committed {info.oid[:7]} to the Space ({info.commit_url})")

    if args.smoke:
        wait_for_rebuild(api, expect_sdk)
        check_health()
    return 0


if __name__ == "__main__":
    sys.exit(main())
