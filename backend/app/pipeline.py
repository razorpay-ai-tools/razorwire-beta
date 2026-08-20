"""The generation pipeline.

Stage 1 (here): source text -> storyboard, via a Claude tool call whose
``input_schema`` is generated from the same models that validate the result. When
validation fails the errors are handed back to the model and it retries, so a
malformed storyboard costs a retry instead of a failed job.

Stages 2 and 3 (voice, visuals) are only needed for the MP4 export path. The
browser reel narrates with the Web Speech API and derives scene timing from
narration length, so the default path ships a script-stage storyboard and never
waits on TTS. See docs/PLAN.md 5.6.
"""

from __future__ import annotations

import json
import logging
import re

from .config import settings
from .storyboard import (
    BrollMood,
    MAX_NARRATION_SENTENCES,
    Storyboard,
    StoryboardInvalid,
    sentence_count,
    tool_input_schema,
    validate_storyboard,
)

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 6
_MAX_SOURCE_CHARS = 60_000

_SYSTEM = f"""You turn internal Razorpay engineering documents into 60-second vertical explainer videos.

You produce a storyboard. Another system renders it, narrates it, and publishes it to an internal feed.

Rules that matter more than style:

1. GROUNDING. Every factual scene must carry a `cite` naming the section it came from, using the
   source's own headings verbatim — a document section for a document, or the author-and-time
   heading of a message for a Slack thread. If the source does not say something, do not put it
   in the storyboard. A viewer must be able to check any claim against the source.

2. DIAGRAMS ARE A NARRATED WALKTHROUGH. For architecture, emit a `diagram` scene whose `steps`
   are the flow — one hop per step: `src`, `dst`, an optional `label` (the action on that hop, e.g.
   "create order API"), and `say` (one or two spoken sentences describing THAT hop). Use the
   source's real component names. The diagram is BUILT from the steps and each box and arrow is
   drawn on screen exactly as its `say` is spoken, so keep each `say` to its single hop and put the
   steps in flow order. Do NOT write Mermaid yourself. At most {{max_nodes}} distinct components
   across the steps. Never invent a hop the source does not describe. Also give a one-line
   `narration` summarising the whole scene.

3. NARRATION IS SPOKEN. Plain prose a voice reads aloud, at most {{max_sentences}} sentences per
   scene. No markdown, no bullet characters, no emoji, no stage directions, and never a URL —
   the voice reads "https colon slash slash" out loud. Expand things a voice stumbles on: "MCC"
   becomes "merchant category code", "block_fund" becomes "block fund". On-screen `bullets` are
   read by the eye, narration by the ear — they should not be the same words.

4. BUDGET. {{min_scenes}} to {{max_scenes}} scenes, and all narration together must stay under 60
   seconds spoken, which is roughly 150 words in total. Open with why an engineer should care;
   close with an outro.

4b. ARCHITECTURE IS ALWAYS A DIAGRAM. Never describe a system in prose or bullets when the
   document gives you components and flow — use a `diagram` scene with `steps`. When the document
   has both a current and a proposed architecture, emit them as TWO SEPARATE `diagram` scenes, in
   that order, so the change is visible rather than asserted.

4c. `compare` IS A LIGHT DEVICE. Its per-side items do not survive into the final video, so use
   it only when the two labels alone carry the point. Anything with real content belongs in
   `bullets`, and any before/after architecture belongs in two `diagram` scenes per 4b.

5. FOOTAGE. `broll.mood` picks background video from a fixed set: {{moods}}. It is decoration
   behind your content and carries no information. Use `abstract` behind dense scenes such as
   diagrams and code, where busy footage would fight the overlay.

Shape a story, not a summary: the problem, what changes, and what the viewer must not get wrong.
"""

_TOOL_NAME = "emit_storyboard"

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _clamp_narrations(candidate: dict) -> None:
    """Trim each scene's narration to MAX_NARRATION_SENTENCES sentences, in place.

    A weaker or translated model often over-writes by a sentence; repairing it here is
    cheaper and more reliable than bouncing the whole storyboard back through a retry.
    """
    def clamp(text: str) -> str:
        text = text.strip()
        if sentence_count(text) > MAX_NARRATION_SENTENCES:
            return " ".join(_SENTENCE_SPLIT.split(text)[:MAX_NARRATION_SENTENCES]).strip()
        return text

    scenes = candidate.get("scenes")
    if not isinstance(scenes, list):
        return
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        if isinstance(scene.get("narration"), str):
            scene["narration"] = clamp(scene["narration"])
        steps = scene.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if isinstance(step, dict) and isinstance(step.get("say"), str):
                    step["say"] = clamp(step["say"])


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


def _user_prompt(kind: str, text: str, doc_title: str | None) -> str:
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
    return f"{head}\n\n---\n{text[:_MAX_SOURCE_CHARS]}\n---"


def run_script_stage(
    *,
    kind: str,
    text: str,
    doc_id: str | None = None,
    doc_title: str | None = None,
    doc_url: str | None = None,
) -> Storyboard:
    """Generate and validate a storyboard.

    :raises RuntimeError: if no API key is configured
    :raises StoryboardInvalid: if the model cannot produce a valid storyboard in
        ``MAX_ATTEMPTS`` attempts; carries the final round of errors
    """
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    from anthropic import Anthropic

    client = Anthropic(
        api_key=settings.anthropic_api_key, base_url=settings.anthropic_base_url or None
    )
    tool = {
        "name": _TOOL_NAME,
        "description": "Emit the finished storyboard.",
        "input_schema": tool_input_schema(),
    }
    messages: list[dict] = [{"role": "user", "content": _user_prompt(kind, text, doc_title)}]
    last_errors: list[str] = ["model produced no tool call"]

    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = client.messages.create(
            model=settings.anthropic_model,
            # Thinking-capable models (e.g. glm via the gateway) spend output tokens on
            # reasoning before the tool call, and a large doc yields a large storyboard,
            # so 4096 truncated the tool_use mid-JSON ("scenes: Field required"). 16k gives
            # room for the reasoning plus the full storyboard.
            max_tokens=16000,
            system=_system_prompt(),
            tools=[tool],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=messages,
        )

        block = next((b for b in response.content if getattr(b, "type", None) == "tool_use"), None)
        if block is None:
            last_errors = ["model produced no tool call"]
            messages.append({"role": "user", "content": f"Call the {_TOOL_NAME} tool."})
            continue

        candidate = dict(block.input)
        # Gateway-translated models (e.g. glm via LiteLLM) sometimes nest the whole
        # payload under a single wrapper key instead of returning {meta, scenes}. Unwrap it.
        if "scenes" not in candidate:
            nested = next(
                (v for v in candidate.values() if isinstance(v, dict) and "scenes" in v), None
            )
            if nested is not None:
                candidate = dict(nested)
        # Repair the most common model slip (an extra sentence) instead of retrying.
        _clamp_narrations(candidate)
        # the pipeline owns these; the source fields are ours to set, not the model's
        candidate["source"] = {
            "kind": kind,
            **({"docId": doc_id} if doc_id else {}),
            **({"url": doc_url} if doc_url else {}),
            **({"title": doc_title} if doc_title else {}),
        }

        try:
            return validate_storyboard(candidate, stage="script")
        except StoryboardInvalid as invalid:
            last_errors = invalid.errors
            log.warning("storyboard invalid on attempt %d/%d: %s", attempt, MAX_ATTEMPTS, invalid.errors)
            # Echo back a CLEAN tool_use block (only the input fields). block.model_dump()
            # also carries fields like `caller` that Anthropic-on-Bedrock via the LiteLLM
            # gateway rejects on input ("tool_use.caller: Input should be a valid dictionary"),
            # which 400s the whole self-repair retry.
            messages.append(
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                    ],
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "is_error": True,
                            "content": (
                                "The storyboard was rejected. Fix every problem and call the tool "
                                "again:\n" + "\n".join(f"- {e}" for e in last_errors)
                            ),
                        }
                    ],
                }
            )

    raise StoryboardInvalid(last_errors)


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
