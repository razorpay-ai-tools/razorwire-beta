"""The MP4 render pipeline: storyboard.json -> narrated, animated 9:16 video.

Stages, mirroring the `voicing` and `rendering` job states:

    tts.py      narration -> per-scene wav + measured duration  (Kokoro, else macOS `say`)
    html.py     one internal scene -> a self-contained 9:16 HTML frame (Mermaid for diagrams)
    capture.py  that HTML -> a PNG, via headless Chromium (Playwright)
    compose.py  PNGs + wavs + captions -> video.mp4, via ffmpeg (Ken Burns + burned captions)
    pipeline.py orchestrates the above; `render_video(sb, work_dir) -> RenderResult`
    publish.py  the mp4 -> media storage + a `generated` feed Post

The renderer consumes the *internal* storyboard shape (`app.storyboard.Storyboard`) —
the same JSON the feed and `job.storyboard` already use — so a rendered video is a
faithful recording of the reel, not a second design that can drift from it.

Everything here is local and free: Chromium, ffmpeg and the TTS all run on this box.
Nothing leaves the perimeter and there is no per-render cost.
"""

from __future__ import annotations

from .pipeline import (
    RenderResult,
    RenderUnavailable,
    render_from_voiced,
    render_video,
    voice_storyboard,
)

# `render_from_voiced` belongs here because `main._run_job` imports it from this package
# to run voicing and rendering as separate job states. It was in `pipeline.__all__` but
# never re-exported, so every generation that got past the model died on
# `cannot import name 'render_from_voiced'` — after the paid call, which is the worst
# place to fail.
__all__ = [
    "RenderResult",
    "RenderUnavailable",
    "render_from_voiced",
    "render_video",
    "voice_storyboard",
]
