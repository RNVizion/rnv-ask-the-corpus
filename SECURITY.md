# Security Policy

Ask the Corpus is a public, anonymous question-answering endpoint over published writing. It has no login and no authorization layer, so this policy is mostly about the two things most policies barely mention: what it costs to run, and what is allowed into the index.

## Supported versions

One deployment, no maintained branches. Whatever is on `main` is what runs; there are no backports and no supported older versions.

The canonical deployment is the Hugging Face Space at `https://huggingface.co/spaces/RNVizion/ask-the-corpus`. If you are testing anything else, read "Out of scope" first.

## Reporting a vulnerability

Email `security@rnvizion.dev`, or use GitHub's private vulnerability reporting on this repository.

You will get an acknowledgment **within seven days**. That is a range one person can keep rather than a number that sounds good; if seven days pass with nothing, send it again.

**There is no bounty.** This is a solo project with no budget behind it. What you get is a real reply, a fix if it is a real finding, and credit if you want it.

## Threat model, stated plainly

The corpus is published writing. Every answer is drawn from pages already live on `rnvizion.dev`, indexed from a list of URLs in `sources.json`. Someone who extracted the entire index would hold nothing they could not have fetched from the site.

That changes what matters here:

- **There is no authorization surface.** No OAuth, no tokens, no scopes, no roles; nothing to bypass, because nothing is gating anything.
- **The exposure is cost and availability, not confidentiality.** The endpoint spends money per request against an API key.
- **The rate limiter is the security control.** On most projects it is a courtesy; here it is the thing standing between an anonymous caller and an unbounded bill.

## In scope

**Anything that bounds spend.** The demo rejects a question over 500 characters, retrieves five chunks, caps an answer at 400 tokens, and rate-limits to six questions a minute and sixty in a rolling twenty-four hours. The counters live in memory, so they start empty whenever the Space restarts or wakes from sleep. A way to make one request cost far more than it should, or to make the limiter cheap to evade, is the most valuable finding this repository can receive.

**What the limiter counts against.** It keys on the client address the application observes behind Hugging Face's router. Evidence that this resolves to a shared upstream address, so that one caller's traffic limits every visitor, is a finding I want; so is the reverse, a way to present as many clients cheaply.

**Availability.** Any way to make the Space unresponsive for other visitors, short of ordinary traffic.

**The ingest path.** `scripts/ingest.py` fetches only the URLs listed in `sources.json`, and that list is the only thing separating "published" from "indexed." A way to make it fetch something else, or to get content into the index that was never on that list, is a real finding.

**Credential exposure.** Any path that reveals or spends either API key outside the flow it belongs to.

## Not vulnerabilities

These are the reports most likely to arrive, and each one filed as a security issue costs your time and mine and lands in the wrong process.

- **A wrong answer is a correctness bug, not a disclosure.** A retrieval miss, an answer attributed to the wrong source, an answer drawn from a source it should not have used: all of these surface text already public on the site. They are worth reporting; open a normal issue.
- **A refusal that should have been an answer, or an answer that should have been a refusal.** Same reason. Refusal behaviour is a measured property with cases in `eval/` tracking it, graded on every push.
- **The committed `chroma/` directory.** It is in the repository deliberately. It holds embeddings and text chunks of published pages and nothing that is not already on the site.
- **No authentication on the endpoint.** That is the design, not an oversight.

## Out of scope

**Third-party rebuilds, forks, mirrors, and hosted copies.** If the instance you are testing is not the canonical Space named above, report it to whoever operates it; I cannot fix, verify, or answer for a deployment I do not run.

This carries more weight here than on most projects. The application cannot answer anything without an API key. A rebuild either brings its own, in which case its limits, its spend, and its behaviour belong to its operator, or it does not, in which case it does not answer at all.

## Credentials

Two distinct credentials, deliberately separate, both read from `ANTHROPIC_API_KEY` in their own environment:

- the **Space secret** funds live answering and is set in the Hugging Face Space settings;
- **`EVAL_KEY`** is a GitHub Actions secret and funds the eval suite only. `eval.yml` holds it, which is why that workflow's commit-back is restricted to pushes on `main` and its permissions are declared rather than inherited.

Neither is committed to this repository, and neither appears in `chroma/`, in `eval/results.json`, or in any workflow output.

## One behaviour worth knowing before you report it

When the pipeline fails, a visitor gets a fixed message in the answer area rather than an error state. That message is a constant; it is not built from the exception, so nothing internal reaches the page. The underlying reason is returned separately and read by the test harness, not by the interface.

It is named here because an error you provoke will look like an answer. That is a rough edge in the interface, not injected output.

## After you report

I will acknowledge within seven days, say whether I agree it is a problem, and say what I intend to do about it. Fixes land on `main`; the repository and the Space are two separate copies, so a fix on `main` is not yet a fix on the live endpoint, and the push to the Space is a separate deliberate step.

The corpus has nothing to hide. It has a bill to pay, and that is what this file is about.
