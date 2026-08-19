/**
 * Self-check for the scene templates. Run: `node src/components/scenes/__check.mts`
 *
 * Two things can break silently and neither shows up in `tsc`:
 *   1. A scene type in a real storyboard with no `case` in the dispatcher. The `never`
 *      check catches a type added to the CONTRACT, but not the reverse mistake of a
 *      case that was renamed or deleted.
 *   2. The mermaid node parser, which is a regex over a language it does not parse.
 *      It is the only thing standing between a failed mermaid render and a blank frame.
 *
 * Reads SceneView.tsx as text on purpose: importing it would drag in React and mermaid
 * for what is a two-assertion check.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import storyboard from '../../lib/fixtures/otm-rearch.storyboard.json' with { type: 'json' };
import { parseMermaidNodes } from './mermaid-nodes.ts';

const read = (name: string) => readFileSync(new URL(name, import.meta.url), 'utf8');

const dispatcher = read('./SceneView.tsx');
const handled = new Set([...dispatcher.matchAll(/case '(\w+)':/g)].map((m) => m[1]));

// 1a. Every scene type the fixture actually contains has a template.
const scenes = storyboard.scenes as { type: string; mermaid?: string }[];
for (const scene of scenes) {
  assert.ok(handled.has(scene.type), `no template in SceneView for fixture scene '${scene.type}'`);
}

// 1b. And every type the contract declares, including ones the fixture happens to omit.
const declared = [...read('../../lib/storyboard.types.ts').matchAll(/type: '(\w+)'/g)].map(
  (m) => m[1],
);
assert.ok(declared.length >= 6, `expected 6+ scene types in the contract, found ${declared.length}`);
for (const type of declared) {
  assert.ok(handled.has(type), `no template in SceneView for contract scene type '${type}'`);
}
assert.deepEqual([...handled].sort(), [...new Set(declared)].sort(), 'dispatcher/contract drift');

// 2. The fallback parser, against the fixture's real diagram source.
const diagram = scenes.find((scene) => scene.type === 'diagram');
assert.ok(diagram?.mermaid, 'fixture has no diagram scene to check the parser against');
assert.deepEqual(parseMermaidNodes(diagram.mermaid), [
  'Edge',
  'pg-router',
  'CPS',
  'payments-upi',
  'payments-mandate',
  'mandate_setups', // [(cylinder)] shape — the one the fixture uses that a naive regex drops
]);

// Edge labels are where a regex most easily invents a node. `-->|yes|` must not become one.
assert.deepEqual(
  parseMermaidNodes('graph LR\n  A{Rearch?} -->|yes| B["pg-router"]\n  A -->|no| C(Monolith)'),
  ['Rearch?', 'pg-router', 'Monolith'],
);

console.log(`ok — ${handled.size} scene templates wired, mermaid fallback parser sound`);
