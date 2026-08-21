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

# Environment isolation lives in conftest.py, which pytest imports before any
# test module — overrides here were import-order roulette.

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


def test_script_stage_rejects_model_set_audio_url():
    data = load()
    data["scenes"][0]["audioUrl"] = "/media/job_x_scene0.m4a"
    with pytest.raises(StoryboardInvalid) as exc:
        validate_storyboard(data, "script")
    assert any("audioUrl is pipeline-set" in e for e in exc.value.errors)


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
    # Blow the spoken ceiling while every scene stays under its own 420-char cap:
    # ~70 words per scene, all scenes, always exceeds the total whatever the constant.
    for scene in data["scenes"]:
        scene["narration"] = " ".join(["word"] * 70)
    with pytest.raises(StoryboardInvalid) as exc:
        validate_storyboard(data, "script")
    assert any("ceiling" in e for e in exc.value.errors)


def test_tool_schema_hides_pipeline_fields():
    raw = json.dumps(tool_input_schema())
    assert "durationMs" not in raw
    assert "clipId" not in raw
    assert "audioUrl" not in raw
    assert "dataflow" in raw  # the mood vocabulary is still exposed


# ------------------------------------------------------------------ the API


def test_health_needs_no_auth(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    # The web app gates the video option on this, so it has to be a real answer about
    # this machine rather than an optimistic constant.
    assert isinstance(body["render"], bool)
    assert body["render"] is (body["renderMissing"] == [])


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


def test_second_dev_user_reaction_is_visible_to_first_user(client):
    user_1 = {"x-dev-email": "viewer-one@razorpay.com"}
    user_2 = {"x-dev-email": "viewer-two@razorpay.com"}
    created = client.post(
        "/posts",
        headers=user_1,
        json={"title": "shared state", "kind": "clip", "mediaUrl": "/media/x.mp4"},
    ).json()

    assert client.post(f"/posts/{created['id']}/like", headers=user_2).json() == {"active": True, "count": 1}
    comment = client.post(
        f"/posts/{created['id']}/comments",
        headers=user_2,
        json={"text": "visible across users"},
    ).json()

    fetched = client.get(f"/posts/{created['id']}", headers=user_1).json()
    assert comment["author"]["email"] == "viewer-two@razorpay.com"
    assert fetched["likes"] == 1
    assert fetched["comments"] == 1
    assert fetched["liked"] is False


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


def test_upload_returns_media_metadata(client):
    r = client.post("/uploads", files={"file": ("clip.mp4", b"not really video", "video/mp4")})
    assert r.status_code == 201
    body = r.json()
    # The local fallback serves out of /media, but the URL leaves here absolute: the web
    # app is on another origin, where a relative path 404s. See `_absolute_media` and
    # `test_upload_returns_an_absolute_url`, which pins the same rule from the other side.
    assert "/media/" in body["mediaUrl"]
    assert body["mediaUrl"].startswith("http://")
    assert body["storageKey"].startswith("local/")


def test_upload_rejects_oversized_video(client):
    r = client.post("/uploads", files={"file": ("clip.mp4", b"x" * (51 * 1024 * 1024), "video/mp4")})
    assert r.status_code == 413


def test_aidoc_generation_requires_a_doc_id(client):
    r = client.post("/generate", json={"kind": "aidoc", "input": "a" * 50})
    assert r.status_code == 422


# ------------------------------------------------------------------ channels & profiles


def test_channel_follow_drives_the_following_feed(client):
    """The one path the feature rests on: create, unfollow, post, filter."""
    followed = client.post("/channels", json={"name": "Payments Core", "description": "money path"})
    assert followed.status_code == 201
    body = followed.json()
    # the creator follows their own channel, else it is missing from the feed they read
    assert (body["slug"], body["following"], body["followers"]) == ("payments-core", True, 1)

    ignored = client.post("/channels", json={"name": "Culture"}).json()
    assert client.post(f"/channels/{ignored['slug']}/follow").json() == {
        "active": False,
        "count": 0,
    }

    for channel in (body, ignored):
        created = client.post(
            "/posts",
            json={
                "title": f"clip in {channel['slug']}",
                "kind": "clip",
                "mediaUrl": "/media/x.mp4",
                "channelId": channel["id"],
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["channel"]["slug"] == channel["slug"]

    def titles(**params):
        return [item["title"] for item in client.get("/feed", params=params).json()["items"]]

    assert titles(scope="following") == ["clip in payments-core"]
    assert titles(channel="culture") == ["clip in culture"]
    assert set(titles()) >= {"clip in payments-core", "clip in culture"}

    listed = {c["slug"]: c for c in client.get("/channels").json()}
    assert (listed["payments-core"]["posts"], listed["culture"]["posts"]) == (1, 1)
    assert [c["slug"] for c in client.get("/channels", params={"following": True}).json()] == [
        "payments-core"
    ]


def test_duplicate_channel_name_is_a_conflict(client):
    assert client.post("/channels", json={"name": "Architecture"}).status_code == 201
    assert client.post("/channels", json={"name": "architecture"}).status_code == 409
    assert client.post("/channels", json={"name": "!!!"}).status_code == 422


def test_post_rejects_an_unknown_channel(client):
    r = client.post(
        "/posts",
        json={"title": "orphan", "kind": "clip", "mediaUrl": "/media/x.mp4", "channelId": "chn_nope"},
    )
    assert r.status_code == 422


def test_profile_reports_posts_and_followed_channels(client):
    me = client.patch("/me", json={"name": "Tester", "bio": "writes specs"}).json()
    assert (me["name"], me["bio"]) == ("Tester", "writes specs")

    channel = client.post("/channels", json={"name": "Onboarding"}).json()
    client.post(
        "/posts",
        json={
            "title": "profile post",
            "kind": "clip",
            "mediaUrl": "/media/x.mp4",
            "channelId": channel["id"],
        },
    )

    profile = client.get(f"/users/{me['id']}").json()
    assert profile["user"]["bio"] == "writes specs"
    assert profile["posts"] >= 1
    assert "onboarding" in {c["slug"] for c in profile["channels"]}
    assert client.get("/users/usr_missing").status_code == 404
    assert "profile post" in [
        item["title"] for item in client.get("/feed", params={"author": me["id"]}).json()["items"]
    ]


def test_unknown_channel_slug_is_a_404(client):
    assert client.get("/channels/nope").status_code == 404
    assert client.get("/feed", params={"channel": "nope"}).status_code == 404


# ------------------------------------------------------------------ aidocs ingest

from app.aidocs import AidocsUnavailable, fetch_doc, parse_doc_html  # noqa: E402

_DOC_HTML = """
<html><head><title>OTM Rearch Spec</title>
<style>.field { color: #fff } h2 { font-size: 20px }</style>
<script>var x = "not prose";</script></head>
<body>
  <h1>OTM / SBMD Rearch</h1>
  <p>One-time mandates move off the monolith.</p>
  <h2>Section 2 - Problem Statement</h2>
  <p>Rules live in two places.</p>
  <ul><li>Duplicated expiry validation</li><li>No owner for block_fund</li></ul>
  <h2>Section 4 - Proposed Architecture</h2>
  <p>pg-router routes into payments-mandate.</p>
</body></html>
"""


def test_parses_sections_and_title():
    doc = parse_doc_html("doc_abc123", _DOC_HTML)
    assert doc.title == "OTM Rearch Spec"
    headings = [s.heading for s in doc.sections]
    assert "Section 2 - Problem Statement" in headings
    assert "Section 4 - Proposed Architecture" in headings


def test_drops_style_and_script_content():
    """CSS and JS reaching the model would waste tokens and invent nonsense citations."""
    text = parse_doc_html("doc_abc123", _DOC_HTML).to_prompt_text()
    assert "font-size" not in text
    assert "not prose" not in text
    assert "block_fund" in text  # real prose survives


def test_prompt_text_keeps_headings_so_claude_can_cite():
    text = parse_doc_html("doc_abc123", _DOC_HTML).to_prompt_text()
    assert "## Section 4 - Proposed Architecture" in text
    assert text.index("Section 2") < text.index("Section 4")  # document order


def test_html_without_headings_still_yields_content():
    doc = parse_doc_html("doc_x1", "<html><body><p>Just a paragraph.</p></body></html>")
    assert doc.sections
    assert "Just a paragraph." in doc.to_prompt_text()


def test_rejects_a_malformed_doc_id_before_shelling_out():
    for bad in ("doc_../../etc/passwd", "notadoc", "doc_with-dashes", "doc_"):
        with pytest.raises(AidocsUnavailable):
            fetch_doc(bad)


def test_doc_url_is_derived_from_the_id():
    assert parse_doc_html("doc_r523noskel555f7f", _DOC_HTML).url.endswith("/doc_r523noskel555f7f")


def test_topic_generation_still_requires_input(client):
    assert client.post("/generate", json={"kind": "topic", "input": "hi"}).status_code == 422


def test_aidoc_generation_no_longer_requires_pasted_input(client):
    """The backend fetches the document, so `input` is optional for the aidoc path."""
    r = client.post("/generate", json={"kind": "aidoc", "docId": "doc_sample123"})
    assert r.status_code == 202, r.text


def test_heading_does_not_absorb_a_nested_caption():
    """`div.field-title > span` is how real aidocs mark sections; naive concatenation
    turns "Problem" into "ProblemPain, users, cost" and citations stop matching."""
    html = '<div class="field-title">Problem<span>Pain and users</span></div><p>Body text here.</p>'
    doc = parse_doc_html("doc_x", html)
    headings = [s.heading for s in doc.sections]
    assert "Problem" in headings, headings


def test_heading_with_no_prose_is_not_offered_as_a_section():
    """A table header cell is not a citable section, and offering it invites a false cite."""
    html = "<table><tr><th>Dimension</th><th>Detail</th></tr>" "<tr><td>Real prose lives here.</td></tr></table>"
    doc = parse_doc_html("doc_x", html)
    assert all(s.text for s in doc.sections)
    assert "Dimension" not in [s.heading for s in doc.sections]


def test_non_h_headings_are_detected():
    """Relying on <h*> alone collapsed a 10-section document into one blob."""
    html = (
        '<div class="field-title">Alpha</div><p>First body.</p>'
        '<div class="field-title">Beta</div><p>Second body.</p>'
    )
    doc = parse_doc_html("doc_x", html)
    assert [s.heading for s in doc.sections] == ["Alpha", "Beta"]
    assert doc.is_structured


def test_unstructured_document_is_flagged():
    doc = parse_doc_html("doc_x", f"<html><body><p>{'word ' * 3000}</p></body></html>")
    assert not doc.is_structured


def test_prompt_text_is_not_truncated():
    """A per-section cap silently discarded two thirds of a real document."""
    body = "sentence. " * 900
    doc = parse_doc_html("doc_x", f"<h2>Big Section</h2><p>{body}</p>")
    assert len(doc.to_prompt_text()) > 8000


# ------------------------------------------------------------------ the model call

from app.config import settings  # noqa: E402
from app.pipeline import run_script_stage  # noqa: E402


def test_script_stage_calls_the_gateway_with_the_configured_model(monkeypatch):
    """Where the call goes, and as what.

    The gateway serves Anthropic's `/v1/messages` shape for every model it routes, which
    is the only reason the `anthropic` SDK can drive `glm-5p2`. Nothing else asserts that,
    so a base URL or model rename would otherwise be found by a failed demo.
    """
    seen: dict = {}

    class _FakeMessages:
        def create(self, **kwargs):
            seen.update(kwargs)
            raise RuntimeError("stop here — the wiring is what is under test")

    class _FakeAnthropic:
        def __init__(self, **kwargs):
            seen["client"] = kwargs
            self.messages = _FakeMessages()

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)
    monkeypatch.setattr(settings, "litellm_api_key", "sk-test-gateway")

    with pytest.raises(RuntimeError, match="stop here"):
        run_script_stage(kind="topic", text="how mandates are debited")

    assert seen["client"]["base_url"] == "https://llm-gateway.razorpay.com"
    assert seen["client"]["api_key"] == "sk-test-gateway"
    assert seen["model"] == "glm-5p2"
    # The forced tool call is the contract; a model that free-texts instead is useless.
    assert seen["tool_choice"] == {"type": "tool", "name": "emit_storyboard"}


def test_script_stage_refuses_to_run_without_a_key(monkeypatch):
    monkeypatch.setattr(settings, "litellm_api_key", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(RuntimeError, match="LITELLM_API_KEY"):
        run_script_stage(kind="topic", text="anything")


def test_a_direct_anthropic_key_still_works(monkeypatch):
    """Whoever holds a real Anthropic key should not be forced through the gateway."""
    monkeypatch.setattr(settings, "litellm_api_key", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-direct")
    assert settings.llm_api_key == "sk-ant-direct"


# ------------------------------------------------------------------ media URLs

def test_media_url_is_absolute(client):
    """A relative /media path resolves against the WEB app, where nothing is mounted."""
    created = client.post(
        "/posts", json={"title": "clip abs", "kind": "clip", "mediaUrl": "/media/x.mp4"}
    ).json()
    assert created["mediaUrl"].startswith("http://"), created["mediaUrl"]
    assert created["mediaUrl"].endswith("/media/x.mp4")


def test_absolute_media_url_is_left_alone(client):
    created = client.post(
        "/posts",
        json={"title": "clip already abs", "kind": "clip", "mediaUrl": "https://cdn.example/x.mp4"},
    ).json()
    assert created["mediaUrl"] == "https://cdn.example/x.mp4"


def test_upload_returns_an_absolute_url(client):
    r = client.post("/uploads", files={"file": ("clip.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")})
    assert r.status_code == 201, r.text
    assert r.json()["mediaUrl"].startswith("http://")


# ------------------------------------------------------- the no-tool-call fallback

from types import SimpleNamespace  # noqa: E402

from app.pipeline import _json_from_text  # noqa: E402


def _text_reply(text: str):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def test_storyboard_is_recovered_from_a_text_reply():
    """Forced tool choice is advisory once a non-Anthropic model is behind the gateway.

    glm-5p2 answers with the storyboard as JSON in a text block a good fraction of the
    time, which failed all three attempts and burned three paid calls for nothing. Each
    case below is a shape a model actually produced.
    """
    # Prose that balances a brace before the real object begins.
    recovered = _json_from_text(
        _text_reply('Here is the storyboard {as requested}: {"meta":{"title":"t"},"scenes":[1]}')
    )
    assert recovered == {"meta": {"title": "t"}, "scenes": [1]}

    # Fenced, with a brace inside a string inside the object.
    assert _json_from_text(_text_reply('```json\n{"meta":{},"scenes":[{"x":"}"}]}\n```')) == {
        "meta": {},
        "scenes": [{"x": "}"}],
    }

    # Mermaid puts braces in strings; a regex would cut the object short here.
    assert _json_from_text(_text_reply('{"scenes":[],"mermaid":"graph TD\\n A[x{y}] --> B"}'))["mermaid"]

    # And nothing is invented when there is nothing to find.
    assert _json_from_text(_text_reply("I cannot do that.")) is None
    assert _json_from_text(_text_reply('{"meta":{"title"')) is None
    assert _json_from_text(_text_reply("")) is None


def test_text_only_reply_still_produces_a_storyboard(monkeypatch):
    """End to end through `run_script_stage`: no tool call, valid JSON, real storyboard."""
    payload = json.loads(FIXTURE.read_text())
    payload.pop("source", None)  # the pipeline owns this

    class _FakeMessages:
        def create(self, **kwargs):
            return _text_reply("Sure, here it is:\n" + json.dumps(payload))

    class _FakeAnthropic:
        def __init__(self, **kwargs):
            self.messages = _FakeMessages()

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)
    monkeypatch.setattr(settings, "litellm_api_key", "sk-test")

    sb = run_script_stage(kind="aidoc", text="anything", doc_id="doc_abc123")
    assert sb.scenes, "a text-shaped reply must still yield scenes"
    assert sb.source.doc_id == "doc_abc123", "the pipeline sets source, not the model"


# ------------------------------------------------------- the plan stage (multi-video)

from app.pipeline import (  # noqa: E402
    _MIN_CHARS_TO_SPLIT,
    _REDUCE_ABOVE_CHARS,
    run_plan_stage,
    run_reduce_stage,
    validate_parts,
)


def _fake_llm(monkeypatch, response):
    """Install a fake Anthropic client whose one call returns (or raises via) `response`."""

    class _FakeMessages:
        def create(self, **kwargs):
            return response() if callable(response) else response

    class _FakeAnthropic:
        def __init__(self, **kwargs):
            self.messages = _FakeMessages()

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)
    monkeypatch.setattr(settings, "litellm_api_key", "sk-test")


def test_a_source_that_fits_is_never_sent_to_the_reduce_stage():
    """The reduce call is only worth its money and its minute on an over-long source."""

    def fail_if_called():
        raise AssertionError("run_reduce_stage must not call the model for a short source")

    _fake_llm(pytest.MonkeyPatch(), fail_if_called)
    short = "x" * 100
    assert run_reduce_stage(text=short) == short


def test_an_over_long_source_is_condensed(monkeypatch):
    condensed = "## Section 4 — Proposed Architecture\n" + ("real prose about the flow. " * 40)
    _fake_llm(monkeypatch, _text_reply(condensed))
    out = run_reduce_stage(text="y" * (_REDUCE_ABOVE_CHARS + 1), doc_title="Deep Dive")
    assert out == condensed.strip()  # the reply is stripped, hence not `condensed` itself
    assert len(out) < _REDUCE_ABOVE_CHARS
    assert "Section 4 — Proposed Architecture" in out  # headings survive, so cites resolve


@pytest.mark.parametrize(
    ("label", "response"),
    [
        ("the call blows up", lambda: (_ for _ in ()).throw(RuntimeError("gateway down"))),
        ("it comes back empty", _text_reply("")),
        ("it returns a stub", _text_reply("too short")),
    ],
)
def test_reduce_failures_fall_back_to_the_original_source(monkeypatch, label, response):
    """Condensing is an optimisation. Losing the document to it would be a bug."""
    _fake_llm(monkeypatch, response)
    original = "z" * (_REDUCE_ABOVE_CHARS + 1)
    assert run_reduce_stage(text=original) == original, label


def test_plan_validation_accepts_one_to_three_titled_parts():
    two = {"parts": [{"title": " The problem ", "focus": "why"}, {"title": "The fix", "focus": "how"}]}
    assert validate_parts(two) == [
        {"title": "The problem", "focus": "why"},
        {"title": "The fix", "focus": "how"},
    ]


def test_plan_validation_rejects_every_unusable_shape():
    for bad in (
        None,
        "three parts please",
        {},
        {"parts": []},  # zero parts
        {"parts": [{"title": f"t{i}", "focus": ""} for i in range(4)]},  # too many
        {"parts": [{"title": "  ", "focus": "x"}]},  # blank title
        {"parts": [{"focus": "no title at all"}]},
        {"parts": [{"title": "ok", "focus": ""}, "not an object"]},
    ):
        assert validate_parts(bad) is None, bad


#: Long enough that `run_plan_stage` actually asks the model. Below
#: `_MIN_CHARS_TO_SPLIT` it answers "one part" without a round-trip, so a short
#: string here would pass these tests without exercising the code they name.
_SPLITTABLE = "word " * (_MIN_CHARS_TO_SPLIT // 4)


def test_plan_stage_falls_back_to_a_single_part_on_garbage(monkeypatch):
    """Planning misbehaving must never fail the job — it collapses to one part."""
    _fake_llm(monkeypatch, _text_reply("I would rather chat than call tools."))
    assert run_plan_stage(kind="aidoc", text=_SPLITTABLE, doc_title="OTM Rearch") == [
        {"title": "OTM Rearch", "focus": ""}
    ]


def test_plan_stage_falls_back_when_the_call_blows_up(monkeypatch):
    def boom():
        raise RuntimeError("gateway down")

    _fake_llm(monkeypatch, boom)
    assert len(run_plan_stage(kind="aidoc", text=_SPLITTABLE)) == 1


def test_plan_stage_reads_a_tool_call(monkeypatch):
    plan = {"parts": [{"title": "A", "focus": "f"}, {"title": "B", "focus": "g"}]}
    _fake_llm(monkeypatch, SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=plan, id="tu_1")]))
    assert [p["title"] for p in run_plan_stage(kind="aidoc", text=_SPLITTABLE)] == ["A", "B"]


def test_a_short_source_is_one_part_without_asking_the_model(monkeypatch):
    """The plan call is skipped entirely below the threshold — it cannot be answered
    two ways, and it was a paid round-trip on the common case."""

    def fail_if_called():
        raise AssertionError("run_plan_stage must not call the model for a short source")

    _fake_llm(monkeypatch, fail_if_called)
    assert run_plan_stage(kind="aidoc", text="too short to split", doc_title="T") == [
        {"title": "T", "focus": ""}
    ]


def test_single_part_leaves_the_title_unsuffixed(monkeypatch):
    payload = load()
    payload.pop("source", None)
    _fake_llm(monkeypatch, _text_reply(json.dumps(payload)))
    sb = run_script_stage(kind="aidoc", text="anything", doc_id="doc_abc123")
    assert "Part" not in sb.meta.title


def test_multi_part_titles_carry_the_part_suffix(monkeypatch):
    payload = load()
    payload.pop("source", None)
    _fake_llm(monkeypatch, _text_reply(json.dumps(payload)))
    sb = run_script_stage(
        kind="aidoc",
        text="anything",
        doc_id="doc_abc123",
        part={"title": "The problem", "focus": "why it breaks", "index": 2, "total": 3},
    )
    assert sb.meta.title.endswith("— Part 2/3")
    assert len(sb.meta.title) <= 70  # StoryboardMeta.title max_length survives the suffix


def test_multi_part_job_publishes_a_post_per_part_and_points_at_part_one(client, monkeypatch):
    import app.main as main_module
    from app.models import Job, _engine
    from app.render import publish as publish_module
    from sqlmodel import Session

    monkeypatch.setattr(
        main_module,
        "run_plan_stage",
        lambda **kw: [{"title": "The problem", "focus": "f1"}, {"title": "The fix", "focus": "f2"}],
    )
    seen_parts: list = []

    def fake_script(*, part=None, **kw):
        seen_parts.append(part)
        return validate_storyboard(load(), "script")

    monkeypatch.setattr(main_module, "run_script_stage", fake_script)
    monkeypatch.setattr(main_module, "_voice_reel", lambda *a, **kw: None)

    created: list[str] = []
    real_publish = publish_module.publish_storyboard_only

    def spy(session, job, sb, **kw):
        post = real_publish(session, job, sb, **kw)
        created.append(post.id)
        return post

    monkeypatch.setattr(publish_module, "publish_storyboard_only", spy)

    me = client.get("/me").json()
    with Session(_engine) as session:
        job = Job(requester_id=me["id"], source_kind="topic", source_input="x")
        session.add(job)
        session.commit()
        job_id = job.id

    main_module._run_job(
        job_id, main_module.GenerateRequest(kind="topic", input="a topic worth two parts")
    )

    assert [p and (p["index"], p["total"], p["title"]) for p in seen_parts] == [
        (1, 2, "The problem"),
        (2, 2, "The fix"),
    ]
    assert len(created) == 2
    with Session(_engine) as session:
        job = session.get(Job, job_id)
        assert (job.state, job.progress) == ("published", 100)
        assert job.post_id == created[0], "the job must land the viewer on part 1"


def test_generate_records_the_requested_format_on_the_job(client, monkeypatch):
    """The row has to say what was asked for.

    "I picked video and got a reel" is otherwise unanswerable after the fact: the format
    lived only in the request body, so nothing on disk could tell a job that published the
    wrong thing from one that was never asked for the right thing.
    """
    import app.main as main_module

    # TestClient runs background tasks inline, and this covers the endpoint's write, not
    # the worker — without this the assertion below costs a real gateway call.
    monkeypatch.setattr(main_module, "_run_job", lambda *a, **kw: None)

    queued = client.post(
        "/generate", json={"kind": "topic", "input": "a topic worth explaining", "format": "video"}
    ).json()
    assert queued["format"] == "video"
    assert client.get(f"/jobs/{queued['id']}").json()["format"] == "video"

    # and the default is still the reel, for callers that predate the choice
    reel = client.post("/generate", json={"kind": "topic", "input": "a topic worth explaining"})
    assert reel.json()["format"] == "reel"


def test_generate_rejects_an_unknown_channel(client):
    body = {"kind": "topic", "input": "a topic with enough text", "channelId": "chn_nope"}
    assert client.post("/generate", json=body).status_code == 422


def test_multi_part_job_keeps_part_ones_storyboard_and_channel(client, monkeypatch):
    """`job.storyboard` must describe the post `job.post_id` points at.

    Each part overwrites the column as it runs, so the last part's storyboard was the one
    left behind while `post_id` still pointed at part 1 — the panel showed part 3's scenes
    under part 1's id.
    """
    import app.main as main_module
    from app.models import Job, Post, _engine
    from sqlmodel import Session, select

    monkeypatch.setattr(
        main_module,
        "run_plan_stage",
        lambda **kw: [{"title": "one", "focus": "f1"}, {"title": "two", "focus": "f2"}],
    )

    def fake_script(*, part=None, **kw):
        raw = load()
        raw["meta"]["title"] = f"part {part['index']}" if part else "whole"
        return validate_storyboard(raw, "script")

    monkeypatch.setattr(main_module, "run_script_stage", fake_script)
    monkeypatch.setattr(main_module, "_voice_reel", lambda *a, **kw: None)

    me = client.get("/me").json()
    channel = client.post("/channels", json={"name": "Part Landing Zone"}).json()
    with Session(_engine) as session:
        job = Job(requester_id=me["id"], source_kind="topic", source_input="x")
        session.add(job)
        session.commit()
        job_id = job.id

    main_module._run_job(
        job_id,
        main_module.GenerateRequest(kind="topic", input="two parts", channel_id=channel["id"]),
    )

    with Session(_engine) as session:
        job = session.get(Job, job_id)
        assert job.storyboard["meta"]["title"] == "part 1"
        assert session.get(Post, job.post_id).title == "part 1"
        # every part lands in the chosen channel, not just the one the caller hears about
        titles = {
            post.title: post.channel_id
            for post in session.exec(select(Post).where(Post.title.in_(["part 1", "part 2"]))).all()
        }
        assert titles == {"part 1": channel["id"], "part 2": channel["id"]}


def test_failed_second_part_keeps_part_one_and_names_the_failure(client, monkeypatch):
    import app.main as main_module
    from app.models import Job, _engine
    from sqlmodel import Session

    monkeypatch.setattr(
        main_module,
        "run_plan_stage",
        lambda **kw: [{"title": "The problem", "focus": "f1"}, {"title": "The fix", "focus": "f2"}],
    )

    def fake_script(*, part=None, **kw):
        if part and part["index"] == 2:
            raise RuntimeError("model fell over")
        return validate_storyboard(load(), "script")

    monkeypatch.setattr(main_module, "run_script_stage", fake_script)
    monkeypatch.setattr(main_module, "_voice_reel", lambda *a, **kw: None)

    me = client.get("/me").json()
    with Session(_engine) as session:
        job = Job(requester_id=me["id"], source_kind="topic", source_input="x")
        session.add(job)
        session.commit()
        job_id = job.id

    main_module._run_job(
        job_id, main_module.GenerateRequest(kind="topic", input="a topic worth two parts")
    )

    with Session(_engine) as session:
        job = session.get(Job, job_id)
        assert job.state == "failed"
        assert "part 2/2" in job.error and "The fix" in job.error
        assert job.post_id, "part 1's published post survives part 2's failure"
        assert client.get(f"/posts/{job.post_id}").status_code == 200
