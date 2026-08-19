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

ponytail: fetches by shelling out to the `aidocs` CLI, which is already installed and
authenticated on every dev machine. The production path is a service-account bearer
token against the HTTP API — swap `_pull_html` when this runs anywhere shared.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from html.parser import HTMLParser

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


def _pull_html(doc_id: str) -> str:
    if shutil.which("aidocs") is None:
        raise AidocsUnavailable("the aidocs CLI is not on PATH")
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, doc_id is validated by the caller
            ["aidocs", "docs", "pull", doc_id],
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
    return result.stdout


def fetch_doc(doc_id: str) -> DocContent:
    """Fetch and normalise a document.

    :raises AidocsUnavailable: when the document cannot be retrieved
    """
    if not doc_id.startswith("doc_") or not doc_id[4:].isalnum():
        raise AidocsUnavailable(f"{doc_id!r} is not a valid aidocs document id")
    return parse_doc_html(doc_id, _pull_html(doc_id))
