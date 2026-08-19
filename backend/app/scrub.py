"""Redaction, applied at the ingestion boundary.

Slack threads are not documents. A thread about a production problem routinely
carries merchant ids, payment ids, phone numbers, customer emails and the occasional
pasted token, because that is what debugging looks like. All of it would otherwise
travel to a model and then into a video that gets posted to the whole company.

Two rules, both deliberate:

1. **Redaction happens in the adapter, never in the prompt.** A prompt instruction not
   to repeat a card number is advice; removing the number before the model can see it
   is a guarantee. Every ingestion path calls this before it returns text.

2. **Redaction is visible, not silent.** Each hit becomes a typed placeholder such as
   ``[merchant id]``, so the surrounding sentence still reads and the model can talk
   about "a merchant" without inventing an identifier. A count comes back with the
   text so a job can record what was removed.

The patterns are deliberately conservative in one direction only: a false positive
costs a slightly vaguer explainer, a false negative puts customer data on a screen.
When in doubt this over-redacts.

ponytail: regex, not a classifier. Razorpay identifiers are strongly prefixed
(``pay_``, ``order_``, ``acc_``) which regex handles exactly; free-form names are not
attempted at all, because a thread's participants are attributed on purpose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Razorpay entity ids. Prefixed and base-58-ish, so precise to match.
_ENTITY_PREFIXES = (
    "pay",
    "order",
    "acc",
    "cust",
    "token",
    "sub",
    "plan",
    "inv",
    "rfnd",
    "txn",
    "settl",
    "qr",
    "fund_account",
    "contact",
    "payout",
)

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Bearer tokens, API keys and secrets. First, because they are the worst.
    (
        "secret",
        re.compile(
            r"\b(?:rzp_(?:live|test)_[A-Za-z0-9]{10,}"
            r"|sk_[A-Za-z0-9]{16,}"
            r"|xox[baprs]-[A-Za-z0-9-]{10,}"          # slack tokens
            r"|gh[pousr]_[A-Za-z0-9]{20,}"            # github tokens
            r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})",  # jwt
            re.IGNORECASE,
        ),
    ),
    (
        "entity id",
        re.compile(rf"\b(?:{'|'.join(_ENTITY_PREFIXES)})_[A-Za-z0-9]{{8,}}\b"),
    ),
    # Card numbers: 13-19 digits, optionally spaced or hyphenated in groups.
    ("card number", re.compile(r"\b(?:\d[ -]?){12,18}\d\b")),
    # Indian mobile numbers, with or without country code.
    ("phone number", re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    # VPAs. Shaped like an email but @-suffixed with a handle, so it must come after.
    ("vpa", re.compile(r"\b[A-Za-z0-9._-]{2,}@(?:ok\w+|ybl|paytm|apl|axl|ibl|upi)\b", re.IGNORECASE)),
    ("ip address", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    # PAN and Aadhaar.
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("aadhaar", re.compile(r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)")),
)

#: Razorpay internal hostnames are fine to name; anything else with a query string may
#: carry a token in it, so the query is dropped rather than the whole link.
_URL_QUERY = re.compile(r"(https?://[^\s?]+)\?[^\s]*")


@dataclass(frozen=True)
class Scrubbed:
    text: str
    #: kind -> how many were replaced. Stored on the job so a reviewer can see what
    #: was removed without the removed values being kept anywhere.
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def scrub(text: str) -> Scrubbed:
    """Replace anything that looks like customer or credential data.

    Order matters: secrets before ids, email before VPA, and card numbers before
    phone numbers, so the broader pattern cannot eat a narrower one.

    >>> scrub("pay_MkL9x2QpAb31Zy failed for 9876543210").text
    '[entity id] failed for [phone number]'
    """
    counts: dict[str, int] = {}
    out = text

    for kind, pattern in _PATTERNS:
        placeholder = f"[{kind}]"
        out, hits = pattern.subn(placeholder, out)
        if hits:
            counts[kind] = counts.get(kind, 0) + hits

    out, query_hits = _URL_QUERY.subn(r"\1", out)
    if query_hits:
        counts["url query"] = query_hits

    return Scrubbed(text=out, counts=counts)
