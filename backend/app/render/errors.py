"""Render errors, in a leaf module so capture/compose/pipeline can share them
without an import cycle."""

from __future__ import annotations


class RenderUnavailable(RuntimeError):
    """A required local tool (ffmpeg, Chromium) is missing.

    Distinct from an unexpected failure: the caller catches this to fall back to a
    storyboard-only publish (the browser reel) instead of failing the whole job.
    """
