/**
 * The storyboard contract. Single source of truth for three consumers:
 *   - TypeScript types            (z.infer, below)
 *   - the Claude tool input_schema (toolInputSchema(), below)
 *   - runtime validation           (validateStoryboard(), below)
 *
 * Stage ownership, and the reason this file is worth reading before writing any
 * pipeline code:
 *
 *   script stage (Claude)  writes scene content, narration, cite, broll.mood
 *   voice stage  (TTS)     writes durationMs   -- Claude must never set it
 *   visual stage (resolver) writes broll.clipId -- Claude must never set it
 *
 * Both pipeline-owned fields are rejected at the script stage and required at
 * the render stage. That turns "the video drifted out of sync" and "the model
 * invented a video asset" from debugging sessions into validation errors.
 */

import { z } from 'zod';

/**
 * The ONLY vocabulary Claude has for choosing footage.
 *
 * Generative video cannot render legible text or an accurate diagram, so it is
 * used strictly as a background plate and never as the carrier of information.
 * Claude picks a mood from this closed set; a resolver maps the mood to a
 * pre-generated, human-prompted Veo clip. Consequences of doing it this way:
 * no spec content ever reaches a video prompt, no per-request generation cost,
 * and no generation latency on the request path.
 */
export const BROLL_MOODS = [
  'dataflow',   // abstract packets / streams moving through a network
  'servers',    // racks, cabling, blinking indicators
  'team',       // people collaborating, over-shoulder, no legible screens
  'money',      // coins, cards, transaction motion
  'abstract',   // slow gradient / particle motion, safe behind dense overlays
  'city',       // scale and reach shots
] as const;
export type BrollMood = (typeof BROLL_MOODS)[number];

export const MAX_MERMAID_NODES = 7;
export const MAX_SPOKEN_SECONDS = 75; // 60s target, 75s hard ceiling
const WORDS_PER_SECOND = 160 / 60;

const narration = z
  .string()
  .min(10)
  .max(420)
  .describe(
    'What the voice says over this scene. Plain spoken prose. No markdown, no stage directions. Expand abbreviations a voice would stumble on.',
  );

const cite = z
  .string()
  .max(80)
  .describe(
    'The source section this scene came from, e.g. "Section 4 - Proposed Architecture". Rendered on screen as a chip. Required for factual scenes when the source is an AIDoc.',
  );

const broll = z.object({
  mood: z.enum(BROLL_MOODS).describe('Background footage mood. Chosen from the fixed set only.'),
  clipId: z
    .string()
    .optional()
    .describe('PIPELINE-SET. The resolver assigns the cached clip. Never set this.'),
});

const durationMs = z
  .number()
  .int()
  .min(800)
  .describe('PIPELINE-SET. Derived from the measured length of this scene narration audio. Never set this.');

const base = { narration, cite: cite.optional(), broll: broll.optional(), durationMs: durationMs.optional() };
const heading = z.string().min(3).max(60);

export const sceneSchema = z.discriminatedUnion('type', [
  z.object({
    type: z.literal('title'),
    heading,
    sub: z.string().max(90).optional(),
    ...base,
  }),
  z.object({
    type: z.literal('bullets'),
    heading,
    bullets: z
      .array(z.string().min(3).max(80))
      .min(2)
      .max(5)
      .describe('Short phrases, not sentences. These are read on screen, not aloud.'),
    ...base,
  }),
  z.object({
    type: z.literal('diagram'),
    heading,
    mermaid: z
      .string()
      .min(12)
      .describe(
        `Mermaid source for the real architecture in the document. Max ${MAX_MERMAID_NODES} nodes. Prefer "graph TD" for a 9:16 frame.`,
      ),
    ...base,
  }),
  z.object({
    type: z.literal('compare'),
    heading,
    left: comparePane('e.g. Legacy'),
    right: comparePane('e.g. Rearch'),
    ...base,
  }),
  z.object({
    type: z.literal('code'),
    heading: heading.optional(),
    lang: z.enum(['go', 'ts', 'json', 'sql', 'bash', 'yaml']).optional(),
    code: z.string().min(5).max(500).describe('Max ~12 lines. It has to be legible on a phone.'),
    ...base,
  }),
  z.object({
    type: z.literal('outro'),
    cta: z.string().min(3).max(50),
    url: z.string().optional(),
    ...base,
  }),
]);

function comparePane(labelHint: string) {
  return z.object({
    label: z.string().min(2).max(28).describe(labelHint),
    items: z.array(z.string().max(60)).min(1).max(4),
  });
}

export const storyboardSchema = z.object({
  meta: z.object({
    title: z.string().min(4).max(70).describe('Feed title. Punchy, not the document title verbatim.'),
    tags: z.array(z.string().regex(/^[a-z0-9-]+$/)).min(1).max(4),
  }),
  source: z.object({
    kind: z.enum(['aidoc', 'topic']),
    docId: z.string().optional().describe('Required when kind is aidoc.'),
    url: z.string().optional(),
    title: z.string().optional(),
  }),
  scenes: z.array(sceneSchema).min(3).max(8).describe('3-8 scenes, under 60 seconds spoken in total.'),
});

export type Scene = z.infer<typeof sceneSchema>;
export type Storyboard = z.infer<typeof storyboardSchema>;
export type SceneType = Scene['type'];
export type PipelineStage = 'script' | 'render';

/** Scene types that assert something about the source document, so they must cite it. */
const FACTUAL: readonly SceneType[] = ['bullets', 'diagram', 'compare', 'code'];

/** Rough spoken length. Rejects a runaway script before we pay for TTS. */
export function spokenSeconds(sb: Storyboard): number {
  const words = sb.scenes.reduce((total, s) => total + s.narration.trim().split(/\s+/).length, 0);
  return words / WORDS_PER_SECOND;
}

/**
 * Count distinct Mermaid node ids. Not expressible in a schema, and an 8-node
 * graph is illegible in a 9:16 frame, so it has to be a code-level rule.
 */
export function mermaidNodeCount(src: string): number {
  const ids = new Set<string>();
  for (const m of src.matchAll(/([A-Za-z_]\w*)\s*(?:[[({]|-{2,3}>|==>)/g)) ids.add(m[1]);
  for (const m of src.matchAll(/(?:-{2,3}>|==>)\s*\|[^|]*\|\s*([A-Za-z_]\w*)/g)) ids.add(m[1]);
  for (const m of src.matchAll(/(?:-{2,3}>|==>)\s*([A-Za-z_]\w*)/g)) ids.add(m[1]);
  return ids.size;
}

export type ValidationResult =
  | { ok: true; storyboard: Storyboard }
  | { ok: false; errors: string[] };

/**
 * @param input raw value, usually straight off a Claude tool call
 * @param stage 'script' right after generation, 'render' once voice and visuals have run
 */
export function validateStoryboard(input: unknown, stage: PipelineStage = 'script'): ValidationResult {
  const parsed = storyboardSchema.safeParse(input);
  if (!parsed.success) {
    // shape is wrong; the semantic rules below would only add noise
    return { ok: false, errors: parsed.error.issues.map((i) => `${i.path.join('.') || '/'}: ${i.message}`) };
  }

  const sb = parsed.data;
  const errors: string[] = [];

  sb.scenes.forEach((scene, i) => {
    const at = `scenes.${i}`;

    // pipeline-owned fields
    const hasDuration = scene.durationMs !== undefined;
    const hasClip = scene.broll?.clipId !== undefined;
    if (stage === 'script') {
      if (hasDuration) errors.push(`${at}.durationMs is pipeline-set, the script stage must not emit it`);
      if (hasClip) errors.push(`${at}.broll.clipId is pipeline-set, the script stage must not emit it`);
    } else {
      if (!hasDuration) errors.push(`${at}.durationMs missing, run the voice stage first`);
      if (scene.broll && !hasClip) errors.push(`${at}.broll.clipId missing, run the visual resolver first`);
    }

    // diagrams have to fit a phone screen
    if (scene.type === 'diagram') {
      const n = mermaidNodeCount(scene.mermaid);
      if (n > MAX_MERMAID_NODES) {
        errors.push(`${at}.mermaid has ${n} nodes, max ${MAX_MERMAID_NODES}. Split the scene or downgrade it to bullets`);
      } else if (n < 2) {
        errors.push(`${at}.mermaid parsed to ${n} nodes, probably malformed`);
      }
    }

    // every factual claim traces back to the document
    if (sb.source.kind === 'aidoc' && FACTUAL.includes(scene.type) && !scene.cite) {
      errors.push(`${at} (${scene.type}) needs a cite, every factual claim traces to a section`);
    }
  });

  if (sb.source.kind === 'aidoc' && !sb.source.docId) errors.push('source.docId is required when kind is aidoc');

  const seconds = spokenSeconds(sb);
  if (seconds > MAX_SPOKEN_SECONDS) {
    errors.push(`narration is ~${seconds.toFixed(0)}s spoken, ceiling is ${MAX_SPOKEN_SECONDS}s. Cut a scene`);
  }

  return errors.length ? { ok: false, errors } : { ok: true, storyboard: sb };
}

/** Fields the pipeline owns. Stripped from the model's view of the contract. */
const PIPELINE_OWNED = ['durationMs', 'clipId'] as const;

function stripPipelineFields(node: unknown): unknown {
  if (Array.isArray(node)) return node.map(stripPipelineFields);
  if (node === null || typeof node !== 'object') return node;

  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
    if (key === 'properties') {
      const props = Object.entries(value as Record<string, unknown>).filter(
        ([prop]) => !PIPELINE_OWNED.includes(prop as (typeof PIPELINE_OWNED)[number]),
      );
      out[key] = Object.fromEntries(props.map(([p, v]) => [p, stripPipelineFields(v)]));
      continue;
    }
    if (key === 'required' && Array.isArray(value)) {
      out[key] = value.filter((r) => !PIPELINE_OWNED.includes(r as (typeof PIPELINE_OWNED)[number]));
      continue;
    }
    out[key] = stripPipelineFields(value);
  }
  return out;
}

/**
 * JSON Schema for the Anthropic tool `input_schema`, generated from the same zod
 * definition the runtime validates against, so the model is told exactly what the
 * validator will enforce.
 *
 * The pipeline-owned fields are stripped rather than merely documented as
 * off-limits. zod's `io: 'input'` does not drop them (it only distinguishes
 * input from output types), and describing a field the model must not use is an
 * invitation to use it.
 */
export function toolInputSchema(): Record<string, unknown> {
  const schema = z.toJSONSchema(storyboardSchema, { io: 'input', target: 'draft-7' });
  return stripPipelineFields(schema) as Record<string, unknown>;
}
