'use client';

/**
 * Two to five items. These are read by the eye while the narration is heard, so each
 * one is a numbered panel row — unmistakably a list, and nothing like the caption bar
 * the feed renders at the bottom of the frame.
 *
 * The number is the signal, not the colour: it survives a light theme and reads out
 * loud as a list position.
 *
 * When active in the reel, the rows enter one at a time across the first ~80% of the
 * scene's duration, matching the rendered MP4's build-up. Reduced-motion viewers get
 * the whole list at once — the global 0.01ms rule crushes the animation but not its
 * delay, so a delayed `backwards` fill would otherwise hide rows for seconds.
 */

import { usePrefersReducedMotion } from '@/components/feed/useReel';
import { sceneDurationMs } from '@/lib/api';
import type { BulletsScene as BulletsSceneData } from '@/lib/storyboard.types';
import { SceneShell, TEXT_SHADOW } from './SceneShell';

/** Contract allows 2–5. Slice defensively so a bad payload cannot overflow the frame. */
const MAX_BULLETS = 5;

export function BulletsScene({
  scene,
  active,
  progress = null,
}: {
  scene: BulletsSceneData;
  active: boolean;
  /** Narration audio position, 0..1, or null for no audio to follow. See SceneView. */
  progress?: number | null;
}) {
  const reducedMotion = usePrefersReducedMotion();
  const bullets = scene.bullets.slice(0, MAX_BULLETS);
  const animate = active && !reducedMotion;
  const stepMs = (sceneDurationMs(scene) * 0.8) / Math.max(bullets.length, 1);

  // With real narration audio, a row appears as the voice reaches it rather than on a
  // blind stagger. Monotonic for free: the fraction only moves forward within a scene,
  // and a new scene is a new list. Opacity, not display, so the rows do not reflow in.
  const audioDriven = animate && progress !== null;
  const shown = audioDriven ? Math.floor(progress * bullets.length) + 1 : bullets.length;

  return (
    <SceneShell cite={scene.cite} active={active}>
      <h2
        className={`text-balance text-[22px] font-bold leading-tight tracking-[-0.02em] text-white ${TEXT_SHADOW}`}
      >
        {scene.heading}
      </h2>

      <ul className="flex flex-col gap-2">
        {bullets.map((bullet, i) => (
          <li
            key={`${i}-${bullet}`}
            className={`panel flex items-start gap-2.5 px-3 py-2.5 ${
              animate && !audioDriven ? 'animate-fade-in [animation-fill-mode:backwards]' : ''
            }`}
            style={
              audioDriven
                ? { opacity: i < shown ? 1 : 0, transition: 'opacity 400ms ease' }
                : animate
                  ? { animationDelay: `${Math.round(120 + i * stepMs)}ms` }
                  : undefined
            }
          >
            <span
              aria-hidden="true"
              className="mt-px flex size-5 shrink-0 items-center justify-center rounded-md border border-brand-500/40 bg-brand-500/20 font-mono text-[11px] font-semibold text-brand-300"
            >
              {i + 1}
            </span>
            <span className="text-balance text-sm font-medium leading-snug text-neutral-50">
              {bullet}
            </span>
          </li>
        ))}
      </ul>
    </SceneShell>
  );
}
