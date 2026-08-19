"""Slack thread ingestion.

The second source. Deliberately shaped to look exactly like ``aidocs.py`` from the
outside, because everything downstream — the prompt, the validator, the citation
rule, the render contract — should not have to know which source it got.

The one idea that makes that work:

    A Slack thread has no section headings, so `cite` has nothing to point at.
    Instead every message becomes a Section whose heading is its author and time
    ("Ananya R, 14:32"). The model then cites the message it drew a claim from,
    exactly as it cites a document section, and a reviewer can find it.

That is strictly better grounding than a document section, because a section can be
long and a message is one person saying one thing.

What this module must get right:

1. **Scrub before returning.** A debugging thread carries payment ids, phone numbers
   and pasted tokens. ``scrub`` runs on every message body here, in the adapter, so no
   ingestion path can forget it. See ``scrub.py``.
2. **Resolve mentions.** Raw ``<@U03AB1CD2>`` in the text teaches the model to write
   user ids into narration. They become display names.
3. **Attribution.** These are real people's words. Participants come back with the
   thread so a post can name them and notify them.

ponytail: fetches over the Slack Web API with a bot token, one call for the thread and
one cached call per unknown user. No Socket Mode, no Events API — those belong with the
automatic trigger, not with reading one thread on demand.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import httpx

from .aidocs import Section
from .config import settings
from .scrub import scrub

log = logging.getLogger(__name__)

_API = "https://slack.com/api"
_FETCH_TIMEOUT_SECONDS = 20

#: Messages that are noise in every thread.
_SKIP_SUBTYPES = frozenset(
    {"channel_join", "channel_leave", "channel_topic", "channel_purpose", "bot_message", "tombstone"}
)

#: Below this a "thread" is one person talking to themselves, which is not a story.
MIN_THREAD_MESSAGES = 3

#: Razorpay runs on IST, and a timestamp a reader recognises is worth more than UTC.
_IST = timezone(timedelta(hours=5, minutes=30))

_PERMALINK = re.compile(
    r"""^https?://(?P<workspace>[\w-]+)\.slack\.com
        /archives/(?P<channel>[A-Z][A-Z0-9]+)
        /p(?P<ts>\d{10})(?P<micro>\d{6})
        (?:\?.*thread_ts=(?P<thread_ts>[\d.]+))?""",
    re.VERBOSE,
)

_MENTION = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>")
_CHANNEL_REF = re.compile(r"<#[C][A-Z0-9]+\|([^>]*)>")
_LINK_LABELLED = re.compile(r"<(?:https?://[^|>]+)\|([^>]+)>")
_LINK_BARE = re.compile(r"<(https?://[^>]+)>")
_SPECIAL = re.compile(r"<!(here|channel|everyone)(?:\|[^>]*)?>")

#: Slack formatting, unwrapped by matching PAIRS only.
#:
#: Stripping every `*_~\`` character instead is a trap worth spelling out: Slack marks
#: italics with `_text_`, so a blanket strip turns `block_fund` into `blockfund` and
#: `pay_MkL9x2QpAb31Zy` into `payMkL9x2QpAb31Zy`. That corrupts the identifiers an
#: engineering thread is mostly made of, and — much worse — it blinds the scrubber,
#: because a Razorpay entity id is only recognisable by its `pay_` prefix. The
#: underscore rule therefore requires non-word characters on both outer edges.
_UNWRAP = (
    re.compile(r"```(.+?)```", re.DOTALL),
    re.compile(r"`([^`\n]+)`"),
    re.compile(r"(?<![\w*])\*(\S(?:[^*\n]*\S)?)\*(?![\w*])"),
    re.compile(r"(?<![\w_])_(\S(?:[^_\n]*\S)?)_(?![\w_])"),
    re.compile(r"(?<![\w~])~(\S(?:[^~\n]*\S)?)~(?![\w~])"),
)


class SlackUnavailable(RuntimeError):
    """The thread could not be read. Mirrors ``AidocsUnavailable``."""


@dataclass(frozen=True)
class ThreadRef:
    channel: str
    ts: str
    workspace: str = "razorpay"

    @property
    def permalink(self) -> str:
        return (
            f"https://{self.workspace}.slack.com/archives/"
            f"{self.channel}/p{self.ts.replace('.', '')}"
        )


@dataclass(frozen=True)
class Participant:
    user_id: str
    display_name: str
    message_count: int


@dataclass(frozen=True)
class ThreadContent:
    """The same interface ``DocContent`` offers, so the pipeline cannot tell them apart."""

    ref: ThreadRef
    channel_name: str
    sections: tuple[Section, ...]
    participants: tuple[Participant, ...]
    #: kind -> count of redactions applied across the whole thread
    redactions: dict[str, int]

    @property
    def url(self) -> str:
        return self.ref.permalink

    @property
    def title(self) -> str:
        """Not the story's title — just enough for the model to know where it is."""
        return f"Thread in #{self.channel_name}"

    @property
    def is_structured(self) -> bool:
        """A thread is usable when enough separate people said enough separate things."""
        return len(self.sections) >= MIN_THREAD_MESSAGES and len(self.participants) >= 2

    def to_prompt_text(self) -> str:
        """Flatten to the text the model reads, with author and time as headings.

        Deliberately does NOT truncate — ``pipeline.run_script_stage`` caps total source
        length in one place.
        """
        parts = [f"# Slack thread in #{self.channel_name}"]
        for section in self.sections:
            parts.append(f"\n## {section.heading}\n{section.text}")
        return "\n".join(parts).strip()


# ------------------------------------------------------------------------ parsing


def parse_permalink(url: str) -> ThreadRef:
    """Turn a Slack permalink into a channel and thread timestamp.

    Slack writes the timestamp in a permalink as ``p1755601234567800`` — the dot is
    dropped, and the last six digits are microseconds. The API wants it back.

    :raises SlackUnavailable: if the URL is not a Slack archive permalink
    """
    match = _PERMALINK.match(url.strip())
    if match is None:
        raise SlackUnavailable(
            "expected a Slack message link like "
            "https://razorpay.slack.com/archives/C0192KLMN/p1755601234567800"
        )
    # A link to a reply carries the parent's ts in thread_ts; the parent is what we want.
    ts = match.group("thread_ts") or f"{match.group('ts')}.{match.group('micro')}"
    return ThreadRef(
        channel=match.group("channel"), ts=ts, workspace=match.group("workspace")
    )


def clean_text(raw: str, names: dict[str, str]) -> str:
    """Strip Slack markup and resolve mentions to display names.

    Raw ``<@U03AB1CD2>`` left in place teaches the model to write user ids into
    narration, which a voice then reads out one character at a time.
    """
    text = _MENTION.sub(lambda m: names.get(m.group(1), "a teammate"), raw)
    text = _SPECIAL.sub(lambda m: f"@{m.group(1)}", text)
    text = _CHANNEL_REF.sub(lambda m: f"#{m.group(1)}", text)
    text = _LINK_LABELLED.sub(lambda m: m.group(1), text)
    text = _LINK_BARE.sub(lambda m: m.group(1), text)
    for pattern in _UNWRAP:
        text = pattern.sub(r"\1", text)
    text = html.unescape(text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip()).strip()


def _heading(user_id: str, ts: str, names: dict[str, str]) -> str:
    who = names.get(user_id, "A teammate")
    try:
        when = datetime.fromtimestamp(float(ts), _IST).strftime("%H:%M")
    except (ValueError, OSError):  # pragma: no cover - malformed ts from the API
        return who
    return f"{who}, {when}"


def parse_thread(
    ref: ThreadRef,
    channel_name: str,
    messages: list[dict],
    names: dict[str, str],
) -> ThreadContent:
    """Normalise raw Slack messages into citable, scrubbed sections.

    Pure: no network. Everything interesting about this module is testable from here.
    """
    sections: list[Section] = []
    counts: dict[str, int] = {}
    per_user: dict[str, int] = {}

    for message in messages:
        if message.get("subtype") in _SKIP_SUBTYPES or message.get("bot_id"):
            continue
        user_id = message.get("user") or ""
        cleaned = clean_text(message.get("text") or "", names)
        if not cleaned:
            continue

        scrubbed = scrub(cleaned)
        for kind, hits in scrubbed.counts.items():
            counts[kind] = counts.get(kind, 0) + hits

        sections.append(
            Section(heading=_heading(user_id, message.get("ts", ""), names), text=scrubbed.text)
        )
        if user_id:
            per_user[user_id] = per_user.get(user_id, 0) + 1

    participants = tuple(
        Participant(user_id=uid, display_name=names.get(uid, uid), message_count=n)
        for uid, n in sorted(per_user.items(), key=lambda kv: -kv[1])
    )

    content = ThreadContent(
        ref=ref,
        channel_name=channel_name,
        sections=tuple(sections),
        participants=participants,
        redactions=counts,
    )
    if not content.is_structured:
        log.warning(
            "%s has %d usable message(s) from %d participant(s); too thin for a story",
            ref.permalink,
            len(content.sections),
            len(participants),
        )
    if counts:
        log.info("%s: redacted %s", ref.permalink, counts)
    return content


# ----------------------------------------------------------------------- transport


def _call(method: str, params: dict) -> dict:
    if not settings.slack_bot_token:
        raise SlackUnavailable("SLACK_BOT_TOKEN is not set")
    try:
        response = httpx.get(
            f"{_API}/{method}",
            params=params,
            headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
            timeout=_FETCH_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise SlackUnavailable(f"slack {method} failed: {exc}") from exc

    if response.status_code != 200:
        raise SlackUnavailable(f"slack {method} returned HTTP {response.status_code}")
    payload = response.json()
    if not payload.get("ok"):
        # `not_in_channel` and `channel_not_found` both mean "invite the bot", which is
        # the single most common setup mistake, so say so rather than echoing the code.
        error = payload.get("error", "unknown")
        if error in {"not_in_channel", "channel_not_found"}:
            raise SlackUnavailable(f"the bot is not in that channel (slack said {error!r})")
        raise SlackUnavailable(f"slack {method} said {error!r}")
    return payload


@lru_cache(maxsize=512)
def _display_name(user_id: str) -> str:
    """Resolve one user id. Cached: a thread mentions the same few people repeatedly."""
    try:
        user = _call("users.info", {"user": user_id}).get("user", {})
    except SlackUnavailable as exc:
        log.warning("could not resolve %s: %s", user_id, exc)
        return "a teammate"
    profile = user.get("profile", {})
    return (
        profile.get("display_name")
        or profile.get("real_name")
        or user.get("real_name")
        or user.get("name")
        or "a teammate"
    )


def fetch_thread(url: str) -> ThreadContent:
    """Read a Slack thread from a permalink and normalise it.

    :raises SlackUnavailable: when the thread cannot be read
    """
    ref = parse_permalink(url)

    replies = _call(
        "conversations.replies", {"channel": ref.channel, "ts": ref.ts, "limit": 200}
    )
    messages = replies.get("messages") or []
    if not messages:
        raise SlackUnavailable("that thread has no messages we can read")

    try:
        channel_name = (
            _call("conversations.info", {"channel": ref.channel})
            .get("channel", {})
            .get("name", ref.channel)
        )
    except SlackUnavailable as exc:
        log.warning("could not name channel %s: %s", ref.channel, exc)
        channel_name = ref.channel

    user_ids = {m.get("user") for m in messages if m.get("user")}
    for raw in messages:
        user_ids.update(_MENTION.findall(raw.get("text") or ""))
    names = {uid: _display_name(uid) for uid in user_ids if uid}

    return parse_thread(ref, channel_name, messages, names)
