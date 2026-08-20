"""HTML frame -> PNG, via headless Chromium (Playwright).

One browser is launched for the whole storyboard and reused across scenes. Each
scene's HTML is written to the work directory and opened as a ``file://`` URL so its
local Mermaid bundle loads; the page sets ``window.__ready`` when it has settled and
we screenshot the exact viewport (no full-page scroll).
"""

from __future__ import annotations

import logging
from pathlib import Path

from .errors import RenderUnavailable

log = logging.getLogger(__name__)


def capture_scenes(
    htmls: list[str],
    work_dir: Path,
    *,
    width: int,
    height: int,
    timeout_ms: int = 20_000,
    keep_alpha: list[bool] | None = None,
) -> list[list[Path]]:
    """Screenshot each scene's build-up to ``scene<i>_s<step>.png``.

    Returns one list of paths per scene, in reveal order: bullets and diagram scenes
    yield a frame per step (the page's ``__reveal``), everything else a single frame.
    ``keep_alpha[i]`` omits Chromium's white page background for scene ``i`` so a
    translucent scrim survives into the PNG for compositing over footage.

    :raises RenderUnavailable: if Playwright or its Chromium build is not installed
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # not installed
        raise RenderUnavailable(f"Playwright not installed: {exc}") from exc

    work_dir.mkdir(parents=True, exist_ok=True)
    out: list[list[Path]] = []

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                args=["--no-sandbox", "--allow-file-access-from-files", "--hide-scrollbars"]
            )
            page = browser.new_page(
                viewport={"width": width, "height": height}, device_scale_factor=1
            )
            for index, html in enumerate(htmls):
                html_path = work_dir / f"scene{index}.html"
                html_path.write_text(html, encoding="utf-8")
                # work_dir descends from the relative WORK_DIR setting, and as_uri()
                # refuses relative paths outright.
                page.goto(html_path.resolve().as_uri(), wait_until="load")
                try:
                    page.wait_for_function("window.__ready === true", timeout=timeout_ms)
                except Exception:
                    # Screenshot what we have rather than fail the whole render on one
                    # slow diagram; a missing frame is worse than a slightly early one.
                    log.warning("scene %d did not signal ready in %dms", index, timeout_ms)
                alpha = bool(keep_alpha[index]) if keep_alpha else False
                # ponytail: steps capped at 8; a denser diagram than that is already
                # rejected by the storyboard's node limit.
                steps = min(8, int(page.evaluate("window.__stepCount || 1")))
                frames: list[Path] = []
                for step in range(1, steps + 1):
                    if steps > 1:
                        page.evaluate(f"window.__reveal({step})")
                    png = work_dir / f"scene{index}_s{step}.png"
                    page.screenshot(path=str(png), omit_background=alpha)
                    frames.append(png)
                out.append(frames)
            browser.close()
    except RenderUnavailable:
        raise
    except Exception as exc:
        # A launch failure usually means the browser binary is missing.
        if "executable doesn't exist" in str(exc).lower() or "playwright install" in str(exc).lower():
            raise RenderUnavailable(
                "Chromium for Playwright is missing (run: playwright install chromium)"
            ) from exc
        raise

    return out
