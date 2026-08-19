'use client';

/**
 * Scene advance for a generated post.
 *
 * Two clocks, one timer. A scene holds for `sceneDurationMs`, and the captions
 * inside it split that time proportionally by character count (the documented
 * approximation — no measured audio exists on the browser-reel path). Rather than
 * scheduling every caption up front, each tick schedules only the next one, so
 * pause, scrub and unmount all collapse to a single `clearTimeout`.
 */

import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import { captionsFor, sceneDurationMs } from '@/lib/api';
import type { Scene } from '@/lib/storyboard.types';

/** Shortest a caption may hold, so a two-word sentence does not flash past. */
const MIN_CAPTION_MS = 700;

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)';

function subscribeToMotionPreference(onChange: () => void): () => void {
  const query = window.matchMedia(REDUCED_MOTION);
  query.addEventListener('change', onChange);
  return () => query.removeEventListener('change', onChange);
}

/**
 * A media query is an external store, so it is read as one. The server snapshot is
 * `false` because `matchMedia` does not exist there; React reconciles on hydration
 * without a mismatch.
 */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeToMotionPreference,
    () => window.matchMedia(REDUCED_MOTION).matches,
    () => false,
  );
}

export interface Reel {
  index: number;
  count: number;
  scene: Scene | undefined;
  /** Current caption line, or null for a scene whose narration is empty. */
  caption: string | null;
  playing: boolean;
  reducedMotion: boolean;
  setPlaying: (playing: boolean) => void;
  next: () => void;
  prev: () => void;
}

export function useReel(scenes: Scene[], active: boolean): Reel {
  const count = scenes.length;
  const [index, setIndex] = useState(0);
  const [line, setLine] = useState(0);
  const [wasActive, setWasActive] = useState(active);
  const reducedMotion = usePrefersReducedMotion();

  // Auto-advancing content is motion. Default to paused for anyone who asked for
  // less of it; the play control still overrides it either way.
  const [playChoice, setPlayChoice] = useState<boolean | null>(null);
  const playing = playChoice ?? !reducedMotion;

  // Scrolling away resets to scene 0, so a post is never half-watched next time.
  // React's documented adjust-state-on-prop-change pattern: doing this in an effect
  // would paint the stale scene for a frame first.
  if (wasActive !== active) {
    setWasActive(active);
    if (!active) {
      setIndex(0);
      setLine(0);
    }
  }

  const scene = scenes[index];
  const captions = useMemo(() => (scene ? captionsFor(scene) : []), [scene]);

  const step = useCallback(
    (delta: number) => {
      setLine(0);
      setIndex((current) => (count === 0 ? 0 : (((current + delta) % count) + count) % count));
    },
    [count],
  );

  const next = useCallback(() => step(1), [step]);
  const prev = useCallback(() => step(-1), [step]);

  useEffect(() => {
    if (!active || !playing || !scene) return;

    const weights = captions.map((text) => Math.max(text.length, 1));
    const total = weights.reduce((sum, weight) => sum + weight, 0);
    const hold =
      total > 0
        ? sceneDurationMs(scene) * ((weights[line] ?? total) / total)
        : sceneDurationMs(scene);

    const timer = window.setTimeout(
      () => {
        if (line < captions.length - 1) setLine((current) => current + 1);
        else next();
      },
      Math.max(MIN_CAPTION_MS, hold),
    );

    return () => window.clearTimeout(timer);
  }, [active, playing, scene, captions, line, next]);

  return {
    index,
    count,
    scene,
    caption: captions[line] ?? null,
    playing,
    reducedMotion,
    setPlaying: setPlayChoice,
    next,
    prev,
  };
}
