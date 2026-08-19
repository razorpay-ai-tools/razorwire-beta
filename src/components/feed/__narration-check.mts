/**
 * Self-check for narration pacing. Run: `node src/components/feed/__narration-check.mts`
 *
 * Two things here can strand a reel and neither shows up in `tsc`:
 *   1. `advanceTarget` deciding "another line" on the last line, which would sit on the
 *      final caption of a scene forever now that the voice, not a timer, advances it.
 *   2. `nextRate` failing to wrap, or not recovering from a rate that is not in the
 *      list — the speed button would stop responding.
 *
 * Also walks a real fixture scene end to end, because the interesting case is not one
 * decision but the sequence of them: every caption spoken exactly once, then the scene.
 */

import assert from 'node:assert/strict';
import storyboard from '../../lib/fixtures/otm-rearch.storyboard.json' with { type: 'json' };
import { NARRATION_RATES, advanceTarget, nextRate, pickVoice, speakableText } from './narration.ts';

// 1. Line vs scene, at the edges.
assert.equal(advanceTarget(0, 3), 'line', 'first of three captions should advance to a line');
assert.equal(advanceTarget(1, 3), 'line');
assert.equal(advanceTarget(2, 3), 'scene', 'last caption must hand over to the next scene');
assert.equal(advanceTarget(0, 1), 'scene', 'a single caption is also the last one');
assert.equal(advanceTarget(0, 0), 'scene', 'a silent scene must not wait for a voice');

// 2. The rate cycle wraps, and recovers from a value that is not in the list.
let rate: number = NARRATION_RATES[0];
const seen = new Set<number>();
for (let i = 0; i < NARRATION_RATES.length; i += 1) {
  seen.add(rate);
  rate = nextRate(rate);
}
assert.equal(seen.size, NARRATION_RATES.length, 'the cycle must visit every rate');
assert.equal(rate, NARRATION_RATES[0], 'and wrap back to the start');
assert.equal(nextRate(99), NARRATION_RATES[0], 'an unknown rate falls back to the first');

// 3. A real scene's captions are each spoken once, then the reel moves on.
//    Mirrors `captionsFor` in lib/api.ts, which cannot be imported here — it lives in a
//    module that pulls in the browser client.
const sentences = (narration: string) =>
  narration
    .split(/(?<=[.!?])\s+/)
    .map((line) => line.trim())
    .filter(Boolean);

const scene = (storyboard.scenes as { narration: string }[])[1];
const captions = sentences(scene.narration);
assert.ok(captions.length > 1, 'fixture scene 1 should split into several captions');

let line = 0;
let steps = 0;
while (advanceTarget(line, captions.length) === 'line') {
  line += 1;
  steps += 1;
  assert.ok(steps <= captions.length, 'advancing must terminate, not loop on a caption');
}
assert.equal(line, captions.length - 1, 'every caption is reached before the scene changes');

// 4. The rewrites that decide whether it sounds like a person or a config file.
assert.equal(speakableText('block_fund is set'), 'block fund is set', 'no "underscore"');
assert.equal(speakableText('pg-router decides'), 'pg router decides', 'no spelled hyphen');
assert.equal(speakableText('UPI and SBMD'), 'U P I and S B M D', 'initialisms are spelled out');
assert.equal(speakableText('`code` and *bold*'), 'code and bold', 'markup is not read aloud');
assert.equal(speakableText('Three things: one, two'), 'Three things, one, two', 'colon becomes a beat');
assert.ok(!/\s{2,}/.test(speakableText('a  --  b')), 'no runs of whitespace survive');
// A lowercase word must survive untouched — the acronym rule is not allowed to be greedy.
assert.equal(speakableText('the mandate expires'), 'the mandate expires');

// 5. Voice preference: a named neural voice beats the default, local beats network,
//    and a machine with no English voice must fall back to the browser's own choice.
const voices = [
  { name: 'Albert', lang: 'en-US', localService: true },
  { name: 'Google US English', lang: 'en-US', localService: false },
  { name: 'Samantha', lang: 'en-US', localService: true },
  { name: 'Amélie', lang: 'fr-FR', localService: true },
];
assert.equal(pickVoice(voices)?.name, 'Samantha', 'preference order must win over list order');
assert.equal(pickVoice([voices[0], voices[3]])?.name, 'Albert', 'falls back to any English voice');
assert.equal(pickVoice([voices[3]]), null, 'no English voice means let the browser decide');

console.log(
  `ok — narration sound: ${captions.length} captions walked, ${NARRATION_RATES.length} rates cycle, speech rewrites hold`,
);
