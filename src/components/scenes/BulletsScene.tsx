/**
 * Two to five items. These are read by the eye while the narration is heard, so each
 * one is a numbered panel row — unmistakably a list, and nothing like the caption bar
 * the feed renders at the bottom of the frame.
 *
 * The number is the signal, not the colour: it survives a light theme and reads out
 * loud as a list position.
 */

import type { BulletsScene as BulletsSceneData } from '@/lib/storyboard.types';
import { SceneShell, TEXT_SHADOW } from './SceneShell';

/** Contract allows 2–5. Slice defensively so a bad payload cannot overflow the frame. */
const MAX_BULLETS = 5;

export function BulletsScene({ scene, active }: { scene: BulletsSceneData; active: boolean }) {
  return (
    <SceneShell cite={scene.cite} active={active}>
      <h2
        className={`text-balance text-[22px] font-bold leading-tight tracking-[-0.02em] text-white ${TEXT_SHADOW}`}
      >
        {scene.heading}
      </h2>

      <ul className="flex flex-col gap-2">
        {scene.bullets.slice(0, MAX_BULLETS).map((bullet, i) => (
          <li
            key={`${i}-${bullet}`}
            className={`panel flex items-start gap-2.5 px-3 py-2.5 ${
              active ? 'animate-fade-in [animation-fill-mode:backwards]' : ''
            }`}
            style={active ? { animationDelay: `${120 + i * 110}ms` } : undefined}
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
