/**
 * The opening card. Most breathing room of any scene and no citation chip — a title
 * asserts nothing about the source document.
 */

import type { TitleScene as TitleSceneData } from '@/lib/storyboard.types';
import { SceneShell, TEXT_SHADOW } from './SceneShell';

export function TitleScene({ scene, active }: { scene: TitleSceneData; active: boolean }) {
  return (
    <SceneShell active={active} centered>
      <h1
        className={`w-full max-w-[20ch] text-balance text-3xl font-bold leading-[1.06] tracking-[-0.035em] text-white ${TEXT_SHADOW}`}
      >
        {scene.heading}
      </h1>

      {/* Anchors the stack when there is no sub, and separates the two when there is. */}
      <span aria-hidden="true" className="block h-0.5 w-10 rounded-full bg-brand-400/90" />

      {scene.sub ? (
        <p
          className={`w-full max-w-[28ch] text-pretty text-[15px] font-medium leading-snug text-neutral-200 ${TEXT_SHADOW}`}
        >
          {scene.sub}
        </p>
      ) : null}
    </SceneShell>
  );
}
