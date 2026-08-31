"""The storyboard contract. Single source of truth.

The backend owns the pipeline (Claude, TTS, Veo resolution), so the backend owns
the contract. Three consumers are generated or driven from the models below:

    - runtime validation           validate_storyboard()
    - the Claude tool input_schema  tool_input_schema()
    - TypeScript types for the web  scripts/emit_contract.py -> storyboard.types.ts

Stage ownership, and the reason to read this before writing pipeline code:

    script stage (Claude)   writes scene content, narration, cite, broll.mood
    voice stage  (TTS)      writes duration_ms    -- Claude must never set it
    visual stage (resolver) writes broll.clip_id  -- Claude must never set it

Both pipeline-owned fields are rejected at the script stage and required at the
render stage. That turns "the video drifted out of sync" and "the model invented
a video asset" from debugging sessions into validation errors.

JSON is camelCase (the web app and Claude both see camelCase); Python stays
snake_case. Pydantic aliases bridge the two.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

MAX_MERMAID_NODES = 7
MAX_SPOKEN_SECONDS = 105  # 90s target, 105s hard ceiling
_WORDS_PER_SECOND = 160 / 60

# --- limits the renderer imposes -------------------------------------------------
# These originate in the renderer's storyboard.json spec, not here. They live in this
# module because generation has to obey them: a scene count or bullet count that
# overshoots cannot be fixed when projecting to the wire format without silently
# dropping content, so the model must be held to the tighter number up front.
# `render_contract` imports them rather than restating them.
MIN_SCENES = 4
MAX_SCENES = 8
MAX_BULLETS = 4
MAX_NARRATION_SENTENCES = 2

#: Mermaid graph directions the renderer parses. `TD` is Mermaid's own synonym for
#: `TB`, and it reads better in a 9:16 frame.
ALLOWED_MERMAID_DIRECTIONS = ("LR", "TB", "TD")
_MERMAID_HEADER = re.compile(r"^\s*(?:graph|flowchart)\s+(LR|RL|TB|TD|BT)\b", re.IGNORECASE)

_SENTENCE_END = re.compile(r"[.!?]+(?:\s|$)")
#: Scheme-qualified or www-prefixed only. A bare "razorpay.com" in prose is not
#: something a TTS engine mangles, and matching bare domains flags ordinary sentences.
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_MARKDOWN = re.compile(r"(?:\*\*|__|`|^\s*#{1,6}\s|\[[^\]]+\]\([^)]+\)|^\s*[-*]\s)", re.MULTILINE)
_EMOJI = re.compile(
    "[" "\U0001f300-\U0001faff" "\U00002600-\U000027bf" "\U0001f000-\U0001f2ff" "\U0000fe0f" "]"
)

#: Scene types that assert something about the source document, so they must cite it.
FACTUAL_SCENE_TYPES = frozenset({"bullets", "diagram", "compare", "code"})

#: Sources with real provenance, where a factual scene has something to point at. An
#: aidoc cites a section heading; a Slack thread cites "Ananya R, 14:32", because the
#: adapter turns every message into a Section headed by its author and time. `topic`
#: is the exception: there is no source, so there is nothing honest to cite.
GROUNDED_SOURCE_KINDS = frozenset({"aidoc", "slack"})

#: Fields the pipeline owns. Stripped from the model's view of the contract.
PIPELINE_OWNED_FIELDS = ("durationMs", "clipId", "audioUrl")


class BrollMood(str, Enum):
    """The ONLY vocabulary Claude has for choosing footage.

    Generative video cannot render legible text or an accurate diagram, so Veo is
    used strictly as a background plate and never as the carrier of information.
    Claude picks a mood from this closed set; a resolver maps the mood to a
    pre-generated, human-prompted Veo clip. Consequences of doing it this way: no
    spec content ever reaches a video prompt, no per-request generation cost, and
    no generation latency on the request path.
    """

    DATAFLOW = "dataflow"   # abstract packets / streams moving through a network
    SERVERS = "servers"     # racks, cabling, blinking indicators
    TEAM = "team"           # people collaborating, over-shoulder, no legible screens
    MONEY = "money"         # coins, cards, transaction motion
    ABSTRACT = "abstract"   # slow gradient / particle motion, safe behind dense overlays
    CITY = "city"           # scale and reach shots


class _Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class Broll(_Model):
    mood: BrollMood = Field(description="Background footage mood. Chosen from the fixed set only.")
    clip_id: str | None = Field(
        default=None,
        description="PIPELINE-SET. The resolver assigns the cached clip. Never set this.",
    )


class ComparePane(_Model):
    label: str = Field(min_length=2, max_length=28, description='e.g. "Legacy" / "Rearch"')
    items: list[Annotated[str, Field(max_length=60)]] = Field(min_length=1, max_length=4)


class _SceneBase(_Model):
    narration: str = Field(
        min_length=10,
        max_length=420,
        description=(
            "What the voice says over this scene. Plain spoken prose, at most "
            f"{MAX_NARRATION_SENTENCES} sentences. No markdown, no emoji, no URLs (the voice "
            "reads them out literally), no stage directions. Expand abbreviations a voice "
            "would stumble on."
        ),
    )
    cite: str | None = Field(
        default=None,
        max_length=80,
        description=(
            'The source section this scene came from, e.g. "Section 4 - Proposed Architecture". '
            "Rendered on screen as a chip. Required for factual scenes when the source is an AIDoc."
        ),
    )
    broll: Broll | None = None
    duration_ms: int | None = Field(
        default=None,
        ge=800,
        description=(
            "PIPELINE-SET. Derived from the measured length of this scene's narration audio. "
            "Never set this."
        ),
    )
    audio_url: str | None = Field(
        default=None,
        description=(
            "PIPELINE-SET. URL of this scene's pre-generated narration audio, played by "
            "the browser reel instead of speech synthesis. Never set this."
        ),
    )


_Heading = Annotated[str, Field(min_length=3, max_length=60)]


class TitleScene(_SceneBase):
    type: Literal["title"]
    heading: _Heading
    sub: str | None = Field(default=None, max_length=90)


class BulletsScene(_SceneBase):
    type: Literal["bullets"]
    heading: _Heading
    bullets: list[Annotated[str, Field(min_length=3, max_length=80)]] = Field(
        min_length=2,
        max_length=MAX_BULLETS,
        description="Short phrases, not sentences. These are read on screen, not aloud.",
    )


class DiagramScene(_SceneBase):
    type: Literal["diagram"]
    heading: _Heading
    mermaid: str = Field(
        min_length=12,
        description=(
            "Mermaid source for the real architecture in the document. Max "
            f"{MAX_MERMAID_NODES} nodes. Prefer 'graph TD' for a 9:16 frame."
        ),
    )


class CompareScene(_SceneBase):
    type: Literal["compare"]
    heading: _Heading
    left: ComparePane
    right: ComparePane


class CodeScene(_SceneBase):
    type: Literal["code"]
    heading: str | None = Field(default=None, min_length=3, max_length=60)
    lang: Literal["go", "ts", "json", "sql", "bash", "yaml"] | None = None
    code: str = Field(min_length=5, max_length=500, description="Max ~12 lines. It has to be legible on a phone.")


class OutroScene(_SceneBase):
    type: Literal["outro"]
    cta: str = Field(min_length=3, max_length=50)
    url: str | None = None


Scene = Annotated[
    Union[TitleScene, BulletsScene, DiagramScene, CompareScene, CodeScene, OutroScene],
    Field(discriminator="type"),
]


class StoryboardMeta(_Model):
    title: str = Field(min_length=4, max_length=70, description="Feed title. Punchy, not the document title verbatim.")
    tags: list[Annotated[str, Field(pattern=r"^[a-z0-9-]+$")]] = Field(min_length=1, max_length=4)


class StoryboardSource(_Model):
    kind: Literal["aidoc", "slack", "topic"]
    doc_id: str | None = Field(default=None, description="Required when kind is aidoc.")
    url: str | None = Field(
        default=None, description="Required when kind is slack: the thread permalink."
    )
    title: str | None = None


class Storyboard(_Model):
    meta: StoryboardMeta
    source: StoryboardSource
    scenes: list[Scene] = Field(
        min_length=MIN_SCENES,
        max_length=MAX_SCENES,
        description=(
            f"{MIN_SCENES}-{MAX_SCENES} scenes, 60 to 90 seconds spoken in total. "
            "Byte-sized reel."
        ),
    )


# --------------------------------------------------------------------------- rules


def spoken_seconds(sb: Storyboard) -> float:
    """Rough spoken length. Rejects a runaway script before we pay for TTS."""
    words = sum(len(scene.narration.split()) for scene in sb.scenes)
    return words / _WORDS_PER_SECOND


def sentence_count(text: str) -> int:
    """Count sentences the way the renderer's rule 2 means it — terminated or trailing."""
    stripped = text.strip()
    if not stripped:
        return 0
    count = len(_SENTENCE_END.findall(stripped))
    # a trailing fragment with no terminator still reads as a sentence
    if not _SENTENCE_END.search(stripped[-2:]):
        count += 1
    return max(count, 1)


def check_narration(at: str, narration: str, errors: list[str]) -> None:
    """Append every narration problem found. Shared with ``render_contract``.

    These are not expressible in a schema: sentence count needs parsing, and the URL
    and emoji rules exist because the narration is spoken by a TTS engine that reads
    "https colon slash slash" out loud rather than skipping it.
    """
    if not narration.strip():
        errors.append(f"{at}.narration is empty")
        return

    sentences = sentence_count(narration)
    if sentences > MAX_NARRATION_SENTENCES:
        errors.append(
            f"{at}.narration is {sentences} sentences, max {MAX_NARRATION_SENTENCES}. "
            "Split the scene or cut a clause"
        )
    if _URL.search(narration):
        errors.append(f"{at}.narration contains a URL, which the voice reads out literally")
    if _MARKDOWN.search(narration):
        errors.append(f"{at}.narration contains markdown, it is spoken aloud not rendered")
    if _EMOJI.search(narration):
        errors.append(f"{at}.narration contains an emoji, which the voice cannot read")


def mermaid_direction(src: str) -> str | None:
    """The declared graph direction, or None when there is no parsable header."""
    match = _MERMAID_HEADER.match(src)
    return match.group(1).upper() if match else None


def check_mermaid(at: str, src: str, errors: list[str]) -> None:
    """Append every diagram problem found. Shared with ``render_contract``.

    The renderer validates diagrams itself and rejects the whole file loudly on a bad
    one, so a malformed diagram that reaches it costs a failed job. Catching it here
    turns that into a retry the model can fix.
    """
    direction = mermaid_direction(src)
    if direction is None:
        errors.append(
            f"{at}.mermaid must start with 'graph LR' or 'graph TB' — "
            "the renderer rejects anything it cannot parse"
        )
    elif direction not in ALLOWED_MERMAID_DIRECTIONS:
        errors.append(
            f"{at}.mermaid direction '{direction}' is not supported, "
            f"use one of {', '.join(ALLOWED_MERMAID_DIRECTIONS)}"
        )

    nodes = mermaid_node_count(src)
    if nodes > MAX_MERMAID_NODES:
        errors.append(
            f"{at}.mermaid has {nodes} nodes, max {MAX_MERMAID_NODES}. "
            "Split the scene or downgrade it to bullets"
        )
    elif nodes < 2:
        errors.append(f"{at}.mermaid parsed to {nodes} nodes, probably malformed")


_NODE_PATTERNS = (
    re.compile(r"([A-Za-z_]\w*)\s*(?:[\[({]|-{2,3}>|==>)"),
    re.compile(r"(?:-{2,3}>|==>)\s*\|[^|]*\|\s*([A-Za-z_]\w*)"),
    re.compile(r"(?:-{2,3}>|==>)\s*([A-Za-z_]\w*)"),
)


def mermaid_node_count(src: str) -> int:
    """Count distinct Mermaid node ids.

    Not expressible in a schema, and an 8-node graph is illegible in a 9:16 frame,
    so it has to be a code-level rule.
    """
    ids: set[str] = set()
    for pattern in _NODE_PATTERNS:
        ids.update(match.group(1) for match in pattern.finditer(src))
    return len(ids)


class StoryboardInvalid(ValueError):
    """Raised with every problem found, not just the first."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_storyboard(data: Any, stage: Literal["script", "render"] = "script") -> Storyboard:
    """Validate shape then semantics.

    :param data: raw value, usually straight off a Claude tool call
    :param stage: ``script`` right after generation, ``render`` once voice and visuals have run
    :raises StoryboardInvalid: with a list of every problem found
    """
    try:
        sb = Storyboard.model_validate(data)
    except Exception as exc:  # pydantic ValidationError, or a non-dict input
        raise StoryboardInvalid(_format_pydantic_errors(exc)) from exc

    errors: list[str] = []

    for index, scene in enumerate(sb.scenes):
        at = f"scenes.{index}"

        has_duration = scene.duration_ms is not None
        has_clip = scene.broll is not None and scene.broll.clip_id is not None
        if stage == "script":
            if has_duration:
                errors.append(f"{at}.durationMs is pipeline-set, the script stage must not emit it")
            if scene.audio_url is not None:
                errors.append(f"{at}.audioUrl is pipeline-set, the script stage must not emit it")
            if has_clip:
                errors.append(f"{at}.broll.clipId is pipeline-set, the script stage must not emit it")
        else:
            if not has_duration:
                errors.append(f"{at}.durationMs missing, run the voice stage first")
            if scene.broll is not None and not has_clip:
                errors.append(f"{at}.broll.clipId missing, run the visual resolver first")

        check_narration(at, scene.narration, errors)

        if isinstance(scene, DiagramScene):
            check_mermaid(at, scene.mermaid, errors)

        if (
            sb.source.kind in GROUNDED_SOURCE_KINDS
            and scene.type in FACTUAL_SCENE_TYPES
            and not scene.cite
        ):
            errors.append(
                f"{at} ({scene.type}) needs a cite, every factual claim traces to its source"
            )

    if sb.source.kind == "aidoc" and not sb.source.doc_id:
        errors.append("source.docId is required when kind is aidoc")
    if sb.source.kind == "slack" and not sb.source.url:
        errors.append("source.url is required when kind is slack, so a viewer can find the thread")

    seconds = spoken_seconds(sb)
    if seconds > MAX_SPOKEN_SECONDS:
        errors.append(
            f"narration is ~{seconds:.0f}s spoken, ceiling is {MAX_SPOKEN_SECONDS}s. Cut a scene"
        )

    if errors:
        raise StoryboardInvalid(errors)
    return sb


def _format_pydantic_errors(exc: Exception) -> list[str]:
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return [str(exc)]
    out = []
    for err in errors():
        loc = ".".join(str(part) for part in err.get("loc", ())) or "/"
        out.append(f"{loc}: {err.get('msg', 'invalid')}")
    return out


# ------------------------------------------------------------------ generated schema


def _strip_pipeline_fields(node: Any) -> Any:
    if isinstance(node, list):
        return [_strip_pipeline_fields(item) for item in node]
    if not isinstance(node, dict):
        return node

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "properties" and isinstance(value, dict):
            out[key] = {
                prop: _strip_pipeline_fields(sub)
                for prop, sub in value.items()
                if prop not in PIPELINE_OWNED_FIELDS
            }
        elif key == "required" and isinstance(value, list):
            out[key] = [item for item in value if item not in PIPELINE_OWNED_FIELDS]
        else:
            out[key] = _strip_pipeline_fields(value)
    return out


def json_schema() -> dict[str, Any]:
    """Full JSON Schema, including pipeline-owned fields. Used to generate TS types."""
    return Storyboard.model_json_schema(by_alias=True)


def tool_input_schema() -> dict[str, Any]:
    """JSON Schema for the Anthropic tool ``input_schema``.

    Generated from the same models the runtime validates against, so the model is
    told exactly what the validator will enforce.

    The pipeline-owned fields are stripped rather than merely documented as
    off-limits, because describing a field the model must not use is an invitation
    to use it.
    """
    return _strip_pipeline_fields(json_schema())
