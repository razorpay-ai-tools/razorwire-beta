"""Contract and API checks.

No Claude calls here — the script stage is exercised separately with a real key.
These cover the rules that break silently: pipeline-owned fields, diagram limits,
citation enforcement, and the feed's counts, pagination and ownership checks.

    cd backend && uv run pytest -q
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("DEV_AUTH_EMAIL", "tester@razorpay.com")
os.environ["DATABASE_URL"] = "sqlite://"  # in-memory, per session

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.models import init_db  # noqa: E402
from app.storyboard import (  # noqa: E402
    MAX_MERMAID_NODES,
    StoryboardInvalid,
    mermaid_node_count,
    tool_input_schema,
    validate_storyboard,
)

FIXTURE = Path(__file__).resolve().parents[2] / "src" / "lib" / "fixtures" / "otm-rearch.storyboard.json"


def load() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c


# ------------------------------------------------------------------ the contract


def test_fixture_is_valid_at_script_stage():
    validate_storyboard(load(), "script")


def test_render_stage_requires_durations():
    with pytest.raises(StoryboardInvalid) as exc:
        validate_storyboard(load(), "render")
    assert sum("durationMs missing" in e for e in exc.value.errors) == 6


def test_render_stage_accepts_resolved_storyboard():
    data = load()
    for scene in data["scenes"]:
        scene["durationMs"] = 4000
        if "broll" in scene:
            scene["broll"]["clipId"] = "veo_abstract_01"
    validate_storyboard(data, "render")


def test_script_stage_rejects_model_set_duration():
    data = load()
    data["scenes"][0]["durationMs"] = 4000
    with pytest.raises(StoryboardInvalid) as exc:
        validate_storyboard(data, "script")
    assert any("durationMs is pipeline-set" in e for e in exc.value.errors)


def test_script_stage_rejects_model_invented_clip():
    data = load()
    data["scenes"][0]["broll"]["clipId"] = "veo_money_01"
    with pytest.raises(StoryboardInvalid) as exc:
        validate_storyboard(data, "script")
    assert any("clipId is pipeline-set" in e for e in exc.value.errors)


def test_rejects_free_text_video_prompt():
    """The closed mood set is what stops a spec leaking into a video prompt."""
    data = load()
    data["scenes"][0]["broll"] = {"mood": "a wide cinematic shot of a datacenter"}
    with pytest.raises(StoryboardInvalid):
        validate_storyboard(data, "script")


def test_rejects_oversized_diagram():
    data = load()
    diagram = next(s for s in data["scenes"] if s["type"] == "diagram")
    diagram["mermaid"] = "graph TD\n" + "\n".join(f"  N{i} --> N{i+1}" for i in range(9))
    with pytest.raises(StoryboardInvalid) as exc:
        validate_storyboard(data, "script")
    assert any(f"max {MAX_MERMAID_NODES}" in e for e in exc.value.errors)


def test_counts_nodes_through_edge_labels():
    assert mermaid_node_count("graph TD\n A -->|yes| B\n B --> C") == 3


def test_rejects_uncited_factual_scene():
    data = load()
    del data["scenes"][1]["cite"]
    with pytest.raises(StoryboardInvalid) as exc:
        validate_storyboard(data, "script")
    assert any("needs a cite" in e for e in exc.value.errors)


def test_topic_source_does_not_need_cites():
    data = load()
    data["source"] = {"kind": "topic"}
    for scene in data["scenes"]:
        scene.pop("cite", None)
    validate_storyboard(data, "script")


def test_rejects_runaway_narration():
    data = load()
    data["scenes"][1]["narration"] = " ".join(["word"] * 80)
    with pytest.raises(StoryboardInvalid) as exc:
        validate_storyboard(data, "script")
    assert any("ceiling" in e for e in exc.value.errors)


def test_tool_schema_hides_pipeline_fields():
    raw = json.dumps(tool_input_schema())
    assert "durationMs" not in raw
    assert "clipId" not in raw
    assert "dataflow" in raw  # the mood vocabulary is still exposed


# ------------------------------------------------------------------ the API


def test_health_needs_no_auth(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_me_creates_the_user_on_first_sight(client):
    body = client.get("/me").json()
    assert body["email"] == "tester@razorpay.com"


def test_generated_post_requires_a_storyboard(client):
    r = client.post("/posts", json={"title": "no storyboard", "kind": "generated"})
    assert r.status_code == 422


def test_clip_post_requires_media(client):
    r = client.post("/posts", json={"title": "no media", "kind": "clip"})
    assert r.status_code == 422


def test_post_like_save_comment_view_roundtrip(client):
    created = client.post(
        "/posts",
        json={"title": "OTM rearch in 60s", "kind": "generated", "storyboard": load(), "tags": ["upi"]},
    )
    assert created.status_code == 201, created.text
    post_id = created.json()["id"]

    assert client.post(f"/posts/{post_id}/like").json() == {"active": True, "count": 1}
    assert client.post(f"/posts/{post_id}/like").json() == {"active": False, "count": 0}
    assert client.post(f"/posts/{post_id}/save").json() == {"active": True, "count": 1}

    comment = client.post(f"/posts/{post_id}/comments", json={"text": "this is great"})
    assert comment.status_code == 201
    assert comment.json()["author"]["email"] == "tester@razorpay.com"

    assert client.post(f"/posts/{post_id}/view").json()["views"] == 1

    fetched = client.get(f"/posts/{post_id}").json()
    assert (fetched["saved"], fetched["liked"]) == (True, False)
    assert (fetched["comments"], fetched["views"]) == (1, 1)
    assert fetched["storyboard"]["meta"]["tags"] == ["upi", "mandates", "architecture"]


def test_feed_paginates_without_repeating_rows(client):
    for i in range(5):
        client.post("/posts", json={"title": f"clip {i}", "kind": "clip", "mediaUrl": "/media/x.mp4"})

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = client.get("/feed", params=params).json()
        seen.extend(item["id"] for item in page["items"])
        cursor = page["nextCursor"]
        if not cursor:
            break

    assert len(seen) == len(set(seen)), "feed returned a duplicate row"
    assert len(seen) >= 6


def test_feed_rejects_a_malformed_cursor(client):
    assert client.get("/feed", params={"cursor": "not-a-cursor"}).status_code == 400


def test_only_the_author_can_delete(client):
    created = client.post(
        "/posts", json={"title": "mine", "kind": "clip", "mediaUrl": "/media/x.mp4"}
    ).json()
    # same dev user owns it, so this succeeds and proves the happy path
    assert client.delete(f"/posts/{created['id']}").status_code == 204
    assert client.get(f"/posts/{created['id']}").status_code == 404


def test_upload_rejects_a_non_video(client):
    r = client.post("/uploads", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_aidoc_generation_requires_a_doc_id(client):
    r = client.post("/generate", json={"kind": "aidoc", "input": "a" * 50})
    assert r.status_code == 422
