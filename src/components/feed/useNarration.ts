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

import { useEffect, useRef, useState } from 'react';
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

/**
 * Unlock speech inside a user gesture.
 *
 * Safari and iOS only allow speech that *starts* in a gesture. Ours starts in an effect
 * a tick after the click that unmuted, which is outside it, so the whole reel played
 * silently with no error anywhere. Speaking one empty utterance from inside the click
 * itself is what unlocks the queue for everything after it. Chrome does not need this
 * and ignores it.
 *
 * Exported for the mute control, which owns the only gesture we are guaranteed.
 */
export function primeSpeech(): void {
  const synth = typeof window === 'undefined' ? undefined : window.speechSynthesis;
  if (!synth) return;
  try {
    synth.speak(new SpeechSynthesisUtterance(''));
    if (synth.paused) synth.resume();
  } catch {
    // A browser that refuses an empty utterance is not a reason to block unmuting.
  }
}

/** Dev-only trace. The failure modes here are all invisible: no error, no sound. */
function trace(...parts: unknown[]): void {
  if (process.env.NODE_ENV !== 'production') console.debug('[narration]', ...parts);
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

/**
 * How many speech voices this browser has, live.
 *
 * Zero is a real state, not a loading state: Chromium builds without the TTS component,
 * a Linux box with no speech-dispatcher, and a locked-down profile all report an empty
 * list forever. Narration then produces no sound and no error, which is indistinguishable
 * from a bug — so the UI says so instead of pretending. Counted here rather than inside
 * `useNarration` because the notice has to be visible before anything is spoken.
 */
export function useSpeechVoiceCount(): number {
  const [count, setCount] = useState<number>(0);

  useEffect(() => {
    const synth = window.speechSynthesis;
    if (!synth) return;

    const read = () => setCount(synth.getVoices().length);
    read();
    synth.addEventListener('voiceschanged', read);
    // Chrome populates the list asynchronously and does not always fire the event.
    const timer = window.setTimeout(read, VOICES_READY_TIMEOUT_MS);

    return () => {
      window.clearTimeout(timer);
      synth.removeEventListener('voiceschanged', read);
    };
  }, []);

  return count;
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
      const voices = speech.getVoices();
      const voice = pickVoice(voices);
      if (voice) utterance.voice = voice;

      trace('speak', {
        voices: voices.length,
        using: voice ? `${voice.name} (${voice.localService ? 'local' : 'network'})` : 'browser default',
        rate,
        speaking: speech.speaking,
        pending: speech.pending,
        paused: speech.paused,
        text: speakableText(line).slice(0, 60),
      });
      utterance.onstart = () => trace('started');
      utterance.rate = rate;
      // Slightly under the default. At 1.0 the neural voices land every sentence on the
      // same note, which is the thing that reads as synthetic more than the timbre does.
      utterance.pitch = 0.95;

      utterance.onend = () => {
        trace('ended');
        finish();
      };

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
        trace('error', event.error);
        if (event.error === 'interrupted' || event.error === 'canceled') return;
        finish();
      };

      watchdog = window.setTimeout(() => {
        trace('watchdog fired — the voice never spoke and never errored');
        finish();
      }, watchdogMs(line, rate));

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
