/**
 * GENERATED FILE - do not edit.
 *
 * Source of truth: backend/app/storyboard.py
 * Regenerate:      cd backend && uv run python scripts/emit_contract.py
 *
 * The backend owns the contract because it owns the pipeline (Claude, TTS, Veo
 * resolution). The web app renders storyboards, so it consumes these types
 * rather than keeping a second definition that drifts.
 */

export const BROLL_MOODS = ['dataflow', 'servers', 'team', 'money', 'abstract', 'city'] as const;
export type BrollMood = 'dataflow' | 'servers' | 'team' | 'money' | 'abstract' | 'city';

export const MAX_MERMAID_NODES = 7;
export const MAX_SPOKEN_SECONDS = 75;

/** Assigned by the visual resolver, never by the model. */
export type Broll = { mood: BrollMood; clipId?: string };

export type ComparePane = { label: string; items: string[] };

type SceneBase = {
  narration: string;
  /** The source section this scene came from. Rendered as a chip. */
  cite?: string;
  broll?: Broll;
  /** Set by the voice stage from measured audio length. Absent on the browser-reel path. */
  durationMs?: number;
};

export type TitleScene = SceneBase & { type: 'title'; heading: string; sub?: string };
export type BulletsScene = SceneBase & { type: 'bullets'; heading: string; bullets: string[] };
export type DiagramScene = SceneBase & { type: 'diagram'; heading: string; mermaid: string };
export type CompareScene = SceneBase & {
  type: 'compare';
  heading: string;
  left: ComparePane;
  right: ComparePane;
};
export type CodeScene = SceneBase & {
  type: 'code';
  heading?: string;
  lang?: 'go' | 'ts' | 'json' | 'sql' | 'bash' | 'yaml';
  code: string;
};
export type OutroScene = SceneBase & { type: 'outro'; cta: string; url?: string };

export type Scene =
  | TitleScene
  | BulletsScene
  | DiagramScene
  | CompareScene
  | CodeScene
  | OutroScene;

export type SceneType = Scene['type'];

export type Storyboard = {
  meta: { title: string; tags: string[] };
  source: { kind: 'aidoc' | 'topic'; docId?: string; url?: string; title?: string };
  scenes: Scene[];
};
