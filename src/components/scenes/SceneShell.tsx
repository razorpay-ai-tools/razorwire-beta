/**
 * The shared 9:16 frame for every scene template.
 *
 * One shell, six templates. It owns three things the templates must not disagree
 * about: the safe area, where the citation chip sits, and the entry animation.
 *
 * It deliberately does NOT render the background video, the scrim, the caption bar
 * or the progress rail — the feed owns all four. Templates render over arbitrary
 * moving footage, so text either sits on a `panel` or carries TEXT_SHADOW.
 */

import type { ReactNode } from 'react';
import { CitationChip } from '@/components/ui';

/**
 * Contrast for text that can't sit on a panel (headings, the title card).
 * Two shadows: a tight one for edge definition against light footage, a wide
 * soft one to darken whatever is immediately behind the glyphs.
 */
export const TEXT_SHADOW =
  '[text-shadow:0_1px_3px_rgb(0_0_0/0.95),0_6px_22px_rgb(0_0_0/0.7)]';

export interface SceneShellProps {
  /**
   * Rendered as a chip only when present. Title and outro pass nothing — they make
   * no factual claim, so a chip there would invent a citation.
   */
  cite?: string;
  /** Drives the entry animation. The feed sets this for the visible scene. */
  active: boolean;
  /** Title and outro centre everything and take the extra breathing room. */
  centered?: boolean;
  children: ReactNode;
}

export function SceneShell({ cite, active, centered = false, children }: SceneShellProps) {
  return (
    <div className="scene-safe flex h-full w-full flex-col">
      {/*
       * The chip leads the scene rather than trailing it. Below the content it landed
       * on the author row, because the bottom of the safe area is exactly where the
       * feed's metadata begins. Above the content it also reads better: it says what
       * you are about to be shown, and it is adjacent to the scene counter.
       */}
      {cite ? <CitationChip cite={cite} className="mb-3 shrink-0 self-start" /> : null}
      <div
        className={`flex min-h-0 flex-1 flex-col justify-center ${
          centered ? 'items-center gap-5 text-center' : 'gap-3'
        } ${active ? 'animate-fade-in' : ''}`}
      >
        {children}
      </div>
    </div>
  );
}
