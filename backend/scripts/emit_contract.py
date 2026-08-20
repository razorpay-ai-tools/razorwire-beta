"""Emit the storyboard contract for the web app.

The backend owns the contract because it owns the pipeline. The web app only
renders storyboards, so it consumes generated artifacts instead of keeping a
second hand-written definition that drifts.

    uv run python scripts/emit_contract.py

Writes:
    ../contracts/storyboard.schema.json        full JSON Schema (both stages)
    ../contracts/tool_input.schema.json        what Claude is shown (pipeline fields stripped)
    ../contracts/render-storyboard.schema.json the file the MP4 renderer reads
    ../src/lib/storyboard.types.ts             TypeScript types for the web app
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.storyboard import (  # noqa: E402
    BrollMood,
    MAX_MERMAID_NODES,
    MAX_SPOKEN_SECONDS,
    json_schema,
    tool_input_schema,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
TYPES_OUT = ROOT / "src" / "lib" / "storyboard.types.ts"

BANNER = """/**
 * GENERATED FILE - do not edit.
 *
 * Source of truth: backend/app/storyboard.py
 * Regenerate:      cd backend && uv run python scripts/emit_contract.py
 *
 * The backend owns the contract because it owns the pipeline (Claude, TTS, Veo
 * resolution). The web app renders storyboards, so it consumes these types
 * rather than keeping a second definition that drifts.
 */
"""


def ts_types() -> str:
    moods = " | ".join(f"'{m.value}'" for m in BrollMood)
    return f"""{BANNER}
export const BROLL_MOODS = [{", ".join(f"'{m.value}'" for m in BrollMood)}] as const;
export type BrollMood = {moods};

export const MAX_MERMAID_NODES = {MAX_MERMAID_NODES};
export const MAX_SPOKEN_SECONDS = {MAX_SPOKEN_SECONDS};

/** Assigned by the visual resolver, never by the model. */
export type Broll = {{ mood: BrollMood; clipId?: string }};

export type ComparePane = {{ label: string; items: string[] }};

type SceneBase = {{
  narration: string;
  /** The source section this scene came from. Rendered as a chip. */
  cite?: string;
  broll?: Broll;
  /** Set by the voice stage from measured audio length. Absent on the browser-reel path. */
  durationMs?: number;
  /** Set at publish: pre-generated narration audio. Absent means Web Speech narrates. */
  audioUrl?: string;
}};

export type TitleScene = SceneBase & {{ type: 'title'; heading: string; sub?: string }};
export type BulletsScene = SceneBase & {{ type: 'bullets'; heading: string; bullets: string[] }};
export type DiagramScene = SceneBase & {{ type: 'diagram'; heading: string; mermaid: string }};
export type CompareScene = SceneBase & {{
  type: 'compare';
  heading: string;
  left: ComparePane;
  right: ComparePane;
}};
export type CodeScene = SceneBase & {{
  type: 'code';
  heading?: string;
  lang?: 'go' | 'ts' | 'json' | 'sql' | 'bash' | 'yaml';
  code: string;
}};
export type OutroScene = SceneBase & {{ type: 'outro'; cta: string; url?: string }};

export type Scene =
  | TitleScene
  | BulletsScene
  | DiagramScene
  | CompareScene
  | CodeScene
  | OutroScene;

export type SceneType = Scene['type'];

export type Storyboard = {{
  meta: {{ title: string; tags: string[] }};
  source: {{ kind: 'aidoc' | 'topic'; docId?: string; url?: string; title?: string }};
  scenes: Scene[];
}};
"""


def main() -> None:
    CONTRACTS.mkdir(parents=True, exist_ok=True)
    TYPES_OUT.parent.mkdir(parents=True, exist_ok=True)

    # Generated from the same pydantic models we validate against, so the renderer's
    # schema and our validator cannot disagree about their own contract.
    from app.render_contract import RenderStoryboard

    render_schema = RenderStoryboard.model_json_schema(by_alias=True)

    written = [
        (CONTRACTS / "storyboard.schema.json", json.dumps(json_schema(), indent=2) + "\n"),
        (CONTRACTS / "tool_input.schema.json", json.dumps(tool_input_schema(), indent=2) + "\n"),
        (
            CONTRACTS / "render-storyboard.schema.json",
            json.dumps(render_schema, indent=2) + "\n",
        ),
        (TYPES_OUT, ts_types()),
    ]
    for path, content in written:
        path.write_text(content, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
