/**
 * Narration pacing, without a browser.
 *
 * These two decisions are the whole difference between a reel that reads along with
 * you and one that talks over itself, and both are pure so they can be checked by
 * `node src/components/feed/__narration-check.mts` rather than by watching a video.
 */

/** Speaking rates offered in the UI. 1 is the synthesizer's own idea of normal. */
export const NARRATION_RATES = [0.85, 1, 1.25, 1.5] as const;

export type NarrationRate = (typeof NARRATION_RATES)[number];

/** Next rate in the cycle, wrapping. An unknown rate falls back to the first. */
export function nextRate(current: number): NarrationRate {
  const at = (NARRATION_RATES as readonly number[]).indexOf(current);
  return NARRATION_RATES[(at + 1) % NARRATION_RATES.length];
}

/**
 * What finishing the current caption means: another line of this scene, or the next
 * scene.
 *
 * A scene with no captions — narration is empty — has nothing to say, so it moves on
 * rather than waiting for a voice that will never speak.
 */
export function advanceTarget(line: number, captionCount: number): 'line' | 'scene' {
  return line < captionCount - 1 ? 'line' : 'scene';
}

/**
 * Rewrite a caption into something a synthesizer can say like a person.
 *
 * Spec prose is full of things TTS mangles, and every one of them is what makes the
 * voice sound like a machine reading a config file:
 *
 *  - `block_fund` came out as "block underscore fund".
 *  - `pg-router` came out as "pig router" or spelled the hyphen.
 *  - `UPI` came out as "oopy"; `SBMD` as "sibmid".
 *  - Backticks and asterisks were read aloud as words in some voices.
 *
 * A comma after a colon is deliberate: it buys a beat before a list, which is the
 * single cheapest thing that makes a sentence sound spoken rather than printed.
 *
 * Pure, so `__narration-check.mts` can hold it to all of the above.
 */
export function speakableText(text: string): string {
  return (
    text
      // Code punctuation first: it is decoration in prose and noise in speech.
      .replace(/[`*_]+/g, ' ')
      // Hyphenated identifiers, but not a dash between words used as punctuation.
      .replace(/(\w)-(\w)/g, '$1 $2')
      // Spell out acronyms. An all-caps run of two to five letters is an initialism in
      // this corpus — UPI, SBMD, OTM, NPCI, MCC, PG — and every voice does better with
      // "U P I" than with its own guess at a pronunciation.
      .replace(/\b[A-Z]{2,5}\b/g, (word) => word.split('').join(' '))
      // A colon introduces a list; a comma there is where a person would breathe.
      .replace(/:\s*/g, ', ')
      .replace(/\s{2,}/g, ' ')
      .trim()
  );
}

/**
 * The best voice available, or null to let the browser choose.
 *
 * Order matters more than it looks: the default voice on macOS Chrome is a compact
 * system voice that sounds like a lift announcement, while Samantha, Ava and the Google
 * voices are the neural ones people describe as human. Preferring a named voice is the
 * difference between "a robot read my spec" and "someone explained my spec".
 *
 * Local services are preferred among equals — a network voice adds a beat of latency at
 * every caption, and the reel now advances on the voice finishing, so that latency
 * would show up as a stutter between lines.
 */
const PREFERRED_VOICES = [
  /Ava.*Premium/i,
  /Samantha/i,
  /Serena.*Premium/i,
  /Google US English/i,
  /Google UK English Female/i,
  /Microsoft (Aria|Jenny|Guy)/i,
];


export function pickVoice<T extends { name: string; lang: string; localService?: boolean }>(
  voices: readonly T[],
): T | null {
  const english = voices.filter((voice) => voice.lang.toLowerCase().startsWith('en'));
  if (english.length === 0) return null;

  for (const pattern of PREFERRED_VOICES) {
    const matches = english.filter((voice) => pattern.test(voice.name));
    if (matches.length > 0) {
      return matches.find((voice) => voice.localService) ?? matches[0];
    }
  }
  return english.find((voice) => voice.localService) ?? english[0];
}
