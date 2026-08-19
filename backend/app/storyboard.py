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
MAX_SPOKEN_SECONDS = 75  # 60s target, 75s hard ceiling
_WORDS_PER_SECOND = 160 / 60

#: Scene types that assert something about the source document, so they must cite it.
FACTUAL_SCENE_TYPES = frozenset({"bullets", "diagram", "compare", "code"})

#: Fields the pipeline owns. Stripped from the model's view of the contract.
PIPELINE_OWNED_FIELDS = ("durationMs", "clipId")


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
            "What the voice says over this scene. Plain spoken prose. No markdown, no stage "
            "directions. Expand abbreviations a voice would stumble on."
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
        max_length=5,
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
    kind: Literal["aidoc", "topic"]
    doc_id: str | None = Field(default=None, description="Required when kind is aidoc.")
    url: str | None = None
    title: str | None = None


class Storyboard(_Model):
    meta: StoryboardMeta
    source: StoryboardSource
    scenes: list[Scene] = Field(
        min_length=3, max_length=8, description="3-8 scenes, under 60 seconds spoken in total."
    )


# --------------------------------------------------------------------------- rules


def spoken_seconds(sb: Storyboard) -> float:
    """Rough spoken length. Rejects a runaway script before we pay for TTS."""
    words = sum(len(scene.narration.split()) for scene in sb.scenes)
    return words / _WORDS_PER_SECOND


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
            if has_clip:
                errors.append(f"{at}.broll.clipId is pipeline-set, the script stage must not emit it")
        else:
            if not has_duration:
                errors.append(f"{at}.durationMs missing, run the voice stage first")
            if scene.broll is not None and not has_clip:
                errors.append(f"{at}.broll.clipId missing, run the visual resolver first")

        if isinstance(scene, DiagramScene):
            nodes = mermaid_node_count(scene.mermaid)
            if nodes > MAX_MERMAID_NODES:
                errors.append(
                    f"{at}.mermaid has {nodes} nodes, max {MAX_MERMAID_NODES}. "
                    "Split the scene or downgrade it to bullets"
                )
            elif nodes < 2:
                errors.append(f"{at}.mermaid parsed to {nodes} nodes, probably malformed")

        if sb.source.kind == "aidoc" and scene.type in FACTUAL_SCENE_TYPES and not scene.cite:
            errors.append(f"{at} ({scene.type}) needs a cite, every factual claim traces to a section")

    if sb.source.kind == "aidoc" and not sb.source.doc_id:
        errors.append("source.docId is required when kind is aidoc")

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
