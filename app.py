import inspect
import re
import sys
import time
from collections import defaultdict, deque

import gradio as gr
import chromadb
from sentence_transformers import SentenceTransformer
from anthropic import Anthropic
from engine.brand import STATUS, TYPE, WEB, font_faces, fonts_dir   # rnv-brand, pinned in requirements.txt

# ---- config (the guardrail knobs) ----
MODEL = "claude-haiku-4-5"      # cheap + fast; the whole cost story
MAX_INPUT = 500                 # reject longer questions (bounds cost per call)
TOP_K = 5                       # chunks retrieved per question
MAX_PER_SOURCE = 2              # ...of which at most two may come from one source
MAX_TOKENS = 400                # caps answer length, so each call's cost is bounded
TEMPERATURE = 0                 # see below; determinism is a feature here
RATE = {"per_min": 6, "per_day": 60}

# MAX_PER_SOURCE exists because the window is small and the corpus is not flat.
#
# Nearest-neighbour retrieval returns the k closest chunks and nothing stops one
# source holding all of them. On 2026-09-17, "How many tests has Christian
# written?" served four chunks of a single essay about the eval suite; the figure
# published on the home page sat sixth, and the bot answered "two". Four wordings
# of that question produced four different answers, and the deciding character was
# a question mark.
#
# This is not a widening. TOP_K stays at 5 and the same five slots are spent; what
# changes is that one source cannot take the whole window, so a window spans at
# least three sources whenever three are close. A question whose answer genuinely
# lives in one source still gets that source twice, which is what the top of the
# window is for.
#
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

RATE_LIMIT_MESSAGE = (
    "You've hit the demo's rate limit for now — give it a minute, "
    "or try a suggested question."
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
    if not _rate_ok(_client_key(request)):
        return RATE_LIMIT_MESSAGE, None
    return _pipeline(question)


def _client_key(request):
    return request.client.host if request and request.client else "local"


def retrieve(question):
    """The chunks the model is given, with no source allowed to fill the window.

    Returns (ids, documents, metadatas) in served order. Chroma is asked for a
    larger pool and the cap is applied here, so the k nearest are still the
    candidates; only their distribution changes.

    evaluate.py calls this rather than re-querying. It used to hold its own copy
    of the query, which was harmless while both said n_results=TOP_K and would
    have gone quietly wrong the moment one of them capped and the other did not:
    the eval would have scored a window no visitor was served.
    """
    pool = col.query(
        query_embeddings=embedder.encode([question]).tolist(),
        n_results=min(TOP_K * 6, max(col.count(), 1)),
        include=["documents", "metadatas"],
    )
    ids, docs, metas = pool["ids"][0], pool["documents"][0], pool["metadatas"][0]
    kept, per_source = [], defaultdict(int)
    for i, chunk_id in enumerate(ids):
        source = (metas[i] or {}).get("source") or chunk_id.rsplit("-", 1)[0]
        if per_source[source] >= MAX_PER_SOURCE:
            continue
        per_source[source] += 1
        kept.append(i)
        if len(kept) == TOP_K:
            break
    # Fewer than TOP_K here means the corpus genuinely has less to offer than the
    # window holds, which is a fact about the corpus and is passed through as one.
    return [ids[i] for i in kept], [docs[i] for i in kept], [metas[i] for i in kept]


def _pipeline(question):
    """Retrieval, then the model. Returns (text, error), as answer_with_status does.

    Split out so that health() can run the real path behind its own limiter check
    without going through input handling meant for visitors. Behaviour is unchanged.
    """
    try:
        _ids, docs, metas = retrieve(question)
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


def _log_failure(err):
    """Record why a visitor saw ERROR_MESSAGE.

    The reason only: never the question and never the visitor's address, so the
    public demo stays anonymous. Container logs are the only place this appears.
    Until this existed the reason was discarded, and from late August 2026 every
    question failed for weeks with nothing anywhere to say why.
    """
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(f"{stamp} answer failed: {err}", file=sys.stderr, flush=True)


# ---- what the page may draw ----
#
# The model's answer is drawn by Gradio's Markdown component, which reads it with
# a Markdown parser in the browser and lets raw HTML through a sanitiser. That
# sanitiser removes scripts and event handlers. It keeps a picture on another
# host, which the visitor's browser then requests; an inline style, which can
# carry a colour of its own or lay an element over the page; and a form.
# Ruled 2026-10-06: an answer draws Markdown and nothing else, and no picture
# from another host. _drawable below is where that is decided, in text, before
# the browser sees it.
#
# It carries nothing today: the corpus is the operator's own pages. It is the
# route a document someone else wrote would take, so it lands before one exists.

# The characters a backslash makes literal to the browser's Markdown parser.
_LITERAL = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
# White space, and the markers of the quotes and list items a line sits in.
_MARKERS = re.compile(r"(?:[ \t]*(?:>|(?:[-+*]|\d{1,9}[.)])(?=[ \t])))*[ \t]*")
# The line that opens a fenced code block: the fence, and before it nothing but those.
_FENCE = re.compile(r"(" + _MARKERS.pattern + r")(`{3,}|~{3,})(.*)$")
_QUOTED = re.compile(r"[ \t]{0,3}>[ ]?")
_BULLETS = re.compile(r"(?:[-+*][ \t]*)+$")
_ITEM = re.compile(r"(?:[-+*]|\d{1,9}[.)])(?:[ \t]|$)")
_TICKS = re.compile(r"`+")
# Line break tags, "<br>", "<br/>", "<br />" or "</br>" in any case, one or
# several, with any white space after them on the same line.
_BREAKS = re.compile(r"(?:</?br[ \t]*/?>[^\S\n]*)+", re.IGNORECASE)
# Lines the line after them cannot run on from: a heading made with "#", and a
# rule. And a line of "=" or "-" under a paragraph, which makes it a heading.
_HEADING = re.compile(r" {0,3}#{1,6}(?:[ \t]|$)")
_RULE = re.compile(r" {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$")
_UNDERLINE = re.compile(r" {0,3}(?:=+|-+)[ \t]*$")
# A web address written out in angle brackets, which is Markdown's own way to make
# a link of one. Only characters _prose passes through as they are; only where
# the address ends at the bracket, before a space, the end, or closing
# punctuation; and only if it ends in a letter, a digit or one of / # = % + -.
# The browser's parser trims some marks from the end of a bare address, which
# would lose them from the link; this keeps to the ones it never trims.
_ANGLED = re.compile(r"<(https?://[A-Za-z0-9](?:[A-Za-z0-9._:/?#@%&=+,;-]*[A-Za-z0-9/#=%+-])?)>(?=[?!.,:;*_'\")]*(?:\s|\Z))")


def _drawable(text):
    """The answer as the page may draw it: Markdown, with no raw HTML and no picture.

    Two readers have to agree for this to hold: this function, and the parser in
    the browser. It is built not to rely on them reading the answer the same
    way: it writes a new answer in which the parser should find nothing but
    Markdown however it reads it. That has been wrong three times and mended
    three times; what it now rests on is testing, not proof.

      Outside code, what is known to begin something other than Markdown is
      written so that it cannot. Every "<" is written as an entity, so no tag
      can begin. The "!" of "![", which begins a picture, is written as an
      entity: the link stays and the picture does not. So is the colon of "]:",
      because that pair makes a link definition, whose quoted title may run on
      across blank lines and swallow a fence; and the first of any three
      tildes, which would open one.

      A "[" is left as it is, so that a link can be written, unless the first
      "]" after it would be inside code. The browser's parser lets the name of
      a link definition run from a "[" across lines, blank lines and a fence to
      the next "]", and takes the lot for a definition if a colon follows: so
      a "[" before a block whose text holds "]:" would carry the opening fence
      away and leave the block's text to be read as Markdown, tags and all.
      Such a "[" is written as an entity. Measured: this is how two readers got
      a picture past an earlier draft that had no such rule.

      Two kinds of "<" are not written as entities. One is the "<" before a
      web address in angle brackets, which Markdown reads as a link: the
      address is written bare, which the browser's parser links just the same,
      and no bracket is left to become part of the link. The other is a line
      break tag, "<br>", "<br/>", "<br />" or "</br>" in any case, which a
      model writes to break a line in a table cell, where Markdown has no way
      to. Such tags, with the white space after them, become one space, or
      nothing where white space or a line's edge is already beside them, so no
      run of spaces grows. Where a line's own text begins, after its
      indentation and any quote or list markers, they go before the line is
      read, and the line is read for what it has become. A list item or a
      quote whose text was nothing but such tags keeps a space as its text,
      written "&#32;", so that it stays the item or the quote it was with the
      tag. Neither adds anything to the answer but that space.

      Nothing here rests on a backslash. The browser's parser turns a bare web
      address into a link and takes every character up to the next space or "<"
      with it, a backslash included, which sets the character after it free. So a
      backslash pair in the answer is written as the entity of the character it
      made literal, and this function adds no backslash of its own.

      A fenced code block is written again at the left margin, after a blank
      line, inside a fence of backticks longer than any run of them in its body,
      and with nothing after the opening fence: no language label. Its body is
      kept, "<" and all, less the indentation and the quote markers of the list
      item or the quote it sat in: inside a fence the browser draws it as text.
      Every other backtick outside code is an entity, or one of a pair around
      inline code on a single line, so nothing else can open or close a fence.
      A block ends at a line that starts with the fence that opened it, or a
      longer run of the same mark, and holds nothing more but backticks,
      tildes and spaces, indented three spaces or fewer from where the block
      sits; or at the end of the answer. The browser's parser ends it there
      too, and also, in a quote or a list item, where the quote or the item
      ends, which this function does not judge.

      A fence indented four spaces or more, outside any list or quote, is
      read as a fence when a fence further on closes it, before any line that
      looks like a fence with a label. To the parser it would be code made by
      indenting, or text in a paragraph; the model meant a code block, and
      this draws one. Otherwise it is read as the parser reads it.

      Other code made by indenting four spaces, after a blank line, a code
      block, a heading or a rule, and outside any list or quote, is written
      again the same way, less those four spaces. Anywhere else this function
      leaves those lines as text, and where the parser would have made code of
      them, as it does after a table or an empty list item or quote, the code
      shows the entities. Indentation is judged on the answer as Gradio hands
      it to the parser, after inspect.cleandoc.

      So a block that sat in a list item or a quote leaves it. That is the cost
      of not trusting the browser to agree where the item or the quote ends. A
      list number that shared the opening line stays behind, so that a list
      numbered in order carries on from the right number; a bullet next to the
      fence is dropped. What was indented under the block is brought out to the
      margin with it, and a blank line ends it there, so that the next item of
      the list is not run into it.

      Inline code keeps its backticks when it is one pair of single backticks on
      one line and holds neither "<" nor "![". If the browser read a span
      holding either as prose it would be a tag or a picture, so that span is
      drawn as plain text, character for character, and loses only its code
      face. Written with two backticks, or across a line end, its backticks are
      entities like any others, and show.

    No language label means the browser loads no syntax grammar. That is ruled as
    well (2026-10-06): the syntax colours were already off, and one grammar in the
    pinned Gradio, cpp, blanked the whole answer when it loaded without the one it
    is built on. A block labelled mermaid was not drawn as code at all: Gradio
    sets it aside for a diagram, and on the pinned version what reached the page
    was its text, outside any code box, and no diagram.

    The eval does not pass through here: it scores answer_with_status, the text
    the model wrote. _DRAWN below checks this function at import.
    """
    # Read the answer as Gradio will hand it to the browser's parser: Markdown's
    # postprocess runs inspect.cleandoc on it, which expands tabs, takes the
    # white space from the start of the first line, takes from every later line
    # the indentation they all share, and drops blank lines at either end. Doing
    # it here first means indentation is judged as the parser would judge the
    # answer as written. Gradio runs it again on what this returns. That takes
    # any white space from the start of the first line, which is text or blank.
    # Beyond that it changes something only where no code block was written and
    # every line after the first is indented in what this returns: then their
    # indentation goes too. That can happen where the answer began with a blank
    # line, or where a line written again came out blank or indented: one that
    # held nothing but line break tags, or one opening with inline code that
    # begins with white space and holds "<" or "![", written without its
    # backticks.
    text = re.sub(r"\r\n?|[\u2028\u2029]", "\n", text).replace("\x00", "")
    lines = inspect.cleandoc(text).split("\n")
    out, opened, prose, i, shift, under = [], [], [], 0, 0, False
    listed, quoted, blank, para = False, False, True, False

    def flush():
        if prose:
            out.append("\n")
            _prose("\n".join(prose), out, opened)
            prose.clear()

    def block(body):
        longest = max((len(run_) for line in body for run_ in _TICKS.findall(line)), default=0)
        fence = "`" * max(3, longest + 1)
        flush()
        if any("]" in line for line in body):
            _shut(out, opened)
        out.append("\n" + "\n".join(["", fence, *body, fence, ""]))

    while i < len(lines):
        line = lines[i]
        indent = len(line) - len(line.lstrip(" "))
        outside = not (listed or quoted)
        if line.strip(" ") and indent >= 4 and not para and outside and not _fenced(line, lines, i, True):
            # Code made by indenting four spaces, where no paragraph is open for
            # the line to run on from, outside any list or quote. In a list or a
            # quote this function does not judge it, and those lines stay prose.
            j = i
            while j < len(lines) and (not lines[j].strip(" ") or len(lines[j]) - len(lines[j].lstrip(" ")) >= 4):
                j += 1
            while not lines[j - 1].strip(" "):
                j -= 1
            block([line_[4:] for line_ in lines[i:j]])
            i, shift, under, blank, para = j, 0, False, False, False
            continue
        start = _MARKERS.match(line).end()
        leading = _BREAKS.match(line, start)
        if leading:
            # See the docstring: read as it will be written. A list or quote
            # marker whose text was nothing but the tags keeps a space, written
            # as an entity, as its text.
            rest = line[leading.end():] or ("&#32;" if line[:start].strip(" \t") else "")
            line = line[:start] + rest
        found = _fenced(line, lines, i, outside)
        if found:
            opens, j, quotes, margin = found
            before = opens.group(1)
            kept = _BULLETS.sub("", before).rstrip()
            if kept.strip(" \t>"):
                prose.append(kept)                  # a list number on the opening line
            block([_unwrapped(line_, quotes, margin) for line_ in lines[i + 1:j]])
            if ">" in before:
                quoted = True
            elif before.strip(" "):
                listed = True
            elif not indent:
                listed = quoted = False             # a fence at the margin ends any list or quote
            i, shift, under, blank, para = j + 1, margin, False, True, False
            continue
        judged = _unbroken(line)                    # judged as _prose will write it
        if not judged.strip(" "):
            quoted = para = False                   # a blank line ends a quote and a paragraph
        else:
            # A rule, or the line under a paragraph that makes a heading of it.
            rule = _RULE.match(judged) or para and outside and _UNDERLINE.match(judged)
            para = not (rule or _HEADING.match(judged))
            if not para and not indent:
                listed = quoted = False             # a heading or a rule at the margin ends any list or quote
            if judged.lstrip().startswith(">"):
                quoted = True
            elif _ITEM.match(judged, indent) and not rule:
                listed = True
            elif not indent and blank:
                listed = False                      # a paragraph at the margin ends any list
            if shift and not indent:
                shift = 0                           # back at the margin: nothing more was under the block
                if under:
                    prose.append("")                # and what was under it ends here, as it did in the item
            under = bool(shift and indent) and not _ITEM.match(judged, indent)
        blank = not judged.strip(" ")
        prose.append(line[min(shift, indent):])
        i += 1
    flush()
    return "".join(out)[1:]


def _fenced(line, lines, i, outside):
    """The fenced block that line, at lines[i], opens, or None if it opens none.

    Returned: the opening match, the index of the closing line (len(lines) if
    nothing closes it), the number of quote markers, and the margin, which is
    how far the block's lines are taken back to the left. A fence of backticks
    with a backtick after it opens none. Nor does a fence indented four spaces
    or more, outside any list or quote, unless a fence closes it before any
    line that looks like a fence with a label.
    """
    opens = _FENCE.match(line)
    if not opens or opens.group(2)[0] == "`" and "`" in opens.group(3):
        return None
    before, run = opens.group(1), opens.group(2)
    quotes = before.count(">")
    margin = len(_QUOTED.sub("", before[before.rindex(">"):], 1) if quotes else before)
    closes = re.compile(r" {0,3}" + re.escape(run) + r"[~`]*[ \t]*$")
    # A closing fence may be indented three spaces from the start of the
    # answer's text, or of the list item's or the quote's, as the parser has
    # it; outside any list or quote, a fence indented one to three spaces does
    # not move that start.
    near = 0 if outside and margin < 4 and not before.strip(" ") else margin
    j = i + 1
    while j < len(lines) and not closes.match(_unwrapped(lines[j], quotes, near)):
        j += 1
    if outside and margin >= 4 and not before.strip(" "):
        labelled = (_FENCE.match(_unwrapped(line_, 0, margin)) for line_ in lines[i + 1:j])
        if j == len(lines) or any(other and other.group(3).strip() for other in labelled):
            return None
    return opens, j, quotes, margin


def _unbroken(line):
    """A line without its line break tags, as _prose writes it: for judging what kind of line it is."""
    return _BREAKS.sub(lambda m: "" if not m.start() or line[m.start() - 1].isspace() or m.end() == len(line) else " ", line)


def _unwrapped(line, quotes, margin):
    """A line of a fenced block's body, without the quote markers and the indentation of where the block sat."""
    for _ in range(quotes):
        marker = _QUOTED.match(line)
        if not marker:
            break
        line = line[marker.end():]
    return line[min(margin, len(line) - len(line.lstrip(" \t"))):]


def _entity(ch):
    return "&lt;" if ch == "<" else f"&#{ord(ch)};"


def _shut(out, opened):
    """Write as entities the "[" that are still open, because code holding a "]" comes next."""
    for at in opened:
        out[at] = _entity("[")
    opened.clear()


def _prose(s, out, opened):
    """Text outside fenced code, written onto out so that it can only be Markdown.

    opened is where on out each "[" stands that no "]" outside code has yet followed.
    """
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\" and s[i + 1:i + 2] in _LITERAL:
            out.append(_entity(s[i + 1]))   # the character the backslash made literal
            i += 2
        elif c == "`":
            k = i
            while k < n and s[k] == "`":
                k += 1
            j = k
            while j < n and s[j] not in "`\n":
                j += 1
            span = k - i == 1 and k < j < n and s[j] == "`" and s[j + 1:j + 2] != "`"
            if not span:
                out.append(_entity("`") * (k - i))
                i = k
            elif "<" in s[k:j] or "![" in s[k:j]:
                out.append("".join(_entity(ch) if ch in _LITERAL else ch for ch in s[k:j]))
                i = j + 1
            else:
                if "]" in s[k:j]:
                    _shut(out, opened)
                out.append(s[i:j + 1])
                i = j + 1
        elif c == "<" and _BREAKS.match(s, i):
            ends = _BREAKS.match(s, i).end()         # line breaks: one space, or nothing beside one
            if not (i == 0 or s[i - 1].isspace() or ends == n or s[ends].isspace()):
                out.append(" ")
            i = ends
        elif c == "<":
            angled = _ANGLED.match(s, i)
            if angled:
                out.append(angled.group(1))     # the address, bare: nothing _prose would change
                i = angled.end()
            else:
                out.append(_entity(c))
                i += 1
        elif c == "!" and s[i + 1:i + 2] == "[":
            out.append(_entity(c))
            i += 1
        elif c == "[":
            opened.append(len(out))
            out.append(c)
            i += 1
        elif c == "]":
            opened.clear()
            colon = s[i + 1:i + 2] == ":"
            out.append("]" + _entity(":") if colon else c)
            i += 2 if colon else 1
        elif c == "~" and s[i:i + 3] == "~~~":
            out.append(_entity(c))
            i += 1
        else:
            out.append(c)
            i += 1


# What _drawable must make of these, checked when this file is imported. The eval
# imports it, so an edit that changes what the function writes for one of them
# fails there and not on the page. It is a handful of texts on the function's
# main moves and no more: an edit can change what it writes for some other
# text and pass. And it checks the function, not the browser's parser: that is
# measured by rendering, again after any change to the function or to the
# gradio pin.
_DRAWN = (
    ("**bold**, a [link](https://rnvizion.dev/) and `code`", "**bold**, a [link](https://rnvizion.dev/) and `code`"),
    ("<img src=x> ![p](u) \\<b>", "&lt;img src=x> &#33;[p](u) &lt;b>"),
    ("`<article>` and - ~~~", "&lt;article&#62; and - &#126;~~"),
    ("<https://rnvizion.dev/blog/>. <https://rnvizion.dev>x", "https://rnvizion.dev/blog/. &lt;https://rnvizion.dev>x"),
    ('[x]: u "t" ``', '[x]&#58; u "t" &#96;&#96;'),
    ("```cpp\nint a = 1 < 2;\n```", "\n```\nint a = 1 < 2;\n```\n"),
    ("  ~~~\n  a ``` b\n  ~~~", "\n````\na ``` b\n````\n"),
    ("> ```py\n>     a\n> ```\n1. ```\n   b\n   ```\n   c", "\n```\n    a\n```\n\n1.\n\n```\nb\n```\n\nc"),
    ("[a](u) [b\n\n```\n]: c\n```", "[a](u) &#91;b\n\n\n```\n]: c\n```\n"),
    ("a<br>b <br>c<BR/>", "a b c"),
    ("1. <br>    x", "1. x"),
    ("Para\n\n    x < y\n    ```\n\nend", "Para\n\n\n````\nx < y\n```\n````\n\n\nend"),
    ("```\na\n    ```\nb\n```", "\n````\na\n    ```\nb\n````\n"),
    ("Run:\n    ```bash\n    a < b\n    ```\nThen.", "Run:\n\n```\na < b\n```\n\nThen."),
    ("Intro\n\n    ```py\n    x < 1\n    ```\n\nend", "Intro\n\n\n```\nx < 1\n```\n\n\nend"),
    ("x\n  a\n\n      b < c", "x\na\n\n\n```\nb < c\n```\n"),
    ("# Code\n    x < y\nend", "# Code\n\n```\nx < y\n```\n\nend"),
    ("T\n===\n    y < z", "T\n===\n\n```\ny < z\n```\n"),
    ("- a\n***\n\n    k < 2", "- a\n***\n\n\n```\nk < 2\n```\n"),
    ("- a\n```\nx\n```\n    y < z", "- a\n\n```\nx\n```\n\n\n```\ny < z\n```\n"),
    ("a\n<br>\n    b < c", "a\n\n\n```\nb < c\n```\n"),
    ("<br>```js\nx < y\n```", "\n```\nx < y\n```\n"),
    ("- <br>```bash\nx < y\n  ```\nend", "\n```\nx < y\n```\n\nend"),
    ("Title\n---<br>\n    x < y", "Title\n---\n\n```\nx < y\n```\n"),
    ("Type\n    ```\nthen code.", "Type\n    &#96;&#96;&#96;\nthen code."),
    ("Type\n    ```\nthen:\n\n```py\nx < y\n```", "Type\n    &#96;&#96;&#96;\nthen:\n\n\n```\nx < y\n```\n"),
    ("1. <br>\n2. b", "1. &#32;\n2. b"),
    ("Intro\n\n  ```\n  a < b\n     ```\n  c\n  ```\n\nend", "Intro\n\n\n````\na < b\n   ```\nc\n````\n\n\nend"),
)
# The fixed replies must reach the page as they are written. The first two come
# back before the limiter and the pipeline are touched.
_FIXED = (answer_with_status("")[0], answer_with_status("x" * (MAX_INPUT + 1))[0], DENIAL, ERROR_MESSAGE, RATE_LIMIT_MESSAGE)
for _given, _expected in _DRAWN + tuple((fixed, fixed) for fixed in _FIXED):
    if _drawable(_given) != _expected:
        raise RuntimeError("_drawable no longer writes what _DRAWN says it must, for: " + repr(_given))


def answer(question, request: gr.Request = None):
    """What Gradio calls, from the page and from the API. A failure is logged.

    The text goes through _drawable first, which is where what the page may
    draw is decided. A caller of the API gets that same text, entities included.
    """
    text, err = answer_with_status(question, request)
    if err:
        _log_failure(err)
    return _drawable(text)


HEALTH_QUESTION = SUGGESTED[0]


def health(request: gr.Request) -> str:
    """Deploy check: one suggested question through the real pipeline.

    Returns "ok", "rate-limited", or "fail: <layer>" where layer is retrieval or
    model. That is a marker emitted by the pipeline, so a checker never has to infer
    a failure from answer text; the corpus writes about this machine in its own
    words, and text is the one signal here that can collide. The exception itself
    goes to the log, never to the caller: this endpoint is public, only undocumented.

    It spends one model call, so it sits behind the same per-client limiter as a
    visitor's question.
    """
    if not _rate_ok(_client_key(request)):
        return "rate-limited"
    _text, err = _pipeline(HEALTH_QUESTION)
    if err:
        _log_failure(err)
        return "fail: " + err.split(":", 1)[0]
    return "ok"


def _dark_only(theme):
    """The theme with every light value replaced by its dark one.

    The demo has one appearance. Gradio picks light or dark from the visitor's
    device unless the address says otherwise, and until 2026-10-02 this file's
    CSS darkened only the ground, so a device set to Light drew Gradio's light
    text on it: 1.33:1 for the answers, 1.06:1 for the example questions.
    Measured 2026-09-30, and seen by nobody whose device is dark. Copying the
    dark values over the light ones means the device setting and the address
    draw the same page, wherever Gradio colours by a theme value. Nothing is
    hardcoded here: the values it copies are Gradio's own, and _on_register
    below replaces the ones the page draws.

    It does not reach what Gradio colours by its dark class and not by a theme
    value. Three such places are known: the syntax in a fenced code block, which
    the CSS below switches off; the icon of Gradio's error toast, which the CSS
    below sets; and the "Use via API" panel. The footer no longer links to
    that panel, or to the Settings menu and its theme switch; see LAUNCH.
    """
    for name in list(vars(theme)):
        if name.endswith("_dark") and getattr(theme, name) is not None:
            setattr(theme, name[: -len("_dark")], getattr(theme, name))
    return theme


# Colour comes from the brand register, never from a literal in this file.
#
# This table says which register key each thing the page draws takes. The demo
# sits on the website surface, and a third-party widget on a brand surface
# carries the site's cool ramp: ruled 2026-10-02, and mapped by the register's
# owner on 2026-10-04, role by role, from how rnvizion.dev itself uses each key.
# Until then the page took its ground and its gold from the register and
# everything else from Gradio, a blue link and an orange loader among them.
#
# Text on gold is the site's ground, which is what rnvizion.dev's own primary
# button does (color: var(--bg)).
#
# The names are Gradio's theme values. Each is set together with its _dark twin,
# where it has one.
ROLES = {
    "bg": [
        "body_background_fill", "background_fill_primary",
        "button_primary_text_color", "button_primary_text_color_hover",
    ],
    "bg-2": [
        "background_fill_secondary", "block_background_fill",
        "block_label_background_fill", "panel_background_fill",
        "button_secondary_background_fill",
    ],
    "bg-3": [
        "input_background_fill", "input_background_fill_focus",
        "input_background_fill_hover", "code_background_fill",
        "color_accent_soft", "button_secondary_background_fill_hover",
    ],
    "border": [
        "border_color_primary", "block_border_color",
        "block_label_border_color", "panel_border_color",
        "input_border_color", "input_border_color_hover",
        "border_color_accent_subdued", "button_secondary_border_color",
    ],
    "text": [
        "body_text_color", "button_secondary_text_color",
        "button_secondary_text_color_hover",
    ],
    "text-dim": [
        "body_text_color_subdued", "block_label_text_color",
        "block_title_text_color", "block_info_text_color",
        "input_placeholder_color",
    ],
    "accent": [
        "input_border_color_focus", "border_color_accent",
        "link_text_color", "link_text_color_active",
        "link_text_color_hover", "link_text_color_visited",
        "button_primary_background_fill", "button_primary_background_fill_hover",
        "button_primary_border_color", "button_primary_border_color_hover",
        "button_secondary_border_color_hover", "loader_color", "color_accent",
    ],
}

# The focus ring is a shadow, not a colour: Gradio draws one pixel of its own grey
# and a black inset. It is switched off, and the gold focus border carries the
# state.
NO_SHADOW = ("input_shadow_focus",)


def _on_register(theme):
    """The theme with every value the page draws taken from the brand register.

    Raises at import if Gradio no longer has one of the names. Setting a name the
    theme does not know is silent: the page would go back to Gradio's grey with
    every gate green, because no gate renders the page. The eval imports this
    file, so a name that a Gradio bump renamed stops there, before any deploy. A
    key the register no longer has stops the same way.
    """
    known = vars(theme)
    names = [name for group in ROLES.values() for name in group] + list(NO_SHADOW)
    unknown = [name for name in names if name not in known]
    if unknown:
        raise RuntimeError(
            "Gradio's theme has no value named: " + ", ".join(unknown)
            + ". The demo's colours are set by name; see ROLES in app.py."
        )
    for key, group in ROLES.items():
        for name in group:
            for target in (name, name + "_dark"):
                if target in known:
                    setattr(theme, target, WEB[key])
    for name in NO_SHADOW:
        for target in (name, name + "_dark"):
            if target in known:
                setattr(theme, target, "none")
    return theme


# Type comes from the brand register too: Inter for the body and JetBrains Mono
# for code, the roles the register's TYPE gives them. Ruled 2026-10-18. Until
# then the page drew Gradio's own faces, whose semi-bold files hold three of the
# 95 printable ASCII characters, so bold text, the heading and the Ask button
# drew mostly in the device's own face.
#
# The files ship inside rnv-brand, in the folder fonts_dir() names, with their
# licenses, and the register checks the folder at import, naming any file that
# is missing. Gradio serves that folder as static files, and font_faces() writes
# the @font-face rules for it, which head the stylesheet below. Gradio's file
# route names a file by its absolute path, so the stylesheet shows where pip
# installed the package. Headings take the body face, as they did; whether they
# take the brand's display face is not ruled.
#
# Each face is a gr.themes.Font and each fallback a plain string, as in
# Gradio's own themes. All plain strings stop launch() when Gradio's analytics
# are on, which is its default: it compares the theme with its built-in ones,
# and a string there has no .name. A Font around a fallback quotes it,
# and a quoted system-ui is a font name, not the device's interface face.
FONTS = fonts_dir()
gr.set_static_paths(paths=[FONTS])
SANS = [gr.themes.Font(TYPE["body"]["family"]), "ui-sans-serif", "system-ui", "sans-serif"]
MONO = [gr.themes.Font(TYPE["mono"]["family"]), "ui-monospace", "Consolas", "monospace"]

THEME = _on_register(_dark_only(gr.themes.Default(font=SANS, font_mono=MONO)))

# What the theme does not reach is set here, after the brand's @font-face rules,
# and one value of the theme's own that Gradio's base stylesheet overrides on
# one device (the typeface rule). This is all the CSS there is. Every colour in
# it reads the register.
#
# Gradio can render the page on the server or in the browser, and the two put
# this stylesheet on opposite sides of Gradio's own. Rendered on the server,
# Gradio's stylesheets come after this one, so a rule here that only ties with
# one of Gradio's loses; rendered in the browser, they come before it and the
# same rule wins. The Space renders on the server (read from its HTML,
# 2026-10-05). So a rule here that competes with one of Gradio's carries
# !important, and a render in one mode does not show what the other draws.
#
#   The heading colour.
#
#   The text of inline code in an answer. The text of a fenced code block takes
#   the same colour, through the same rule. This one holds in both modes as it
#   is.
#
#   The syntax in a fenced code block. Gradio colours it in a palette of its
#   own, one set on a Light device and another on a Dark one, and no theme
#   value reaches either. Ruled 2026-10-05: switched off, so a block reads in
#   the one code colour on every device. The rule also undoes the one case
#   where Gradio dims a token and does not colour it. An answer now
#   reaches the page with no language label (_drawable; ruled 2026-10-06), so
#   Gradio loads no grammar and makes no token. The rule stays, so that the
#   ruling does not rest on one function.
#
#   A horizontal rule and a table's borders in an answer. Gradio draws the rule
#   in a grey of its own and the table's borders in the text colour. Both take
#   the register's border: mapped by the register's owner on 2026-10-05.
#
#   The footer's separator dots. Gradio leaves them standing when the links
#   they separated are gone; see LAUNCH.
#
#   The fallback list of the code typeface. Rendered on the server, Gradio's
#   base stylesheet replaces the theme's list on a Light device and not on a
#   Dark one, so the two fell to different faces for a glyph the first face
#   lacks. Ruled 2026-10-06: both take the theme's list. This names no face of
#   its own: the list is the theme's, set from the register above. It is set on
#   the container, where no rule of Gradio's sets it, so it competes with
#   nothing.
#
#   The error toast, which Gradio raises itself, as when the connection to the
#   server is lost; this file raises none of its own. Gradio draws its icon,
#   and the countdown bar of a toast that has one, in one of its own reds on a
#   Light device and another on a Dark one; it reads none of the theme's error
#   values, and setting them moved nothing. Its fill is a theme value Gradio
#   picks by device: bg-2 on one, bg on the other. Ruled 2026-10-11, mapped by
#   the register's owner the same day: the red is the register's error red,
#   STATUS["error"], a fill for marks, and the fill is bg-2 on every device.
#   Its border and text already take border and text. The fill rule reaches
#   every kind of toast; Gradio is not known to raise another on this page,
#   and their icons are not ruled.
#
# The button, the ground and the hover used to be set here as well, with
# !important. The theme sets them now, hover included, so there is one place
# that says what colour the button is.
GOLD, CODE, BORDER = WEB["accent"], WEB["code"], WEB["border"]
RAISED, ERROR = WEB["bg-2"], STATUS["error"]

CSS = font_faces(f"/gradio_api/file={FONTS}/") + f"""
h1, h2 {{ color: {GOLD} !important; }}
.gradio-container .prose code {{ color: {CODE}; }}
.gradio-container .prose pre code span.token {{ color: inherit !important; opacity: 1 !important; }}
.gradio-container .prose hr {{ border-top-color: {BORDER} !important; }}
.gradio-container .prose table, .gradio-container .prose tr,
.gradio-container .prose th, .gradio-container .prose td {{ border-color: {BORDER} !important; }}
.gradio-container footer .divider {{ display: none !important; }}
.gradio-container {{ --font-mono: {THEME.font_mono}; }}
.gradio-container .toast-body.error {{ --toast-color: {ERROR} !important; }}
.gradio-container .toast-body {{ background: {RAISED} !important; }}
"""

with gr.Blocks(title="Ask the Corpus") as demo:
    gr.Markdown("# Ask the Corpus")
    gr.Markdown("Ask a question about Christian Smith's work. Answers come only from his published work on rnvizion.dev: his writing and his profile. If it's not there, it says so.")
    inp = gr.Textbox(label="Your question", placeholder="What is squish?", lines=2, max_lines=4)
    btn = gr.Button("Ask", variant="primary")
    # No maths in an answer. Gradio lifts whatever sits between two "$$" out of
    # the text before its Markdown parser runs, and puts it back afterwards as it
    # was, tags and all; a "$$" inside a code block can carry the block's closing
    # fence away with it. An empty list switches that pass off. _drawable relies
    # on it: measured on the first 83 of its test answers, with the default list
    # two of them got a picture's request through.
    out = gr.Markdown(latex_delimiters=[])
    gr.Examples(SUGGESTED, inputs=inp)
    btn.click(answer, inputs=inp, outputs=out)
    inp.submit(answer, inputs=inp, outputs=out)
    # Called by scripts/deploy_space.py after a deploy that changes the Space, and
    # by the cron's health job on every pass. Hidden from the API page.
    gr.api(health, api_name="health", api_visibility="undocumented")


def _launchable(arguments):
    """The arguments the page is launched with, checked against Gradio's launch().

    Raises at import if launch() no longer takes one of them. The eval imports
    this file and never launches it, so an argument that a Gradio bump renamed
    would otherwise pass the eval and stop the Space at start, after the deploy.
    It checks the names, not what Gradio does with the values.
    """
    takes = inspect.signature(gr.Blocks.launch).parameters
    unknown = [name for name in arguments if name not in takes]
    if unknown:
        raise RuntimeError(
            "Gradio's launch() takes no argument named: " + ", ".join(unknown)
            + ". See LAUNCH in app.py."
        )
    return arguments


# What the page is launched with.
#
# footer_links says which of Gradio's three footer links the page shows. Two of
# them open panels of Gradio's own, "Use via API" and Settings, which draw
# colours that are not the register's; the first also follows the visitor's
# device. Ruled 2026-10-05: the footer links to neither, and "Built with Gradio"
# stays. Only the links go: the API still answers, and scripts/deploy_space.py
# calls it after a deploy that changes the Space.
LAUNCH = _launchable({
    "css": CSS,
    "theme": THEME,
    "server_name": "0.0.0.0",
    "server_port": 7860,
    "footer_links": ["gradio"],
})

if __name__ == "__main__":
    demo.launch(**LAUNCH)
