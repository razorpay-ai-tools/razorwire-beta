"""Ingestion tests — Slack and aidocs, plus the scrubber that guards both.

No network. ``parse_thread`` is pure, so everything that matters about the Slack
adapter is testable from raw message dicts shaped exactly like Slack's API returns.

The scrubber gets the most attention here on purpose: it is the one component where a
miss puts customer data on a screen in front of the whole company.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DEV_AUTH_EMAIL", "tester@razorpay.com")
os.environ["DATABASE_URL"] = "sqlite://"

from app import slack  # noqa: E402
from app.scrub import scrub  # noqa: E402
from app.storyboard import (  # noqa: E402
    GROUNDED_SOURCE_KINDS,
    StoryboardInvalid,
    validate_storyboard,
)

PERMALINK = "https://razorpay.slack.com/archives/C0192KLMN/p1755601234567800"

NAMES = {"U03AB1CD2": "Ananya R", "U04XY9ZW1": "Kabir S", "U05MN3PQ4": "Devika J"}


def thread_messages() -> list[dict]:
    """Shaped like conversations.replies, including the noise a real thread carries."""
    return [
        {
            "user": "U03AB1CD2",
            "ts": "1755601234.567800",
            "text": "we're seeing 5xx on <#C0777AAAA|payments-alerts> right after every deploy",
        },
        {
            "user": "U04XY9ZW1",
            "ts": "1755601500.000100",
            "text": "<@U03AB1CD2> is it *only* right after? pay_MkL9x2QpAb31Zy failed at 14:31",
        },
        {"subtype": "channel_join", "user": "U05MN3PQ4", "ts": "1755601600.000100", "text": "joined"},
        {"bot_id": "B01", "ts": "1755601650.000100", "text": "PagerDuty: incident triggered"},
        {
            "user": "U03AB1CD2",
            "ts": "1755601800.000200",
            "text": "yes. pod reports ready before the db pool is warm. see <https://x.co/a|the graph>",
        },
        {
            "user": "U05MN3PQ4",
            "ts": "1755602100.000300",
            "text": "then the fix is a real readiness check. ping me at 9876543210 or devika@razorpay.com",
        },
        {"user": "U04XY9ZW1", "ts": "1755602400.000400", "text": "   "},
    ]


@pytest.fixture
def thread() -> slack.ThreadContent:
    ref = slack.parse_permalink(PERMALINK)
    return slack.parse_thread(ref, "payments-platform", thread_messages(), NAMES)


# ---------------------------------------------------------------------- the scrubber


@pytest.mark.parametrize(
    ("raw", "expected_kind"),
    [
        ("pay_MkL9x2QpAb31Zy failed", "entity id"),
        ("merchant acc_JK3Yi8SZpwBP2M", "entity id"),
        ("call 9876543210 now", "phone number"),
        ("call +91 9876543210 now", "phone number"),
        ("mail devika@razorpay.com", "email"),
        ("card 4111 1111 1111 1111", "card number"),
        ("vpa saksham@okhdfcbank", "vpa"),
        ("host 10.0.42.7", "ip address"),
        ("key rzp_live_AbCdEf123456", "secret"),
        ("slack xoxb-1234567890-abcdefghij", "secret"),
        ("gh ghp_abcdefghijklmnopqrstuvwxyz01", "secret"),
        ("pan ABCDE1234F", "pan"),
    ],
)
def test_scrub_catches_each_kind(raw: str, expected_kind: str) -> None:
    result = scrub(raw)
    assert expected_kind in result.counts, f"{raw!r} -> {result.text!r}"
    assert f"[{expected_kind}]" in result.text


def test_scrub_leaves_ordinary_engineering_prose_alone() -> None:
    prose = "pg-router calls payments-mandate, and the readiness check gates traffic."
    result = scrub(prose)
    assert result.text == prose
    assert result.total == 0


def test_scrub_strips_query_strings_that_could_carry_a_token() -> None:
    result = scrub("open https://dash.razorpay.com/app/payments?token=abc123")
    assert result.text.endswith("/app/payments")
    assert "abc123" not in result.text


def test_scrub_counts_every_hit_so_a_job_can_record_what_was_removed() -> None:
    result = scrub("pay_AAAAAAAA1 and pay_BBBBBBBB2 for 9876543210")
    assert result.counts == {"entity id": 2, "phone number": 1}
    assert result.total == 3


# --------------------------------------------------------------------- permalinks


def test_parse_permalink_restores_the_dotted_timestamp() -> None:
    ref = slack.parse_permalink(PERMALINK)
    assert (ref.channel, ref.ts, ref.workspace) == ("C0192KLMN", "1755601234.567800", "razorpay")


def test_a_link_to_a_reply_resolves_to_its_parent_thread() -> None:
    reply = f"{PERMALINK}?thread_ts=1755600000.111100&cid=C0192KLMN"
    assert slack.parse_permalink(reply).ts == "1755600000.111100"


def test_permalink_round_trips() -> None:
    assert slack.parse_permalink(PERMALINK).permalink == PERMALINK


@pytest.mark.parametrize(
    "bad",
    [
        "https://razorpay.slack.com/archives/C0192KLMN",
        "https://example.com/archives/C0192KLMN/p1755601234567800",
        "doc_r523noskel555f7f",
        "",
    ],
)
def test_a_non_permalink_is_rejected_with_an_example(bad: str) -> None:
    with pytest.raises(slack.SlackUnavailable, match="archives"):
        slack.parse_permalink(bad)


# ------------------------------------------------------------------- normalisation


def test_each_message_becomes_a_citable_section(thread: slack.ThreadContent) -> None:
    """The whole design: a heading the model can cite, per message."""
    headings = [s.heading for s in thread.sections]
    assert headings == [
        "Ananya R, 16:30",
        "Kabir S, 16:35",
        "Ananya R, 16:40",
        "Devika J, 16:45",
    ]


def test_noise_and_empty_messages_are_dropped(thread: slack.ThreadContent) -> None:
    """joins, bot posts and whitespace-only replies are not part of the story"""
    assert len(thread.sections) == 4  # from 7 raw messages
    body = thread.to_prompt_text()
    assert "joined" not in body
    assert "PagerDuty" not in body


def test_mentions_become_names_not_user_ids(thread: slack.ThreadContent) -> None:
    """A voice reads U03AB1CD2 out one character at a time."""
    body = thread.to_prompt_text()
    assert "U03AB1CD2" not in body
    assert "Ananya R is it only right after?" in body


def test_slack_markup_is_stripped(thread: slack.ThreadContent) -> None:
    body = thread.to_prompt_text()
    assert "#payments-alerts" in body       # <#C..|name> -> #name
    assert "the graph" in body              # <url|label> -> label
    assert "https://x.co/a" not in body
    assert "*only*" not in body             # bold markers gone


@pytest.mark.parametrize(
    ("raw", "must_survive"),
    [
        ("the *real* fix is block_fund handling", "block_fund"),
        ("_check_ this_ and mandate_setups", "mandate_setups"),
        ("`pay_MkL9x2QpAb31Zy` in code fences", "pay_"),
        ("frequency=one_time forces it on", "one_time"),
    ],
)
def test_snake_case_identifiers_survive_markup_stripping(raw: str, must_survive: str) -> None:
    """Slack italics are `_text_`, so a blanket underscore strip is a trap.

    It corrupts the identifiers an engineering thread is made of, and it blinds the
    scrubber: a Razorpay entity id is only recognisable by its `pay_` prefix.
    """
    cleaned = slack.clean_text(raw, {})
    assert must_survive in cleaned, cleaned


def test_italics_are_still_unwrapped() -> None:
    assert slack.clean_text("this is _really_ important", {}) == "this is really important"
    assert slack.clean_text("the *real* fix", {}) == "the real fix"


def test_scrubbing_happens_in_the_adapter_not_the_prompt(thread: slack.ThreadContent) -> None:
    """Nothing sensitive can reach the model, whatever the prompt says."""
    body = thread.to_prompt_text()
    for secret in ("pay_MkL9x2QpAb31Zy", "9876543210", "devika@razorpay.com"):
        assert secret not in body
    assert thread.redactions == {"entity id": 1, "phone number": 1, "email": 1}


def test_participants_are_attributed_and_ranked(thread: slack.ThreadContent) -> None:
    assert [(p.display_name, p.message_count) for p in thread.participants] == [
        ("Ananya R", 2),
        ("Kabir S", 1),
        ("Devika J", 1),
    ]


def test_thread_content_offers_the_same_interface_as_a_document(
    thread: slack.ThreadContent,
) -> None:
    """The pipeline must not be able to tell the two sources apart."""
    from app.aidocs import DocContent

    for attribute in ("url", "title", "is_structured", "to_prompt_text", "sections"):
        assert hasattr(thread, attribute), f"ThreadContent is missing {attribute}"
        doc_has = attribute in DocContent.__annotations__ or hasattr(DocContent, attribute)
        assert doc_has, f"DocContent is missing {attribute}"
    assert thread.url == PERMALINK
    assert thread.is_structured


@pytest.mark.parametrize(
    ("messages", "why"),
    [
        ([{"user": "U03AB1CD2", "ts": "1755601234.5678", "text": "a lone thought"}], "too few"),
        (
            [
                {"user": "U03AB1CD2", "ts": f"175560123{i}.5678", "text": f"thought {i}"}
                for i in range(4)
            ],
            "one participant",
        ),
    ],
)
def test_a_thin_thread_is_not_structured(messages: list[dict], why: str) -> None:
    ref = slack.parse_permalink(PERMALINK)
    content = slack.parse_thread(ref, "some-channel", messages, NAMES)
    assert not content.is_structured, why


# ------------------------------------------------------------- the contract accepts it


def _slack_storyboard(**source_overrides) -> dict:
    source = {"kind": "slack", "url": PERMALINK, **source_overrides}
    return {
        "meta": {"title": "Why deploys briefly 5xx", "tags": ["reliability"]},
        "source": source,
        "scenes": [
            {
                "type": "title",
                "heading": "Ready is not the same as awake",
                "narration": "A server can be switched on and still not able to work.",
            },
            {
                "type": "bullets",
                "heading": "What on-call saw",
                "bullets": ["5xx right after deploys", "pods ready before the pool is warm"],
                "narration": "Errors spiked in the first minute after every deploy.",
                "cite": "Ananya R, 16:30",
            },
            {
                "type": "diagram",
                "heading": "The gap",
                "mermaid": "graph TD\n  A[Deploy] --> B[Pod ready]\n  B --> C[Traffic]",
                "narration": "Traffic arrives before the pod can finish a request.",
                "cite": "Ananya R, 16:40",
            },
            {
                "type": "outro",
                "cta": "Open the thread",
                "narration": "The thread has the fix and who is doing it.",
            },
        ],
    }


def test_a_slack_sourced_storyboard_validates() -> None:
    sb = validate_storyboard(_slack_storyboard(), stage="script")
    assert sb.source.kind == "slack"


def test_slack_is_a_grounded_source_so_factual_scenes_still_need_a_cite() -> None:
    assert "slack" in GROUNDED_SOURCE_KINDS
    data = _slack_storyboard()
    del data["scenes"][1]["cite"]
    with pytest.raises(StoryboardInvalid, match="needs a cite"):
        validate_storyboard(data, stage="script")


def test_a_slack_source_must_carry_the_thread_url() -> None:
    data = _slack_storyboard()
    data["source"].pop("url")
    with pytest.raises(StoryboardInvalid, match="source.url is required"):
        validate_storyboard(data, stage="script")


def test_a_slack_storyboard_projects_onto_the_render_contract() -> None:
    """Both sources must reach the renderer's file, indistinguishably."""
    from app import render_contract as rc

    payload, _ = rc.emit(validate_storyboard(_slack_storyboard(), stage="script"))
    rc.validate_render_storyboard(payload)
    # provenance is ours; it never travels in the render file
    assert "slack.com" not in __import__("json").dumps(payload)
