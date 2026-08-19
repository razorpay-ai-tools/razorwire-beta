/**
 * Self-check for the storyboard contract.  Run: npm run validate
 * Node 26 runs TypeScript directly, so there is no build step and no test framework.
 */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  BROLL_MOODS,
  MAX_MERMAID_NODES,
  mermaidNodeCount,
  toolInputSchema,
  validateStoryboard,
  type Storyboard,
} from '../src/lib/storyboard.ts';

const HERE = dirname(fileURLToPath(import.meta.url));
const load = (): Storyboard =>
  JSON.parse(readFileSync(join(HERE, '../src/lib/fixtures/otm-rearch.storyboard.json'), 'utf8'));

let failed = 0;
function check(name: string, condition: boolean, detail?: unknown) {
  if (condition) {
    console.log('ok   ', name);
    return;
  }
  failed += 1;
  console.error('FAIL ', name, detail === undefined ? '' : `\n       ${JSON.stringify(detail)}`);
}
const errorsOf = (r: ReturnType<typeof validateStoryboard>) => (r.ok ? [] : r.errors);

// --- the fixture is the contract's worked example ----------------------------

const base = validateStoryboard(load(), 'script');
check('fixture is valid at the script stage', base.ok, errorsOf(base));

// --- pipeline-owned fields: durationMs --------------------------------------

const noDurations = errorsOf(validateStoryboard(load(), 'render'));
check(
  'render stage rejects missing durations',
  noDurations.filter((e) => e.includes('durationMs missing')).length === 6,
  noDurations,
);

const voiced = load();
voiced.scenes.forEach((s) => {
  s.durationMs = 4000;
  if (s.broll) s.broll.clipId = 'veo_abstract_01';
});
check('render stage accepts injected durations and clip ids', validateStoryboard(voiced, 'render').ok);
check(
  'script stage rejects model-set durations',
  errorsOf(validateStoryboard(voiced, 'script')).some((e) => e.includes('durationMs is pipeline-set')),
);

// --- pipeline-owned fields: broll.clipId ------------------------------------

const clipOnly = load();
clipOnly.scenes[0].broll!.clipId = 'veo_money_01';
check(
  'script stage rejects a model-invented video asset',
  errorsOf(validateStoryboard(clipOnly, 'script')).some((e) => e.includes('broll.clipId is pipeline-set')),
);

const unresolved = load();
unresolved.scenes.forEach((s) => {
  s.durationMs = 4000;
});
check(
  'render stage rejects unresolved broll',
  errorsOf(validateStoryboard(unresolved, 'render')).some((e) => e.includes('clipId missing')),
);

const badMood = load();
// a free-text video prompt is exactly what the closed mood set exists to prevent
(badMood.scenes[0] as { broll?: unknown }).broll = { mood: 'a wide cinematic shot of a datacenter' };
check('rejects a mood outside the fixed set', !validateStoryboard(badMood, 'script').ok);
check('mood set is non-empty and unique', BROLL_MOODS.length === new Set(BROLL_MOODS).size && BROLL_MOODS.length > 0);

// --- diagrams must fit a 9:16 frame -----------------------------------------

const fatDiagram = load();
const diagramScene = fatDiagram.scenes.find((s) => s.type === 'diagram')!;
if (diagramScene.type === 'diagram') {
  diagramScene.mermaid =
    'graph TD\n' + Array.from({ length: 9 }, (_, i) => `  N${i} --> N${i + 1}`).join('\n');
}
check(
  'rejects an oversized diagram',
  errorsOf(validateStoryboard(fatDiagram, 'script')).some((e) => e.includes(`max ${MAX_MERMAID_NODES}`)),
);
check('counts nodes through edge labels', mermaidNodeCount('graph TD\n A -->|yes| B\n B --> C') === 3);
check('counts nodes in the fixture diagram', mermaidNodeCount('graph TD\n A[x] --> B[(y)]') === 2);

// --- citations --------------------------------------------------------------

const uncited = load();
delete uncited.scenes[1].cite;
check(
  'rejects an uncited factual scene from an AIDoc',
  errorsOf(validateStoryboard(uncited, 'script')).some((e) => e.includes('needs a cite')),
);

const topic = load();
topic.source = { kind: 'topic' };
topic.scenes.forEach((s) => delete s.cite);
check('a topic source does not require citations', validateStoryboard(topic, 'script').ok);

const noDocId = load();
topic.source = { kind: 'topic' };
delete noDocId.source.docId;
check(
  'requires docId when the source is an AIDoc',
  errorsOf(validateStoryboard(noDocId, 'script')).some((e) => e.includes('source.docId')),
);

// --- budget and shape -------------------------------------------------------

const windy = load();
windy.scenes[1].narration = 'word '.repeat(80).trim();
check('rejects a runaway script', errorsOf(validateStoryboard(windy, 'script')).some((e) => e.includes('ceiling')));

const thin = load();
if (thin.scenes[1].type === 'bullets') thin.scenes[1].bullets = ['only one'];
check('rejects too few bullets', !validateStoryboard(thin, 'script').ok);

const short = load();
short.scenes = short.scenes.slice(0, 2);
check('rejects fewer than three scenes', !validateStoryboard(short, 'script').ok);

// --- the model sees the same contract the validator enforces ----------------

const tool = toolInputSchema() as { properties?: Record<string, unknown> };
check('tool schema generates', Boolean(tool.properties?.scenes && tool.properties?.meta));
const asText = JSON.stringify(tool);
check('tool schema hides pipeline-owned durationMs', !asText.includes('durationMs'));
check('tool schema hides pipeline-owned clipId', !asText.includes('clipId'));
check('tool schema exposes the mood vocabulary', BROLL_MOODS.every((m) => asText.includes(m)));

console.log(failed ? `\n${failed} check(s) failed` : `\nall passed`);
process.exit(failed ? 1 : 0);
