import time
from collections import defaultdict, deque

import gradio as gr
import chromadb
from sentence_transformers import SentenceTransformer
from anthropic import Anthropic

# ---- config (the guardrail knobs) ----
MODEL = "claude-haiku-4-5"      # cheap + fast; the whole cost story
MAX_INPUT = 500                 # reject longer questions (bounds cost per call)
TOP_K = 5                       # chunks retrieved per question
MAX_TOKENS = 400                # caps answer length, so each call's cost is bounded
TEMPERATURE = 0                 # see below; determinism is a feature here
RATE = {"per_min": 6, "per_day": 60}

# TEMPERATURE = 0 is a deliberate choice, not a default.
#
# The API default is 1.0, which means the same question over the same context can
# be answered once and refused the next time. For a bot whose entire product claim
# is "it refuses when it should," a refusal that depends on sampling is a claim
# that cannot be measured: the eval gate asserts thresholds on numbers that move
# under it, and two runs of the same commit can disagree. Determinism in a gate
# outranks variety in phrasing, and a grounded question-answering assistant has
# nothing to gain from variety anyway.
#
# This is product surface. Changing it changes live answers, so it belongs in the
# decision log alongside a system-prompt change, not in a quiet commit.

SYSTEM = (
    "You answer questions about the published work of Christian 'RNVizion' Smith: his "
    "blog posts and his profile. Use ONLY the context excerpts provided. If they don't "
    "contain the answer, reply with exactly this line and nothing else: \"The corpus has "
    "knowledge, but the information you seek will not be found here.\" Never use outside "
    "knowledge or guess. When you do answer, keep it concise, and name the source(s) your "
    "answer draws from."
)

DENIAL = "The corpus has knowledge, but the information you seek will not be found here."

# The friendly failure a visitor sees. It is NOT the denial line, and that
# distinction is the whole point of answer_with_status below: to a scorer reading
# only the text, this string is indistinguishable from a real answer, so an API
# outage during an eval run would score as 58 successful answers and the gate
# would pass on a run that measured nothing.
ERROR_MESSAGE = (
    "The demo hit a snag on that one. Try again in a moment, or pick a suggested question."
)


SUGGESTED = [
    "What is squish?",
    "Why was a developer's job never really the code?",
    "What does constraint have to do with creativity?",
    "What kind of roles is Christian looking for?",
]

# ---- load the prebuilt index + embedder once ----
col = chromadb.PersistentClient(path="chroma").get_collection("corpus")
embedder = SentenceTransformer("all-MiniLM-L6-v2")   # must match the ingest model
llm = Anthropic()   # reads ANTHROPIC_API_KEY from the environment

# ---- per-client rate limiter (in-memory) ----
_hits = defaultdict(deque)
def _rate_ok(key):
    now = time.time()
    dq = _hits[key]
    while dq and now - dq[0] > 86400:
        dq.popleft()
    if sum(1 for t in dq if now - t < 60) >= RATE["per_min"] or len(dq) >= RATE["per_day"]:
        return False
    dq.append(now)
    return True


def answer_with_status(question, request: gr.Request = None):
    """The real pipeline. Returns (text, error).

    `error` is None when the pipeline ran, and a short reason string when it did
    not. It is returned rather than stored on the module so that two concurrent
    visitors cannot read each other's status; a global would race, and the eval
    would eventually read a status belonging to a different question.

    The two failure paths are separated deliberately. A Chroma failure and an
    Anthropic failure produce the same message for a visitor and should never
    produce the same diagnosis for a maintainer: one means the index is broken,
    the other means the API is. Collapsing them into a single `except` is how an
    index problem spends a week being investigated as a model problem.
    """
    question = (question or "").strip()
    if not question:
        return "Ask me something about Christian's work.", None
    if len(question) > MAX_INPUT:
        return f"Please keep your question under {MAX_INPUT} characters.", None
    key = request.client.host if request and request.client else "local"
    if not _rate_ok(key):
        return (
            "You've hit the demo's rate limit for now — give it a minute, "
            "or try a suggested question."
        ), None

    try:
        res = col.query(
            query_embeddings=embedder.encode([question]).tolist(),
            n_results=TOP_K,
            include=["documents", "metadatas"],
        )
        docs, metas = res["documents"][0], res["metadatas"][0]
    except Exception as exc:
        return ERROR_MESSAGE, f"retrieval: {type(exc).__name__}: {exc}"

    if not docs:
        # An empty index is not an error path; it is an honest "nothing here."
        return DENIAL, None

    context = "\n\n".join(f"[Source: {m.get('title', '?')}]\n{d}" for d, m in zip(docs, metas))
    try:
        resp = llm.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": f"Context excerpts:\n\n{context}\n\nQuestion: {question}"}],
        )
    except Exception as exc:
        return ERROR_MESSAGE, f"model: {type(exc).__name__}: {exc}"

    return "".join(b.text for b in resp.content if b.type == "text"), None


def answer(question, request: gr.Request = None):
    """What Gradio calls. Same behaviour as before; the status is dropped."""
    text, _err = answer_with_status(question, request)
    return text


CSS = """
.gradio-container {
    background: #0a0a0f;
    --button-primary-background-fill: #d2bc93;
    --button-primary-background-fill-hover: #c4ab7e;
    --button-primary-text-color: #0a0a0f;
    --button-primary-border-color: #d2bc93;
}
h1, h2 { color: #d2bc93 !important; }
.gradio-container button.primary {
    background: #d2bc93 !important;
    color: #0a0a0f !important;
    border-color: #d2bc93 !important;
}
"""

with gr.Blocks(title="Ask the Corpus") as demo:
    gr.Markdown("# Ask the Corpus")
    gr.Markdown("Ask a question about Christian Smith's work. Answers come only from his published work on rnvizion.dev: his writing and his profile. If it's not there, it says so.")
    inp = gr.Textbox(label="Your question", placeholder="What is squish?", lines=2, max_lines=4)
    btn = gr.Button("Ask", variant="primary")
    out = gr.Markdown()
    gr.Examples(SUGGESTED, inputs=inp)
    btn.click(answer, inputs=inp, outputs=out)
    inp.submit(answer, inputs=inp, outputs=out)

if __name__ == "__main__":
    demo.launch(css=CSS,server_name="0.0.0.0", server_port=7860)
