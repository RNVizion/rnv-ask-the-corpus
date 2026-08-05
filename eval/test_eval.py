"""
test_eval.py — pytest gate over the eval metrics.

Reads eval/results.json, the artifact evaluate.py just wrote, and asserts the
aggregate thresholds against it. No Claude calls, no API key.

    python eval/evaluate.py --report-only    # spends the calls, writes the artifact
    pytest eval/test_eval.py -v              # gates on what it wrote

WHY IT NO LONGER RUNS THE SUITE ITSELF
It used to call evaluate.run() a second time and then write_report() again. Three
consequences, none of them intended:

  - Every CI run spent 58 Claude calls twice.
  - The first run's report was overwritten by the second, so the metrics printed
    in the CI log belonged to a run that neither gated nor survived as an
    artifact. Post-mortems were being written from discarded numbers.
  - The report and the gate could disagree. app.py samples at temperature 0 now,
    which narrows that, but two runs of the same commit describing the same
    system should not be two runs at all.

The gate is now a function of a single artifact, which is what a gate should be:
run once, record what happened, assert against the record.

STALENESS IS THE FAILURE THIS INTRODUCES, SO IT IS CHECKED FIRST
An artifact from an older commit would let a green file pass a red system. The
provenance block carries the commit it was generated from; if that disagrees with
HEAD, the run is rejected before any threshold is read. Dating the artifact
before trusting it is the standing rule here, learned three times.
"""
import json
import subprocess
from pathlib import Path

import pytest

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent
RESULTS_JSON = EVAL_DIR / "results.json"

from eval import evaluate  # noqa: E402  (for THRESHOLDS, the single declaration)


def _head_sha():
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=REPO_ROOT, timeout=5,
        )
        return out.stdout.strip()
    except Exception:
        return ""


@pytest.fixture(scope="module")
def results():
    if not RESULTS_JSON.exists():
        pytest.fail(
            f"{RESULTS_JSON} not found. This gate reads the artifact rather than "
            f"re-running the suite; run `python eval/evaluate.py --report-only` first."
        )
    data = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    prov = data.get("provenance", {})

    head = _head_sha()
    recorded = (prov.get("commit") or "").replace("-dirty", "")
    if head and recorded and head != recorded:
        pytest.fail(
            f"results.json was generated from commit {recorded}, but HEAD is {head}. "
            f"A stale artifact would let an old green run pass a changed system. "
            f"Re-run `python eval/evaluate.py --report-only`."
        )
    return data


@pytest.fixture(scope="module")
def metrics(results):
    return results["metrics"]


def test_no_errored_cases(metrics):
    # An errored case is unmeasured, not failed. A run holding any of them is not
    # a valid measurement, and every percentage below is over a shrunken
    # denominator that quietly flatters the result.
    assert metrics.get("error_cases", 0) == 0, {
        "errored": metrics.get("error_cases"),
        "scored": metrics.get("scored_cases"),
        "total": metrics.get("total_cases"),
    }


def test_index_matches_manifest(results):
    # Advisory in spirit, gated in practice: if the index and sources.json differ,
    # the scores describe a corpus that is not the one declared. The coverage
    # guard already fails on the fatal version of this (a case referencing a
    # source the index lacks); this catches the quieter version.
    prov = results.get("provenance", {})
    assert prov.get("index_matches_manifest", True), {
        "indexed": prov.get("sources"),
        "declared": prov.get("declared_sources"),
    }


def test_retrieval_accuracy(metrics):
    assert metrics["retrieval_accuracy"] is not None
    assert metrics["retrieval_accuracy"] >= evaluate.THRESHOLDS["retrieval_accuracy"], metrics


def test_out_of_corpus_refusal(metrics):
    # The honesty thesis, measured: out-of-corpus questions must get the denial line.
    assert metrics["ooc_refusal_accuracy"] >= evaluate.THRESHOLDS["ooc_refusal_accuracy"], metrics


def test_no_false_refusals(metrics):
    # In-corpus questions must NOT be refused.
    assert metrics["false_refusal_rate"] <= evaluate.THRESHOLDS["false_refusal_rate"], metrics
