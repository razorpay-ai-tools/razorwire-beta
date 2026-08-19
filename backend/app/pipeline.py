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
_MAX_SOURCE_CHARS = 60_000

_SYSTEM = f"""You turn internal Razorpay engineering documents into 60-second vertical explainer videos.

You produce a storyboard. Another system renders it, narrates it, and publishes it to an internal feed.

Rules that matter more than style:

1. GROUNDING. Every factual scene must carry a `cite` naming the section it came from, using the
   document's own section headings. If the document does not say something, do not put it in the
   storyboard. A viewer must be able to check any claim against the spec.

2. DIAGRAMS ARE REAL. For architecture, emit actual Mermaid describing the actual components and
   their actual direction of flow, using the document's real service and entity names. Maximum
   {{max_nodes}} nodes, or it will be rejected as illegible on a phone. Prefer `graph TD` for a
   vertical frame. Never invent a component the document does not mention.

3. NARRATION IS SPOKEN. Plain prose a voice reads aloud. No markdown, no bullet characters, no
   stage directions. Expand things a voice stumbles on: "MCC" becomes "merchant category code",
   "block_fund" becomes "block fund". On-screen `bullets` are read by the eye, narration by the
   ear — they should not be the same words.

4. BUDGET. 3 to 8 scenes, and all narration together must stay under 60 seconds spoken, which is
   roughly 150 words in total. Open with why an engineer should care; close with an outro.

5. FOOTAGE. `broll.mood` picks background video from a fixed set: {{moods}}. It is decoration
   behind your content and carries no information. Use `abstract` behind dense scenes such as
   diagrams and code, where busy footage would fight the overlay.

Shape a story, not a summary: the problem, what changes, and what the viewer must not get wrong.
"""

_TOOL_NAME = "emit_storyboard"


def _system_prompt() -> str:
    from .storyboard import MAX_MERMAID_NODES

    return _SYSTEM.format(
        max_nodes=MAX_MERMAID_NODES,
        moods=", ".join(m.value for m in BrollMood),
    )


def _user_prompt(kind: str, text: str, doc_title: str | None) -> str:
    if kind == "aidoc":
        head = f"Document: {doc_title or 'untitled'}\n\nTurn this document into a storyboard."
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

    client = Anthropic(api_key=settings.anthropic_api_key)
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
            max_tokens=4096,
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
            messages.append({"role": "assistant", "content": [block.model_dump()]})
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
