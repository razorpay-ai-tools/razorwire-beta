"""The generation pipeline.

Stage 1 (here): source text -> storyboard, via a model tool call whose ``input_schema``
is generated from the same models that validate the result. When validation fails the
errors are handed back to the model and it retries, so a malformed storyboard costs a
retry instead of a failed job.

The call goes through Razorpay's LiteLLM gateway, which serves Anthropic's
``/v1/messages`` shape and translates it to whichever model is configured. That is why
this module still imports the ``anthropic`` SDK while running ``glm-5p2``: the wire
format is the contract, not the vendor. See ``Settings.llm_base_url``.

Stages 2 and 3 (voice, visuals) are only needed for the MP4 export path. The
browser reel narrates with the Web Speech API and derives scene timing from
narration length, so the default path ships a script-stage storyboard and never
waits on TTS. See docs/PLAN.md 5.6.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent import futures

from .config import settings
from .storyboard import (
    BrollMood,
    Storyboard,
    StoryboardInvalid,
    tool_input_schema,
    validate_storyboard,
)

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
# ponytail: cap prompt size to keep the gateway request under its timeout; add a
# document summarisation stage only if truncating source proves insufficient.
_MAX_SOURCE_CHARS = 32_000
#: Per-request ceiling. 180s cut the script stage off mid-think at exactly 181s on a
#: long source — our own timeout, not the gateway's. A reasoning model at 16384
#: tokens legitimately needs longer than that, so the ceiling has to clear the work
#: it was asked to do; `_STAGE_DEADLINE_SECONDS` is what stops it stacking.
_LLM_TIMEOUT_SECONDS = 420.0
#: Total wall clock allowed across ALL attempts of one stage.
#:
#: The SDK's `timeout` is per HTTP operation — effectively an inactivity timeout —
#: so a reasoning model that keeps streaming never trips it, and three attempts can
#: stack. A 172k-character source spent 64 minutes here before the gateway gave up,
#: with the job pinned at `scripting` the whole time. Checked between attempts: it
#: cannot interrupt a call already in flight, but it stops us starting another.
_STAGE_DEADLINE_SECONDS = 600.0
#: Above this, the source goes through `run_reduce_stage` first. Set just under
#: `_MAX_SOURCE_CHARS`, because a source that would be truncated is exactly the one
#: whose tail is being thrown away unread.
_REDUCE_ABOVE_CHARS = 30_000
#: One reduce call's slice of the source. A single call over the whole thing was the
#: same trap as an oversized script call: handed 120k characters the model spent its
#: entire budget thinking and returned no text at all. Slices are sized like the
#: script stage's window, which is known to work, and they run concurrently.
#: Kept above `_REDUCE_ABOVE_CHARS` so a source only just over the threshold is one
#: slice rather than a tiny second one.
_REDUCE_CHUNK_CHARS = 40_000
#: Hard cap on how much of a runaway source is read at all, across every slice.
_MAX_REDUCE_INPUT_CHARS = 400_000
#: Below this, `run_plan_stage` answers "one part" without a round-trip. 220 words of
#: narration is the whole 90-second budget, and a source needs several times that
#: before a second part has anything of its own to say.
_MIN_CHARS_TO_SPLIT = 6_000

_SYSTEM = f"""You turn internal Razorpay engineering documents into 60-second vertical explainer videos.

You produce a storyboard. Another system renders it, narrates it, and publishes it to an internal feed.

Rules that matter more than style:

1. GROUNDING. Every factual scene must carry a `cite` naming the section it came from, using the
   source's own headings verbatim — a document section for a document, or the author-and-time
   heading of a message for a Slack thread. If the source does not say something, do not put it
   in the storyboard. A viewer must be able to check any claim against the source.

2. DIAGRAMS ARE REAL. For architecture, emit actual Mermaid describing the actual components and
   their actual direction of flow, using the document's real service and entity names. Maximum
   {{max_nodes}} nodes, or it will be rejected as illegible on a phone. Prefer `graph TD` for a
   vertical frame. Never invent a component the document does not mention.

3. NARRATION IS SPOKEN. Plain prose a voice reads aloud, at most {{max_sentences}} sentences per
   scene. No markdown, no bullet characters, no emoji, no stage directions, and never a URL —
   the voice reads "https colon slash slash" out loud. Expand things a voice stumbles on: "MCC"
   becomes "merchant category code", "block_fund" becomes "block fund". On-screen `bullets` are
   read by the eye, narration by the ear — they should not be the same words.

3b. PUNCTUATE FOR BREATH. The voice engine turns punctuation into pauses, so write the pauses
   in: short sentences, a comma where a speaker would take half a beat, an em dash before the
   payoff, a full stop instead of a run-on. Read your narration aloud in your head — if you
   run out of air, so will the voice.

3c. TONE IS LIGHT. Warm, upbeat and plainly glad to explain — a colleague sharing something
   genuinely useful, not a system issuing a briefing. Problems are the setup for a fix, never
   doom. Keep it professional: light means easy to listen to, not jokey.

4. BUDGET. {{min_scenes}} to {{max_scenes}} scenes, and all narration together runs 60 to 90
   seconds spoken — roughly 150 to 220 words in total. Use the room to actually cover the
   document; never pad a thin one to fill it. If the document genuinely cannot be covered in
   90 seconds, cover its most load-bearing storyline completely rather than everything
   shallowly. Open with why an engineer should care; close with an outro.

4b. ARCHITECTURE IS ALWAYS A DIAGRAM. Never describe a system in prose or bullets when the
   document gives you components and flow. When the document has both a current and a proposed
   architecture, emit them as TWO SEPARATE `diagram` scenes, in that order, so the change is
   visible rather than asserted. Every Mermaid graph must start with `graph LR` or `graph TD`.

4c. `compare` IS A LIGHT DEVICE. Its per-side items do not survive into the final video, so use
   it only when the two labels alone carry the point. Anything with real content belongs in
   `bullets`, and any before/after architecture belongs in two `diagram` scenes per 4b.

4d. DIAGRAMS ARE WALKED, NOT SHOWN. The video reveals a diagram one component at a time,
   in the order the Mermaid source declares them. Write the narration as that walk: name
   each component once, in declaration order, saying what it does or hands over — so a
   viewer who has never seen the system can follow the build-up. Same for bullets, which
   appear one at a time in order.

5. FOOTAGE. `broll.mood` picks background video from a fixed set: {{moods}}. It is decoration
   behind your content and carries no information. Use `abstract` behind dense scenes such as
   diagrams and code, where busy footage would fight the overlay.

Shape a story, not a summary: the problem, what changes, and what the viewer must not get wrong.
"""

_TOOL_NAME = "emit_storyboard"


def _system_prompt() -> str:
    from .storyboard import (
        MAX_MERMAID_NODES,
        MAX_NARRATION_SENTENCES,
        MAX_SCENES,
        MIN_SCENES,
    )

    return _SYSTEM.format(
        max_nodes=MAX_MERMAID_NODES,
        max_sentences=MAX_NARRATION_SENTENCES,
        min_scenes=MIN_SCENES,
        max_scenes=MAX_SCENES,
        moods=", ".join(m.value for m in BrollMood),
    )


#: Written on top of the base brief when the storyboard is destined for an MP4 rather
#: than the browser reel. The contract does not change — citations, the node cap and the
#: sixty-second budget all still hold — but what makes a good sixty seconds does.
#:
#: The reel is read as much as watched: it pauses, it is scrubbed, its captions carry the
#: text. A rendered video plays once, straight through, usually with sound. That wants a
#: spine, a worked example and narration written to be heard rather than skimmed.
_VIDEO_STYLE = """
This storyboard becomes a RENDERED VIDEO with a spoken voice track, watched once from
start to finish. Write it as a short informative film, not as slides:

- ONE WORKED EXAMPLE, carried through. Pick a single concrete case the document supports —
  one request, one mandate, one outage — and follow it across the scenes so the viewer
  tracks a story instead of a list of facts. Use the document's real names and numbers.
- ARC, NOT AGENDA. Open on the stake: what breaks, what it costs, who feels it. The very
  first sentence is a hook under twelve words. Turn on the change. Close on what is
  different now. Never open with "this document covers".
- SPOKEN, NOT WRITTEN. Contractions, short sentences, one idea per sentence. The voice is
  the whole soundtrack, so a sentence that would be skimmed on screen has to be heard. No
  lists read aloud as lists.
- LET THE BULLETS BE THE SLIDE. On-screen bullets are a few words each; the narration says
  the sentence around them. Never read a bullet verbatim.
- The example is not a licence to invent. If the document does not give you specifics,
  narrate the general case and cite it — a made-up number in a spoken video is worse than
  in text, because nobody pauses to check it.

None of the above changes what you return. Emit the storyboard by calling the tool, or if
you cannot call tools, reply with the storyboard as a single JSON object and nothing else.
Do not write a screenplay, a shot list, or a treatment in prose: "film" describes how the
narration should sound, not the format of your answer.
"""


def _user_prompt(kind: str, text: str, doc_title: str | None, *, style: str = "reel") -> str:
    if kind == "aidoc":
        head = f"Document: {doc_title or 'untitled'}\n\nTurn this document into a storyboard."
    elif kind == "slack":
        # A thread is an argument that ended somewhere, not a document. The section
        # headings are "Author, HH:MM" per message, so `cite` names who said it.
        head = (
            f"{doc_title or 'A Slack thread'}\n\n"
            "Turn this thread into a storyboard. It is a conversation, not a document, so:\n"
            "- Lead with what was DECIDED or LEARNED, not with the order things were said.\n"
            "- `cite` the message you took each claim from, using its heading verbatim "
            '(for example "Ananya R, 14:32").\n'
            "- Ignore side-tracks, pleasantries and anything unresolved.\n"
            "- Redacted values appear as [entity id], [email] and similar. Never write a "
            "placeholder into narration or a diagram; talk about it in words instead, or "
            "leave it out.\n"
            "- If the thread never reached a conclusion, say what the open question is "
            "rather than inventing an answer."
        )
    else:
        head = (
            "Topic (no source document, so omit `cite` and do not state specifics you cannot "
            "support):\n"
        )
    brief = f"{head}{_VIDEO_STYLE if style == 'video' else ''}"
    return f"{brief}\n\n---\n{text[:_MAX_SOURCE_CHARS]}\n---"


def run_script_stage(
    *,
    kind: str,
    text: str,
    doc_id: str | None = None,
    doc_title: str | None = None,
    doc_url: str | None = None,
    style: str = "reel",
    part: dict | None = None,
) -> Storyboard:
    """Generate and validate a storyboard.

    :param style: ``"reel"`` for the browser storyboard, ``"video"`` for one destined for
        an MP4 with a spoken track. Same contract either way; different brief, because a
        video is watched once with sound and a reel is scrubbed and read.
    :param part: when the plan stage split the source, ``{"title", "focus", "index",
        "total"}`` for the part this storyboard covers. The brief is narrowed to that
        focus and the feed title gains a "— Part i/n" suffix. None means the whole source.
    :raises RuntimeError: if no API key is configured
    :raises StoryboardInvalid: if the model cannot produce a valid storyboard in
        ``MAX_ATTEMPTS`` attempts; carries the final round of errors
    """
    if not settings.llm_api_key:
        raise RuntimeError("LITELLM_API_KEY is not set (or ANTHROPIC_API_KEY for a direct key)")

    from anthropic import Anthropic

    # The gateway serves Anthropic's `/v1/messages` shape for every model it routes, so
    # the only difference from talking to Anthropic directly is where it points. An empty
    # base URL means exactly that: talk to Anthropic directly.
    client = Anthropic(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url or None,
        timeout=_LLM_TIMEOUT_SECONDS,
        max_retries=0,
    )
    tool = {
        "name": _TOOL_NAME,
        "description": "Emit the finished storyboard.",
        "input_schema": tool_input_schema(),
    }
    prompt = _user_prompt(kind, text, doc_title, style=style)
    if part and part.get("total", 1) > 1:
        prompt += (
            f"\n\nThis is part {part['index']} of {part['total']} in a series on this source. "
            f"This part is \"{part['title']}\".\nIts focus: {part['focus']}\n"
            "Cover ONLY this part's focus — the other parts cover the rest."
        )
    messages: list[dict] = [{"role": "user", "content": prompt}]
    last_errors: list[str] = ["model produced no tool call"]

    started = time.monotonic()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        elapsed = time.monotonic() - started
        if attempt > 1 and elapsed > _STAGE_DEADLINE_SECONDS:
            log.warning(
                "script stage out of budget after %.0fs on attempt %d; giving up",
                elapsed,
                attempt,
            )
            break
        response = client.messages.create(
            model=settings.llm_model,
            # glm-5p2 is a reasoning model and the budget must cover thinking AND the
            # storyboard. At 4096 the thinking block alone exhausted it; at 8192 the
            # same failure came back on longer sources — stop_reason=max_tokens, an
            # empty reply, and "no tool call and no JSON to fall back to". Lowering
            # this to shorten a slow call trades a slow success for a certain failure;
            # the way to shorten the call is to shrink the INPUT, which is what
            # run_reduce_stage does.
            max_tokens=16384,
            system=_system_prompt(),
            tools=[tool],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=messages,
        )

        block = next((b for b in response.content if getattr(b, "type", None) == "tool_use"), None)

        if block is None:
            # Forced tool choice is a request, not a guarantee, once the call goes through
            # the gateway to a non-Anthropic model: glm-5p2 answers with the storyboard as
            # JSON in a text block maybe half the time, which failed all three attempts and
            # burned three paid calls to produce nothing. The JSON is right there, so take
            # it — the validator is the gate either way, and a storyboard that passes is
            # worth the same whichever envelope carried it.
            candidate = _json_from_text(response)
            if candidate is None:
                last_errors = ["model produced no tool call and no JSON to fall back to"]
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Call the {_TOOL_NAME} tool. If you cannot call tools, reply with "
                            "the storyboard as a single JSON object and nothing else."
                        ),
                    }
                )
                log.warning("attempt %d/%d: no tool call, no parsable JSON", attempt, MAX_ATTEMPTS)
                continue
            log.info("attempt %d: recovered the storyboard from a text reply", attempt)
        else:
            candidate = dict(block.input)
        # the pipeline owns these; the source fields are ours to set, not the model's
        candidate["source"] = {
            "kind": kind,
            **({"docId": doc_id} if doc_id else {}),
            **({"url": doc_url} if doc_url else {}),
            **({"title": doc_title} if doc_title else {}),
        }

        try:
            sb = validate_storyboard(candidate, stage="script")
            if part and part.get("total", 1) > 1:
                # 70 is StoryboardMeta.title's max_length; the suffix must not push a
                # stored title past re-validation on the read paths.
                suffix = f" — Part {part['index']}/{part['total']}"
                sb.meta.title = f"{sb.meta.title[: 70 - len(suffix)].rstrip()}{suffix}"
            return sb
        except StoryboardInvalid as invalid:
            last_errors = invalid.errors
            log.warning("storyboard invalid on attempt %d/%d: %s", attempt, MAX_ATTEMPTS, invalid.errors)
            complaint = "The storyboard was rejected. Fix every problem and try again:\n" + "\n".join(
                f"- {e}" for e in last_errors
            )

            if block is None:
                # A text-shaped answer has no tool_use_id to attach a tool_result to, and
                # sending one anyway is a 400 from the gateway. Plain turns instead.
                messages.append({"role": "assistant", "content": json.dumps(candidate)})
                messages.append({"role": "user", "content": complaint})
            else:
                messages.append({"role": "assistant", "content": [block.model_dump()]})
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "is_error": True,
                                "content": complaint,
                            }
                        ],
                    }
                )

    raise StoryboardInvalid(last_errors)


def _json_from_text(response) -> dict | None:
    """Pull a storyboard object out of a text reply, or return None.

    Models that cannot or will not call the tool answer with the JSON directly, sometimes
    fenced in ```json, sometimes with a sentence in front of it. Scanning for the outermost
    balanced braces handles all three without a regex that a nested object would defeat.
    """
    text = "".join(
        getattr(block, "text", "") for block in response.content if getattr(block, "type", None) == "text"
    ).strip()
    if not text:
        return None

    # Every `{` is a candidate, not just the first. A reply that opens with "Here is the
    # storyboard {as requested}:" balances a brace before the real object begins, and
    # stopping at the first candidate threw the whole storyboard away.
    #
    # ponytail: O(n^2) worst case on brace-heavy prose. The text is a few KB and this runs
    # once per attempt; revisit if a source ever produces megabytes of it.
    fallback: dict | None = None
    for start, char in enumerate(text):
        if char != "{":
            continue
        candidate = _balanced_object(text, start)
        if candidate is None:
            continue
        # A storyboard has these; a brace in prose does not. Keep looking rather than
        # returning the first thing that happens to parse.
        if "scenes" in candidate or "meta" in candidate:
            return candidate
        fallback = fallback or candidate
    return fallback


def _balanced_object(text: str, start: int) -> dict | None:
    """Parse the object starting at ``start``, or None if it does not close or parse."""
    depth, in_string, escaped = 0, False, False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


# ------------------------------------------------------------------- the plan stage

_PLAN_TOOL = "plan_parts"

_PLAN_SYSTEM = """You decide whether one internal engineering document becomes one explainer video or several.

A video carries 60 to 90 seconds of narration. Most documents fit in one, and ONE part is the
strongly preferred answer: split ONLY when a single 90-second video genuinely cannot cover the
document's load-bearing content. Never more than 3 parts.

When you do split, the parts must be logically segregated stories — for example "the problem and
current architecture" / "the proposed flow end to end" / "migration and rollout" — never arbitrary
halves of the text. Each part must stand alone as one coherent story a viewer can watch on its own.
"""


def _plan_input_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "parts": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Short video title for this part.",
                        },
                        "focus": {
                            "type": "string",
                            "description": (
                                "2-3 sentences: what this part covers and why it is one "
                                "coherent story."
                            ),
                        },
                    },
                    "required": ["title", "focus"],
                },
            }
        },
        "required": ["parts"],
    }


def validate_parts(candidate) -> list[dict[str, str]] | None:
    """1-3 parts with non-empty titles, normalised — or None when the plan is unusable.

    Pure on purpose: the fallback rule ("planning misbehaving never fails a job") is the
    part worth testing, and it needs no client to exercise.
    """
    if not isinstance(candidate, dict):
        return None
    parts = candidate.get("parts")
    if not isinstance(parts, list) or not 1 <= len(parts) <= 3:
        return None
    out: list[dict[str, str]] = []
    for item in parts:
        if not isinstance(item, dict):
            return None
        title = str(item.get("title") or "").strip()
        if not title:
            return None
        out.append({"title": title, "focus": str(item.get("focus") or "").strip()})
    return out


_REDUCE_SYSTEM = """You condense an internal Razorpay engineering document so another model can
script a short explainer from it.

Keep VERBATIM every section heading you take a fact from. The scripting step cites those
headings, and a citation that does not match the source is worse than no citation at all.

Keep: the problem and who it hurts, the decision and its alternatives, the components and
their real direction of flow, the document's own service and entity names, and any number
the document actually states.

Compress hardest on repetition. A table of measurements becomes its finding, not its rows.
Drop changelog noise, restated context, and anything the document never concludes.

Never invent, never generalise a number, and never rename a component. If the document is
ambiguous, say so in one clause rather than resolving it.

Return prose under 8000 characters, organised under those verbatim headings, and nothing else.
"""


def run_reduce_stage(*, text: str, doc_title: str | None = None) -> str:
    """Condense an over-long source before the plan and script stages see it.

    A source far past ``_MAX_SOURCE_CHARS`` was truncated to a dense fragment with no
    narrative, which is the worst possible input for a reasoning model: it thought for
    an hour on a 172k-character SR table dump and the gateway dropped the call. Cutting
    the input is the only lever that shortens the call AND improves the script, because
    both failures came from the same cause.

    Never raises: any failure returns the original text, so a job degrades to the old
    truncate-and-hope behaviour rather than dying here.
    """
    if len(text) <= _REDUCE_ABOVE_CHARS or not settings.llm_api_key:
        return text

    slices = _chunk_on_blank_lines(text[:_MAX_REDUCE_INPUT_CHARS], _REDUCE_CHUNK_CHARS)
    try:
        from anthropic import Anthropic

        client = Anthropic(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url or None,
            timeout=_LLM_TIMEOUT_SECONDS,
            max_retries=0,
        )
    except Exception as exc:
        log.warning("reduce stage unavailable (%s); keeping the source as-is", exc)
        return text

    def condense(chunk: str) -> str:
        response = client.messages.create(
            model=settings.llm_model,
            max_tokens=8192,
            system=_REDUCE_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Document: {doc_title or 'untitled'}\n\nCondense this part of it.\n\n"
                        f"---\n{chunk}\n---"
                    ),
                }
            ],
        )
        return "".join(
            getattr(block, "text", "")
            for block in response.content
            if getattr(block, "type", None) == "text"
        ).strip()

    # Slices are independent, and these are network calls, so they overlap. A slice
    # that fails is dropped rather than failing the job: the rest of the document is
    # still worth scripting from.
    condensed: list[str] = []
    if len(slices) == 1:
        try:
            condensed = [condense(slices[0])]
        except Exception as exc:
            log.warning("reduce stage failed (%s); keeping the source as-is", exc)
            return text
    else:
        with futures.ThreadPoolExecutor(max_workers=min(4, len(slices))) as pool:
            for index, task in enumerate(
                [pool.submit(condense, chunk) for chunk in slices]
            ):
                try:
                    condensed.append(task.result())
                except Exception as exc:
                    log.warning("reduce slice %d/%d failed: %s", index + 1, len(slices), exc)

    reduced = "\n\n".join(part for part in condensed if part).strip()
    # Too little came back to be a condensation of the document; it is a lost document.
    if len(reduced) < 500:
        log.warning("reduce stage returned %d chars; keeping the original", len(reduced))
        return text
    log.info(
        "reduced source from %d to %d chars across %d slice(s)", len(text), len(reduced), len(slices)
    )
    return reduced


def _chunk_on_blank_lines(text: str, size: int) -> list[str]:
    """Split into ~``size`` pieces at paragraph breaks, so a heading stays with the
    text beneath it and no slice starts mid-sentence."""
    blocks = text.split("\n\n")
    chunks: list[str] = []
    current = ""
    for block in blocks:
        if current and len(current) + len(block) + 2 > size:
            chunks.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}" if current else block
    if current:
        chunks.append(current)
    return chunks or [text]


def run_plan_stage(*, kind: str, text: str, doc_title: str | None = None) -> list[dict[str, str]]:
    """One LLM call deciding whether the source is one video or 2-3 logically split parts.

    Never raises: a missing key, a gateway error or an unusable plan all collapse to a
    single part, so planning can only ever widen a job, not fail it. Same gateway and
    text-reply fallback as :func:`run_script_stage`.
    """
    fallback = [{"title": doc_title or "", "focus": ""}]
    if not settings.llm_api_key:
        return fallback
    # A source this short cannot fill one 90-second video, let alone two, so the plan
    # is knowable without asking: skip a whole paid round-trip on the common case.
    # The threshold is deliberately conservative — roughly the length at which a
    # document starts to carry more than one load-bearing storyline.
    if len(text) < _MIN_CHARS_TO_SPLIT:
        log.info("source is %d chars; one part without asking the model", len(text))
        return fallback
    try:
        from anthropic import Anthropic

        # Bounded exactly like the script stage. Left on SDK defaults this call could
        # run 600s and then retry twice, so a slow gateway cost half an hour before
        # the job even started scripting.
        client = Anthropic(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url or None,
            timeout=_LLM_TIMEOUT_SECONDS,
            max_retries=0,
        )
        response = client.messages.create(
            model=settings.llm_model,
            # reasoning models think before they answer; see run_script_stage
            max_tokens=8192,
            system=_PLAN_SYSTEM,
            tools=[
                {
                    "name": _PLAN_TOOL,
                    "description": "Emit the part plan.",
                    "input_schema": _plan_input_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": _PLAN_TOOL},
            messages=[
                {
                    "role": "user",
                    "content": (
                        (f"Document: {doc_title}\n\n" if doc_title else "")
                        + "Plan the explainer video(s) for this source. Call the "
                        f"{_PLAN_TOOL} tool with 1 part unless one 90-second video truly "
                        "cannot carry the load-bearing content.\n\n"
                        f"---\n{text[:_MAX_SOURCE_CHARS]}\n---"
                    ),
                }
            ],
        )
        block = next((b for b in response.content if getattr(b, "type", None) == "tool_use"), None)
        candidate = dict(block.input) if block is not None else _json_from_text(response)
        parts = validate_parts(candidate)
        if parts is None:
            log.warning("plan stage produced an unusable plan; falling back to a single part")
            return fallback
        return parts
    except Exception:
        log.warning("plan stage failed; falling back to a single part", exc_info=True)
        return fallback


def resolve_broll(sb: Storyboard, library: dict[str, str]) -> Storyboard:
    """Assign a cached Veo clip to each scene that asked for footage.

    ``library`` maps mood -> clip id. Claude only ever chose a mood; the clip that
    mood resolves to is ours, which is why no spec text reaches a video prompt and
    why nothing is generated on the request path.
    """
    updated = sb.model_copy(deep=True)
    for scene in updated.scenes:
        if scene.broll is not None:
            scene.broll.clip_id = library.get(scene.broll.mood.value)
    return updated


def storyboard_to_json(sb: Storyboard) -> dict:
    """camelCase dict, as the web app and the stored column expect."""
    return json.loads(sb.model_dump_json(by_alias=True, exclude_none=True))
