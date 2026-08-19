"""The render contract — ``storyboard.json`` exactly as the renderer specified it.

This is the ONLY thing that crosses between the generator and the renderer. The
renderer owns this shape; we conform to it. Where their schema and our internal
model disagree, their schema wins here and our extras are stripped at the boundary.

Why this is a separate module from ``storyboard.py``:

    storyboard.py    our internal model. Carries `cite` and `broll`, which the
                     browser reel renders and the MP4 renderer has no slot for.
                     Six React scene components and the feed read this shape.
    render_contract   the wire format. Their names, their nesting, their limits.

Keeping them apart means their schema can move without touching the web app, and
our feed keeps its citation chip without asking them to carry a field they do not
want. The projection is ``from_storyboard`` and it is almost an identity map.

Their seven rules, and where each is enforced:

    1. 4-6 scenes                         schema (min_length/max_length)
    2. narration plain, <=2 sentences     storyboard.check_narration
    3. exactly one visual.kind            schema (discriminated union)
    4. mermaid valid and simple           storyboard.check_mermaid
    5. architecture as diagram, current
       and proposed as separate scenes    prompt (see pipeline._SYSTEM)
    6. unique stable scene id             _check_ids, ids assigned by projection
    7. every label comes from the doc     grounding validator (not here; needs
                                          the source sections)

Rule 7 is the only one this module cannot see, because it has no access to the
source document. It belongs with the internal validator.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from . import storyboard as internal
from .config import settings

log = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"

#: The renderer's limits. Defined in ``storyboard`` because generation has to obey
#: them too, and one source of truth beats two that agree today.
MIN_SCENES = internal.MIN_SCENES
MAX_SCENES = internal.MAX_SCENES

#: Emitted in `style` when we do not override. The renderer has its own defaults for
#: every one of these; we send them so the output is self-describing rather than
#: dependent on which renderer build reads it.
DEFAULT_ASPECT_RATIO = "9:16"
DEFAULT_FPS = 30
DEFAULT_PALETTE = ("#2563eb", "#7c3aed", "#f8fafc")


class _Wire(BaseModel):
    """camelCase on the wire, snake_case in Python. Unknown fields are a bug, not input."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


# --------------------------------------------------------------------------- visuals


class TitleVisual(_Wire):
    kind: Literal["title"]
    heading: str
    subtitle: str | None = None


class DiagramVisual(_Wire):
    kind: Literal["diagram"]
    mermaid: str
    heading: str | None = None


class BulletsVisual(_Wire):
    kind: Literal["bullets"]
    bullets: list[str] = Field(min_length=1, max_length=internal.MAX_BULLETS)
    heading: str | None = None


class ComparisonSide(_Wire):
    label: str
    icon: str | None = None


class ComparisonVisual(_Wire):
    """Two labels and an optional icon each.

    Deliberately thin, because the renderer's spec gives it no slot for per-side
    items. Our internal `compare` scene carries up to four items a side; those have
    nowhere to land here, so the projection records them as a warning instead of
    dropping them quietly. Rule 5 covers before/after architecture with two diagram
    scenes, which is why this stays a light device rather than a content carrier.
    """

    kind: Literal["comparison"]
    left: ComparisonSide
    right: ComparisonSide
    heading: str | None = None


class CodeVisual(_Wire):
    kind: Literal["code"]
    code: str
    language: str | None = None
    heading: str | None = None


class OutroVisual(_Wire):
    kind: Literal["outro"]
    heading: str | None = None
    cta_text: str | None = None


Visual = Annotated[
    Union[TitleVisual, DiagramVisual, BulletsVisual, ComparisonVisual, CodeVisual, OutroVisual],
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------- scenes


class RenderScene(_Wire):
    id: str
    narration: str
    visual: Visual
    on_screen_text: str | None = None
    motion: Literal["fade", "push_in", "none"] | None = None


class RenderStyle(_Wire):
    aspect_ratio: str | None = None
    palette: list[str] | None = None
    fps: int | None = None


class RenderStoryboard(_Wire):
    schema_version: str = SCHEMA_VERSION
    title: str
    subtitle: str | None = None
    style: RenderStyle | None = None
    scenes: list[RenderScene] = Field(min_length=MIN_SCENES, max_length=MAX_SCENES)


# ----------------------------------------------------------------------- validation


class RenderContractInvalid(ValueError):
    """Raised with every problem found, not just the first.

    Mirrors ``storyboard.StoryboardInvalid`` so the pipeline's self-repair loop can
    feed these errors back to the model unchanged.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _check_ids(scenes: list[RenderScene], errors: list[str]) -> None:
    seen: set[str] = set()
    for index, scene in enumerate(scenes):
        if not scene.id.strip():
            errors.append(f"scenes.{index}.id is empty")
        elif scene.id in seen:
            errors.append(f"scenes.{index}.id '{scene.id}' is a duplicate, ids must be unique")
        seen.add(scene.id)


def validate_render_storyboard(data: Any) -> RenderStoryboard:
    """Validate a candidate ``storyboard.json`` against the renderer's rules.

    Runs before anything is handed over, because the renderer rejects a malformed
    file loudly and a rejection costs us a whole job.

    :raises RenderContractInvalid: with a list of every problem found
    """
    try:
        sb = RenderStoryboard.model_validate(data)
    except Exception as exc:
        raise RenderContractInvalid(internal._format_pydantic_errors(exc)) from exc

    errors: list[str] = []
    _check_ids(sb.scenes, errors)

    for index, scene in enumerate(sb.scenes):
        at = f"scenes.{index}"
        internal.check_narration(at, scene.narration, errors)
        if isinstance(scene.visual, DiagramVisual):
            internal.check_mermaid(f"{at}.visual", scene.visual.mermaid, errors)

    if errors:
        raise RenderContractInvalid(errors)
    return sb


# ----------------------------------------------------------------------- projection


def scene_id(index: int) -> str:
    """Stable, unique scene id (rule 6).

    Derived from position rather than asked of the model: the model has no reason to
    invent an identifier, and a positional id is stable for a given storyboard while
    being impossible to duplicate.
    """
    return f"s{index + 1}"


def _project_visual(scene: Any, at: str, warnings: list[str]) -> Visual:
    match scene.type:
        case "title":
            return TitleVisual(kind="title", heading=scene.heading, subtitle=scene.sub)
        case "bullets":
            return BulletsVisual(kind="bullets", heading=scene.heading, bullets=list(scene.bullets))
        case "diagram":
            return DiagramVisual(kind="diagram", heading=scene.heading, mermaid=scene.mermaid)
        case "compare":
            dropped = list(scene.left.items) + list(scene.right.items)
            if dropped:
                warnings.append(
                    f"{at}: comparison carries no items in the render contract, "
                    f"so {len(dropped)} item(s) are not in the MP4: {dropped}"
                )
            return ComparisonVisual(
                kind="comparison",
                heading=scene.heading,
                left=ComparisonSide(label=scene.left.label),
                right=ComparisonSide(label=scene.right.label),
            )
        case "code":
            return CodeVisual(
                kind="code", heading=scene.heading, code=scene.code, language=scene.lang
            )
        case "outro":
            return OutroVisual(kind="outro", cta_text=scene.cta)
        case unknown:  # pragma: no cover - the internal union makes this unreachable
            raise RenderContractInvalid([f"{at}: unknown internal scene type {unknown!r}"])


def from_storyboard(
    sb: internal.Storyboard, *, style: RenderStyle | None = None
) -> tuple[RenderStoryboard, list[str]]:
    """Project our internal storyboard onto the renderer's schema.

    ``cite``, ``broll`` and ``durationMs`` are dropped: the renderer's schema has no
    slot for the first two, and it computes timing itself from the real narration
    audio, so sending a duration would be a value it has to ignore.

    :returns: the wire storyboard, and any warnings about content that could not be
        represented. Warnings are for us, and never travel in the file.
    """
    warnings: list[str] = []
    scenes: list[RenderScene] = []

    for index, scene in enumerate(sb.scenes):
        at = f"scenes.{index}"
        scenes.append(
            RenderScene(
                id=scene_id(index),
                narration=scene.narration,
                visual=_project_visual(scene, at, warnings),
            )
        )

    # The top-level subtitle is the title scene's sub when there is one. Taken rather
    # than generated, so the projection never invents a line of copy.
    subtitle = next(
        (s.sub for s in sb.scenes if isinstance(s, internal.TitleScene) and s.sub), None
    )

    wire = RenderStoryboard(
        schema_version=SCHEMA_VERSION,
        title=sb.meta.title,
        subtitle=subtitle,
        style=style
        or RenderStyle(
            aspect_ratio=DEFAULT_ASPECT_RATIO,
            palette=list(DEFAULT_PALETTE),
            fps=DEFAULT_FPS,
        ),
        scenes=scenes,
    )
    return wire, warnings


def to_json(sb: RenderStoryboard) -> dict:
    """The file, as a camelCase dict. ``exclude_none`` keeps optionals out entirely."""
    return json.loads(sb.model_dump_json(by_alias=True, exclude_none=True))


def write_bundle(job_id: str, sb: internal.Storyboard) -> Path:
    """Write ``storyboard.json`` where the voice and render stages will look for it.

    The handoff in the architecture is literally one file, and steps 3 and 4 run on
    the same box, so a file on disk is the seam — not an HTTP round trip to our own
    API. The voice stage reads this, writes ``scene<N>.wav`` beside it, and the render
    stage writes ``scene<N>.png`` and ``video.mp4`` in the same directory.

        <work_dir>/<job_id>/storyboard.json    <- this
                            scene1.wav ...      <- voice stage
                            scene1.png ...      <- render stage
                            video.mp4           <- render stage, then copied to media

    The directory is not served at any URL: it holds intermediate work derived from
    internal documents, and only the finished MP4 belongs in ``media_dir``.

    :returns: the path written
    :raises RenderContractInvalid: rather than writing a file the renderer will reject
    """
    payload, warnings = emit(sb)
    directory = Path(settings.work_dir) / job_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "storyboard.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    log.info("wrote %s (%d scenes, %d warning(s))", path, len(payload["scenes"]), len(warnings))
    return path


def emit(sb: internal.Storyboard) -> tuple[dict, list[str]]:
    """Project, validate, serialise. The one call the API needs.

    :raises RenderContractInvalid: if the projection would produce a file the
        renderer rejects. That is our bug or a gap in the internal validator, never
        the renderer's problem to discover.
    """
    wire, warnings = from_storyboard(sb)
    validate_render_storyboard(to_json(wire))
    for warning in warnings:
        log.warning("render projection: %s", warning)
    return to_json(wire), warnings
