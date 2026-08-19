'use client';

/**
 * The voice on a generated reel.
 *
 * There is no audio track on this path, so narration is the browser's speech
 * synthesizer. Two things make it read along with the viewer rather than talk over
 * the top of them:
 *
 *  1. It speaks the caption that is on screen, one line at a time. Previously one
 *     utterance covered a whole scene while the captions advanced on a character-count
 *     estimate, so the voice and the words drifted apart within a sentence or two.
 *  2. `onDone` fires when the voice finishes the line, so the reel is paced by the
 *     speech instead of by a timer. A slow voice, a fast voice and a changed rate all
 *     stay in sync for free — see `useReel`, whose timer stands down while this runs.
 *
 * Muted is the default, because browsers refuse unmuted autoplay. Muted means the
 * timer paces the reel; exactly one of the two clocks is ever running.
 */

import { useEffect, useRef } from 'react';
import { pickVoice, speakableText } from './narration';

/**
 * Chrome reports an empty voice list for a moment after load, and a `speak()` in that
 * window is dropped with no error and no sound — the reported "I pressed unmute and
 * nothing happened, then it worked the second time".
 *
 * The timeout matters: browsers that already have voices never fire `voiceschanged`,
 * and one that has none (a bare Linux box) would otherwise wait forever.
 */
const VOICES_READY_TIMEOUT_MS = 1200;

/**
 * How long to wait for a voice to say a line before giving up on it.
 *
 * The reel now advances on speech ending, so a synthesizer that neither speaks nor
 * errors — a machine with no installed voices, a tab throttled mid-utterance — would
 * park the reel on one caption forever. Twice the expected reading time plus a few
 * seconds is generous enough never to cut off a real voice.
 */
function watchdogMs(text: string, rate: number): number {
  const words = text.trim().split(/\s+/).length;
  const expected = (words / ((160 * rate) / 60)) * 1000;
  return expected * 2 + 3000;
}

function whenVoicesReady(synth: SpeechSynthesis): Promise<void> {
  if (synth.getVoices().length > 0) return Promise.resolve();

  return new Promise((resolve) => {
    const done = () => {
      window.clearTimeout(timer);
      synth.removeEventListener('voiceschanged', done);
      resolve();
    };
    const timer = window.setTimeout(done, VOICES_READY_TIMEOUT_MS);
    synth.addEventListener('voiceschanged', done);
  });
}

interface NarrationOptions {
  /** The line to speak. Null or empty says nothing. */
  text: string | null;
  /** False when muted, paused, off screen, or not a generated post. */
  enabled: boolean;
  rate: number;
  /** Called when the line has been spoken, or when speaking it failed. */
  onDone: () => void;
}

export function useNarration({ text, enabled, rate, onDone }: NarrationOptions): void {
  // Held in a ref so a new callback identity does not restart the sentence.
  const onDoneRef = useRef(onDone);
  useEffect(() => {
    onDoneRef.current = onDone;
  }, [onDone]);

  useEffect(() => {
    const synth = typeof window === 'undefined' ? undefined : window.speechSynthesis;
    if (!synth || !enabled || !text) return;

    // Narrowed once, so the nested function below keeps the types.
    const speech = synth;
    const line = text;

    let cancelled = false;
    let watchdog = 0;

    function finish() {
      if (cancelled) return;
      window.clearTimeout(watchdog);
      onDoneRef.current();
    }

    function startSpeaking() {
      if (cancelled) return;

      const utterance = new SpeechSynthesisUtterance(speakableText(line));
      const voice = pickVoice(speech.getVoices());
      if (voice) utterance.voice = voice;
      utterance.rate = rate;
      // Slightly under the default. At 1.0 the neural voices land every sentence on the
      // same note, which is the thing that reads as synthetic more than the timbre does.
      utterance.pitch = 0.95;

      utterance.onend = finish;

      /*
       * An interruption is NOT the line finishing.
       *
       * Our own `cancel()` — on unmount, on a scene change, on the line before this one
       * — arrives here as `interrupted` or `canceled`. Treating those as an ending made
       * the reel advance through every caption in silence, one per frame: narration
       * visibly "happening" with nothing to hear. Any other error is a voice that truly
       * cannot say this line, and there the reel must move on rather than freeze.
       */
      utterance.onerror = (event) => {
        if (event.error === 'interrupted' || event.error === 'canceled') return;
        finish();
      };

      watchdog = window.setTimeout(finish, watchdogMs(line, rate));

      // Only clear the queue when there IS one. Chrome drops an utterance that is spoken
      // in the same tick as a `cancel()`, so an unconditional cancel here silenced the
      // very first line.
      if (speech.speaking || speech.pending) speech.cancel();
      if (speech.paused) speech.resume();
      speech.speak(utterance);
    }

    /*
     * Speak SYNCHRONOUSLY when the voice list is already populated, and only wait when
     * it is not. Safari treats `speak()` as needing user activation, and awaiting a
     * promise first — even an already-resolved one — puts the call in a later microtask
     * where that activation is gone, so the unmute click produced silence with no error.
     */
    if (speech.getVoices().length > 0) startSpeaking();
    else void whenVoicesReady(speech).then(startSpeaking);

    return () => {
      cancelled = true;
      window.clearTimeout(watchdog);
      speech.cancel();
    };
  }, [text, enabled, rate]);
}
