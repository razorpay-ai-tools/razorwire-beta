"""aidocs ingestion.

The differentiator, made real. Until this existed the API accepted a ``docId`` and
then ignored it, sending Claude whatever text the user had pasted — which meant the
citations in a storyboard referenced sections nobody had verified came from the doc.

Two things this has to get right:

1. **Section headings.** ``cite`` is only trustworthy if Claude is looking at the
   document's real section names, so the normaliser preserves headings and attributes
   body text to the nearest preceding one.
2. **No dependencies.** ``html.parser`` from the standard library. A single-file HTML
   document with inline ``<style>`` does not need an HTML5 tree builder.

Two fetch paths, and the reason there are two:

    AIDOCS_TOKEN set     HTTP against /v1/documents/... with a service-account key.
                         The only one that works in a container.
    AIDOCS_TOKEN unset   shell out to the `aidocs` CLI, which already holds a Google
                         session on a developer laptop. Nicer locally: no token to
                         mint, no env var to set.

The CLI path is why the hosted backend answered ``api 401 unauthorized`` for every
document: a container has no ``~/.config/aidocs/config.json``, so the CLI had no
credential to inherit. The HTTP path also reports the version id and the server's
``sha256``, which the CLI cannot, so a published explainer can notice its source
document moving underneath it.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, replace
from html.parser import HTMLParser

import httpx

from .config import settings

log = logging.getLogger(__name__)

#: Tags whose text content is markup, not prose.
_SKIP_CONTENT = frozenset({"style", "script", "noscript", "template"})
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_BLOCK = frozenset(
    {"p", "div", "li", "tr", "br", "section", "article", "header", "footer", "blockquote", "pre"}
)

_FETCH_TIMEOUT_SECONDS = 30

#: Tags that name a section without being an <h*>.
_PSEUDO_HEADINGS = frozenset({"dt", "summary", "legend", "th", "caption"})

#: A class or role that suggests the element is a heading. aidocs documents are
#: author-written HTML, and real ones frequently mark sections with a styled div
#: rather than an <h2> — our own submission uses `div.field-title`. Relying on <h*>
#: alone collapsed a ten-section document into one 12k-character blob, which leaves
#: Claude nothing real to cite.
_HEADING_HINTS = ("title", "heading", "header", "label", "field-name", "eyebrow")

#: Longest section we treat as structured. Past this the document has no usable
#: outline and we say so rather than pretending the citations will be meaningful.
_UNSTRUCTURED_SECTION_CHARS = 8000


class AidocsUnavailable(RuntimeError):
    """The document could not be fetched. Callers may fall back to pasted text."""


@dataclass(frozen=True)
class Section:
    heading: str
    text: str


@dataclass(frozen=True)
class DocContent:
    doc_id: str
    title: str
    sections: tuple[Section, ...]
    #: Which version this content came from, and the server's hash of it. Both are
    #: None on the CLI path, which cannot report them.
    version_id: str | None = None
    source_sha256: str | None = None

    @property
    def url(self) -> str:
        return f"https://aidocs.razorpay.com/app/d/{self.doc_id}"

    @property
    def is_structured(self) -> bool:
        """False when we found no usable outline, so citations would be guesswork."""
        named = [s for s in self.sections if s.heading]
        return len(named) >= 2 and all(len(s.text) <= _UNSTRUCTURED_SECTION_CHARS for s in self.sections)

    def to_prompt_text(self) -> str:
        """Flatten to the text Claude reads, with headings intact so it can cite them.

        Deliberately does NOT truncate. `pipeline.run_script_stage` caps total source
        length in one place; capping again per section here silently discarded most of
        a real document.
        """
        parts = [f"# {self.title}"] if self.title else []
        for section in self.sections:
            parts.append(f"\n## {section.heading}\n{section.text}" if section.heading else f"\n{section.text}")
        return "\n".join(parts).strip()


class _Extractor(HTMLParser):
    """Collect (heading, text) pairs in document order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_heading = False
        self._heading_tag = ""
        self._heading_parts: list[str] = []
        self._body_parts: list[str] = []
        self._current_heading = ""
        self.sections: list[Section] = []
        self.title = ""
        self._in_title = False

    # -- lifecycle ---------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_CONTENT:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        if self._in_heading:
            # nested markup inside a heading; keep it from running words together
            self._heading_parts.append("\n")
            return
        if tag in _HEADINGS or tag in _PSEUDO_HEADINGS or _looks_like_heading(attrs):
            self._flush_section()
            self._in_heading = True
            self._heading_tag = tag
            self._heading_parts = []
            return
        if tag in _BLOCK:
            self._body_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_CONTENT:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "title":
            self._in_title = False
            return
        if self._in_heading and tag == self._heading_tag:
            self._in_heading = False
            # a styled heading div often nests a caption span; first line is the name
            first = _collapse("".join(self._heading_parts)).split("\n")[0]
            self._current_heading = first[:120]

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title = _collapse(self.title + data)
        elif self._in_heading:
            self._heading_parts.append(data)
        else:
            self._body_parts.append(data)

    # -- assembly ----------------------------------------------------------

    def _flush_section(self) -> None:
        text = _collapse("".join(self._body_parts))
        self._body_parts = []
        if self._current_heading or text:
            self.sections.append(Section(heading=self._current_heading, text=text))

    def finish(self) -> None:
        self._flush_section()
        # Require prose. A heading with nothing under it (table header cells, mostly)
        # is not a citable section, and offering it as one invites a false citation.
        self.sections = [s for s in self.sections if s.text]


def _looks_like_heading(attrs: list[tuple[str, str | None]]) -> bool:
    for name, value in attrs:
        if not value:
            continue
        if name == "role" and value.strip().lower() == "heading":
            return True
        if name == "class":
            classes = value.lower()
            if any(hint in classes for hint in _HEADING_HINTS):
                return True
    return False


def _collapse(text: str) -> str:
    """Squash runs of whitespace but keep paragraph breaks."""
    lines = (line.strip() for line in text.replace("\r", "").split("\n"))
    kept = [" ".join(line.split()) for line in lines]
    out: list[str] = []
    for line in kept:
        if line:
            out.append(line)
        elif out and out[-1] != "":
            out.append("")
    return "\n".join(out).strip()


def parse_doc_html(doc_id: str, html: str) -> DocContent:
    """Turn a single-file aidocs HTML document into titled sections."""
    extractor = _Extractor()
    extractor.feed(html)
    extractor.close()
    extractor.finish()

    sections = tuple(extractor.sections)
    if not sections:
        # no headings and no prose we recognised; hand over the raw text rather than nothing
        sections = (Section(heading="", text=_collapse(html)),)

    content = DocContent(doc_id=doc_id, title=extractor.title, sections=sections)
    if not content.is_structured:
        log.warning(
            "%s has no usable section outline (%d sections, longest %d chars); "
            "citations will be coarse",
            doc_id,
            len(sections),
            max((len(s.text) for s in sections), default=0),
        )
    return content


@dataclass(frozen=True)
class PulledDoc:
    """Raw HTML plus the provenance needed to notice the document changing."""

    html: str
    version_id: str | None = None
    #: The server's own hash of this version. Cheap staleness detection: store it with
    #: the post, compare on the next poll, regenerate when it moves.
    sha256: str | None = None


def _api(path: str, *, token: str) -> httpx.Response:
    url = f"{settings.aidocs_server.rstrip('/')}/v1{path}"
    try:
        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=_FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise AidocsUnavailable(f"aidocs {path} failed: {exc}") from exc

    if response.status_code == 401:
        raise AidocsUnavailable(
            "aidocs rejected the token. Check AIDOCS_TOKEN — a service-account key from "
            "`aidocs sa key create <sa_id>`, not a personal CLI session."
        )
    if response.status_code == 403:
        raise AidocsUnavailable(
            f"the service account is not allowed to read that document ({path}). "
            "Grant it access, or use a document shared with the org."
        )
    if response.status_code == 404:
        raise AidocsUnavailable(f"aidocs has no such document or version ({path})")
    if response.status_code >= 400:
        raise AidocsUnavailable(f"aidocs {path} returned HTTP {response.status_code}")
    return response


def _pull_over_http(doc_id: str, token: str) -> PulledDoc:
    """Fetch the current version's HTML over the API.

    Two calls, and the first one is not waste: ``/versions`` is where the version id
    and the server's ``sha256`` come from, which is what lets us tell later that a
    document moved under a published explainer.
    """
    versions = _api(f"/documents/{doc_id}/versions", token=token).json()
    items = versions if isinstance(versions, list) else versions.get("items", [])
    if not items:
        raise AidocsUnavailable(f"{doc_id} has no versions")

    current = max(items, key=lambda v: v.get("number", 0))
    version_id = current.get("id")
    html = _api(f"/documents/{doc_id}/versions/{version_id}/html", token=token).text
    if not html.strip():
        raise AidocsUnavailable(f"{doc_id} version {version_id} is empty")
    return PulledDoc(html=html, version_id=version_id, sha256=current.get("sha256"))


def _pull_over_cli(doc_id: str) -> PulledDoc:
    """Fallback for a developer laptop, where the CLI already holds a Google session.

    Kept because it is genuinely nicer locally: no token to mint, no env var to set.
    It cannot work in a container — there is no ``~/.config/aidocs/config.json`` there,
    which is exactly how the hosted backend ended up answering `api 401 unauthorized`
    for every document.
    """
    if shutil.which("aidocs") is None:
        raise AidocsUnavailable(
            "no AIDOCS_TOKEN is set and the aidocs CLI is not on PATH. Set AIDOCS_TOKEN "
            "to a service-account key for anything that is not a developer laptop."
        )
    command = ["aidocs"]
    if settings.aidocs_server:
        command += ["--server", settings.aidocs_server]
    command += ["docs", "pull", doc_id]
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, doc_id is validated by the caller
            command,
            capture_output=True,
            text=True,
            timeout=_FETCH_TIMEOUT_SECONDS,
            check=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise AidocsUnavailable(f"aidocs pull timed out after {_FETCH_TIMEOUT_SECONDS}s") from exc
    except subprocess.CalledProcessError as exc:
        raise AidocsUnavailable(f"aidocs pull failed: {(exc.stderr or '').strip()[:300]}") from exc

    if not result.stdout.strip():
        raise AidocsUnavailable("aidocs returned an empty document")
    return PulledDoc(html=result.stdout)


def _pull(doc_id: str) -> PulledDoc:
    """HTTP when we hold a token, CLI when we do not."""
    if settings.aidocs_token:
        return _pull_over_http(doc_id, settings.aidocs_token)
    log.info("no AIDOCS_TOKEN set, falling back to the aidocs CLI session")
    return _pull_over_cli(doc_id)


def fetch_doc(doc_id: str) -> DocContent:
    """Fetch and normalise a document.

    :raises AidocsUnavailable: when the document cannot be retrieved
    """
    if not doc_id.startswith("doc_") or not doc_id[4:].isalnum():
        raise AidocsUnavailable(f"{doc_id!r} is not a valid aidocs document id")
    pulled = _pull(doc_id)
    content = parse_doc_html(doc_id, pulled.html)
    return replace(content, version_id=pulled.version_id, source_sha256=pulled.sha256)
