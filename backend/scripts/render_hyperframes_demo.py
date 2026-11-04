"""Render one storyboard through the HyperFrames engine, end to end.

A proof and a smoke test, not part of the service. Voices the storyboard with
whatever TTS backend is available (`say` on a Mac needs no model download), builds
the composition, gates it on `hyperframes check`, and renders the MP4.

    cd backend
    .venv/bin/python scripts/render_hyperframes_demo.py \\
        ../src/lib/fixtures/otm-rearch.storyboard.json /tmp/reel.mp4
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.render import hyperframes, tts  # noqa: E402
from app.storyboard import validate_storyboard  # noqa: E402


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    source, out = Path(sys.argv[1]), Path(sys.argv[2])

    sb = validate_storyboard(json.loads(source.read_text()), stage="script")
    print(f"storyboard: {sb.meta.title} ({len(sb.scenes)} scenes)")

    work = out.parent / (out.stem + ".work")
    work.mkdir(parents=True, exist_ok=True)

    voiced = tts.voice_scenes([scene.narration for scene in sb.scenes], work)
    for scene, spoken in zip(sb.scenes, voiced):
        scene.duration_ms = spoken.duration_ms
    total = sum(v.duration_ms for v in voiced) / 1000
    print(f"voiced: {total:.1f}s total, cues per scene: {[len(v.cues) for v in voiced]}")

    project = hyperframes.build_composition(sb, voiced, work / "composition")
    print(f"composition: {project}")

    hyperframes.check(project)
    print("check: passed")

    hyperframes.render(project, out)
    print(f"rendered: {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
