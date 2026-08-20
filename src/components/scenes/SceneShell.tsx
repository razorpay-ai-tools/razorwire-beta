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

/**
 * Clearance for the feed's action rail, which floats over the right edge of the frame.
 *
 * `scene-safe` pads 1.25rem inline, but the rail is ~56px wide, so wide scene content
 * (bullet panels, the compare panes, the code block) ran underneath the like and
 * comment buttons. Applied only when the scene is not centred: title and outro have
 * narrow, centre-aligned content that sits above the rail's vertical band, and padding
 * one side would visibly throw their centring off.
 */
const RAIL_CLEARANCE = 'pr-[4.75rem]';

export function SceneShell({ cite, active, centered = false, children }: SceneShellProps) {
  return (
    /*
     * The entry animation sits HERE, on the whole frame, not on the content column
     * below. It used to be on the column, which left the citation chip outside it: on
     * every scene change the chip snapped in while the content faded, so the two halves
     * of the same scene arrived at different times. One scene, one entrance.
     *
     * `SceneView` keys the template on the scene, which is what makes this replay for
     * every scene rather than only the first — a CSS animation runs on mount and never
     * again. Reduced motion needs nothing here: the global rule in globals.css crushes
     * the duration, so those viewers get the scene immediately.
     */
    <div
      className={`scene-safe flex h-full w-full flex-col ${centered ? '' : RAIL_CLEARANCE} ${
        active ? 'animate-fade-in' : ''
      }`}
    >
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
        }`}
      >
        {children}
      </div>
    </div>
  );
}
