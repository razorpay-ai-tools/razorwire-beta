"""HTML frame(s) -> PNG(s), via headless Chromium (Playwright).

Static scenes yield a single screenshot. Diagram scenes are ANIMATED: the page
exposes ``window.__seek(t)``, so we step time at a fixed fps and screenshot each
frame — capturing the diagram drawing itself. One browser is reused for all scenes.

Frame-stepping (drive time, screenshot) rather than video recording: Playwright's
headless recorder throttles frames and collapses the timeline, so it can't capture
smooth real-time animation. Stepping is deterministic and exact.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .errors import RenderUnavailable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SceneCapture:
    """One scene to capture: its HTML, whether it animates, and its length."""

    html: str
    animated: bool
    duration_ms: int


@dataclass(frozen=True)
class CapturedScene:
    """The PNG frame(s) for one scene — one still, or many for an animated scene."""

    frames: list[Path]
    animated: bool


def capture(
    scenes: list[SceneCapture],
    work_dir: Path,
    *,
    width: int,
    height: int,
    fps: int = 24,
    timeout_ms: int = 20_000,
) -> list[CapturedScene]:
    """Capture each scene to PNG frame(s). Reuses one headless browser.

    :raises RenderUnavailable: if Playwright or its Chromium build is not installed
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # not installed
        raise RenderUnavailable(f"Playwright not installed: {exc}") from exc

    # Absolute path required: as_uri() rejects a relative path, and the job's work_dir
    # is relative ("./.work/<job>").
    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    out: list[CapturedScene] = []

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                args=["--no-sandbox", "--allow-file-access-from-files", "--hide-scrollbars"]
            )
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            for index, spec in enumerate(scenes):
                html_path = work_dir / f"scene{index}.html"
                html_path.write_text(spec.html, encoding="utf-8")
                page.goto(html_path.as_uri(), wait_until="load")
                try:
                    page.wait_for_function("window.__ready === true", timeout=timeout_ms)
                except Exception:
                    log.warning("scene %d did not signal ready in %dms", index, timeout_ms)

                if spec.animated and spec.duration_ms > 0:
                    n_frames = max(1, int(spec.duration_ms / 1000 * fps))
                    frames: list[Path] = []
                    for f in range(n_frames + 1):
                        t = f * (1000.0 / fps)
                        try:
                            page.evaluate("window.__seek(%f)" % t)
                        except Exception:
                            pass
                        frame = work_dir / f"scene{index}_{f:04d}.png"
                        page.screenshot(path=str(frame))
                        frames.append(frame)
                    out.append(CapturedScene(frames=frames, animated=True))
                else:
                    still = work_dir / f"scene{index}.png"
                    page.screenshot(path=str(still))
                    out.append(CapturedScene(frames=[still], animated=False))
            browser.close()
    except RenderUnavailable:
        raise
    except Exception as exc:
        if "executable doesn't exist" in str(exc).lower() or "playwright install" in str(exc).lower():
            raise RenderUnavailable(
                "Chromium for Playwright is missing (run: playwright install chromium)"
            ) from exc
        raise

    return out
