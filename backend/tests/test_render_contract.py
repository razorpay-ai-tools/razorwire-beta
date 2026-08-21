"""Tests for the render contract — the file the renderer reads.

The renderer rejects a malformed ``storyboard.json`` loudly, so every one of its
seven rules is worth a test on our side. A rejection there costs a whole job; a
failure here costs a red test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import render_contract as rc
from app import storyboard as internal

FIXTURE = Path(__file__).resolve().parents[2] / "src/lib/fixtures/otm-rearch.storyboard.json"


@pytest.fixture
def sb() -> internal.Storyboard:
    return internal.validate_storyboard(json.loads(FIXTURE.read_text()), stage="script")


@pytest.fixture
def wire(sb: internal.Storyboard) -> dict:
    payload, _ = rc.emit(sb)
    return payload


# ------------------------------------------------------------------ shape and naming


def test_emits_the_renderers_shape(wire: dict) -> None:
    assert wire["schemaVersion"] == rc.SCHEMA_VERSION
    assert set(wire) <= {"schemaVersion", "title", "subtitle", "style", "scenes"}
    assert wire["title"]
    assert wire["style"]["aspectRatio"] == "9:16"
    assert wire["style"]["fps"] == 30
    assert wire["style"]["palette"]


def test_every_scene_has_id_narration_and_exactly_one_visual(wire: dict) -> None:
    for scene in wire["scenes"]:
        assert set(scene) <= {"id", "narration", "visual", "onScreenText", "motion"}
        assert scene["id"] and scene["narration"]
        assert "kind" in scene["visual"]


def test_scene_ids_are_unique_and_stable(wire: dict) -> None:
    ids = [scene["id"] for scene in wire["scenes"]]
    assert ids == [f"s{i + 1}" for i in range(len(ids))]
    assert len(set(ids)) == len(ids)


def test_visual_kinds_are_renamed_to_the_renderers_vocabulary(wire: dict) -> None:
    kinds = {scene["visual"]["kind"] for scene in wire["scenes"]}
    # `compare` and `lang` are our internal names; the renderer never sees them
    assert "compare" not in kinds
    assert kinds <= {"title", "diagram", "bullets", "comparison", "code", "outro"}
    for scene in wire["scenes"]:
        assert "lang" not in scene["visual"]
        assert "sub" not in scene["visual"]
        assert "cta" not in scene["visual"]


def test_internal_only_fields_never_reach_the_renderer(wire: dict) -> None:
    """`cite` and `broll` are ours; `durationMs` the renderer computes from real audio."""
    blob = json.dumps(wire)
    for ours in ("cite", "broll", "clipId", "durationMs", "mood"):
        assert ours not in blob, f"{ours} leaked into the render file"


def test_subtitle_is_taken_from_the_title_scene_not_invented(
    sb: internal.Storyboard, wire: dict
) -> None:
    expected = next(
        (s.sub for s in sb.scenes if isinstance(s, internal.TitleScene) and s.sub), None
    )
    assert wire.get("subtitle") == expected


def test_projection_round_trips_through_the_renderers_validator(wire: dict) -> None:
    assert rc.validate_render_storyboard(wire).title == wire["title"]


def test_comparison_items_are_reported_not_dropped_silently(sb: internal.Storyboard) -> None:
    """Their `comparison` has no slot for per-side items, so the loss must be visible."""
    has_compare = any(s.type == "compare" for s in sb.scenes)
    _, warnings = rc.emit(sb)
    assert bool(warnings) is has_compare
    if has_compare:
        assert "comparison carries no items" in warnings[0]


# ----------------------------------------------------------------------- their rules


def _minimal(**overrides) -> dict:
    scenes = [
        {"id": "s1", "narration": "A short line.", "visual": {"kind": "title", "heading": "Hi"}},
        {
            "id": "s2",
            "narration": "Another short line.",
            "visual": {"kind": "diagram", "mermaid": "graph LR\n A[One] --> B[Two]"},
        },
        {
            "id": "s3",
            "narration": "A third short line.",
            "visual": {"kind": "bullets", "bullets": ["one", "two"]},
        },
        {"id": "s4", "narration": "A closing line.", "visual": {"kind": "outro"}},
    ]
    return {"schemaVersion": "1.0.0", "title": "A title", "scenes": scenes, **overrides}


def test_the_minimal_file_is_valid() -> None:
    assert rc.validate_render_storyboard(_minimal()).scenes[0].id == "s1"


@pytest.mark.parametrize("count", [3, 7])
def test_rule_1_scene_count_must_be_4_to_6(count: int) -> None:
    base = _minimal()
    scene = base["scenes"][0]
    base["scenes"] = [{**scene, "id": f"s{i}"} for i in range(count)]
    with pytest.raises(rc.RenderContractInvalid):
        rc.validate_render_storyboard(base)


@pytest.mark.parametrize(
    "narration",
    [
        "One sentence. Two sentences. Three sentences. Four is too many.",
        "Read it at https://aidocs.razorpay.com/app/d/doc_x.",
        "This has **markdown** in it.",
        "This one is cheerful 🎉.",
    ],
    ids=["four-sentences", "url", "markdown", "emoji"],
)
def test_rule_2_narration_must_be_plain_spoken_text(narration: str) -> None:
    base = _minimal()
    base["scenes"][0]["narration"] = narration
    with pytest.raises(rc.RenderContractInvalid):
        rc.validate_render_storyboard(base)


def test_rule_3_an_unknown_visual_kind_is_rejected() -> None:
    base = _minimal()
    base["scenes"][0]["visual"] = {"kind": "carousel", "heading": "nope"}
    with pytest.raises(rc.RenderContractInvalid):
        rc.validate_render_storyboard(base)


@pytest.mark.parametrize(
    "mermaid",
    [
        "A[One] --> B[Two]",                          # no graph header
        "graph BT\n A[One] --> B[Two]",               # direction the renderer will not take
        "graph LR\n A[Only]",                         # one node, malformed
        "graph LR\n" + "\n".join(f" N{i} --> N{i + 1}" for i in range(8)),  # over the node cap
    ],
    ids=["no-header", "bad-direction", "one-node", "too-many-nodes"],
)
def test_rule_4_mermaid_must_be_valid_and_simple(mermaid: str) -> None:
    base = _minimal()
    base["scenes"][1]["visual"]["mermaid"] = mermaid
    with pytest.raises(rc.RenderContractInvalid):
        rc.validate_render_storyboard(base)


@pytest.mark.parametrize("direction", ["LR", "TB", "TD"])
def test_rule_4_accepts_every_direction_we_promised(direction: str) -> None:
    base = _minimal()
    base["scenes"][1]["visual"]["mermaid"] = f"graph {direction}\n A[One] --> B[Two]"
    rc.validate_render_storyboard(base)


def test_rule_6_duplicate_scene_ids_are_rejected() -> None:
    base = _minimal()
    base["scenes"][1]["id"] = base["scenes"][0]["id"]
    with pytest.raises(rc.RenderContractInvalid) as raised:
        rc.validate_render_storyboard(base)
    assert any("duplicate" in error for error in raised.value.errors)


def test_validation_reports_every_problem_not_just_the_first() -> None:
    base = _minimal()
    base["scenes"][0]["narration"] = "One. Two. Three. Four."
    base["scenes"][2]["narration"] = "Also. Far. Too. Long. Indeed."
    with pytest.raises(rc.RenderContractInvalid) as raised:
        rc.validate_render_storyboard(base)
    assert len(raised.value.errors) >= 2


# ---------------------------------------------------------- limits agree across modules


def test_the_two_modules_cannot_disagree_about_limits() -> None:
    """One source of truth. If these drift, generation can emit an unprojectable file."""
    assert (rc.MIN_SCENES, rc.MAX_SCENES) == (internal.MIN_SCENES, internal.MAX_SCENES)


def test_internal_validator_enforces_the_renderers_limits() -> None:
    """Anything the renderer rejects must be caught at generation, not at the boundary."""
    fields = internal.Storyboard.model_fields["scenes"].metadata
    limits = {type(m).__name__: m for m in fields}
    assert limits["MinLen"].min_length == rc.MIN_SCENES
    assert limits["MaxLen"].max_length == rc.MAX_SCENES


# ------------------------------------------------------------------------- endpoints
# The handoff route. Kept here rather than in test_api so the whole render contract
# lives in one file.

import os  # noqa: E402

os.environ.setdefault("DEV_AUTH_EMAIL", "tester@razorpay.com")
os.environ["DATABASE_URL"] = "sqlite://"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.models import init_db  # noqa: E402


@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c


def test_post_storyboard_json_serves_the_render_contract(client) -> None:
    created = client.post(
        "/posts",
        json={
            "title": "OTM rearch",
            "kind": "generated",
            "tags": ["upi"],
            "storyboard": json.loads(FIXTURE.read_text()),
        },
    )
    assert created.status_code == 201, created.text

    served = client.get(f"/posts/{created.json()['id']}/storyboard.json")
    assert served.status_code == 200, served.text
    payload = served.json()

    # it is their file, and it survives their validator
    assert payload["schemaVersion"] == rc.SCHEMA_VERSION
    rc.validate_render_storyboard(payload)
    assert "cite" not in json.dumps(payload)


def test_storyboard_json_404s_for_a_clip_post(client) -> None:
    created = client.post(
        "/posts",
        json={"title": "Design crit", "kind": "clip", "tags": ["culture"], "mediaUrl": "/m/a.mp4"},
    )
    assert created.status_code == 201, created.text
    assert client.get(f"/posts/{created.json()['id']}/storyboard.json").status_code == 404


def test_storyboard_json_404s_for_an_unknown_post(client) -> None:
    assert client.get("/posts/post_missing/storyboard.json").status_code == 404


# --------------------------------------------------------------- the on-disk handoff
# Steps 3 and 4 of the architecture run on the same box, so the seam is a file.


def test_write_bundle_puts_the_file_where_the_voice_stage_looks(
    sb: internal.Storyboard, tmp_path, monkeypatch
) -> None:
    from app.config import settings as live

    monkeypatch.setattr(live, "work_dir", str(tmp_path))
    path = rc.write_bundle("job_abc", sb)

    assert path == tmp_path / "job_abc" / "storyboard.json"
    written = json.loads(path.read_text())
    rc.validate_render_storyboard(written)
    assert written["schemaVersion"] == rc.SCHEMA_VERSION


def test_the_work_dir_is_not_the_publicly_served_media_dir() -> None:
    """Intermediate work derived from internal documents must not be reachable by URL."""
    from app.config import settings as live

    assert live.work_dir != live.media_dir


# --------------------------------------------------------- the two shapes must not mix
# The trap this guards: step 5a screenshots our OWN web app, whose scene components
# dispatch on internal `scene.type`. Step 6 then writes Post(storyboard=...). If the
# render contract's `visual.kind` shape ever lands in that column, every scene falls
# through to UnsupportedScene and `docHref` returns null — a feed of blank frames with
# nothing raising an error anywhere.


def test_the_render_file_is_not_a_valid_internal_storyboard(wire: dict) -> None:
    """Storing storyboard.json in Post.storyboard must fail loudly, not silently."""
    with pytest.raises(internal.StoryboardInvalid):
        internal.validate_storyboard(wire, stage="script")


def test_an_internal_storyboard_is_not_a_valid_render_file(sb: internal.Storyboard) -> None:
    """And the reverse, so neither can be mistaken for the other."""
    from app.pipeline import storyboard_to_json

    with pytest.raises(rc.RenderContractInvalid):
        rc.validate_render_storyboard(storyboard_to_json(sb))


def test_the_two_shapes_are_distinguishable_by_a_single_field(
    sb: internal.Storyboard, wire: dict
) -> None:
    """`type` vs `visual.kind` — enough for a renderer to assert which it was handed."""
    from app.pipeline import storyboard_to_json

    internal_json = storyboard_to_json(sb)
    assert all("type" in scene and "visual" not in scene for scene in internal_json["scenes"])
    assert all("visual" in scene and "type" not in scene for scene in wire["scenes"])
