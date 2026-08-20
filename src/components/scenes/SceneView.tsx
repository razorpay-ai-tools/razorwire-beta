/**
 * The dispatcher. One scene in, one 9:16 frame of content out.
 *
 * The `never` assignment in the default branch is the point: add a seventh scene type
 * to the contract without adding a template here and this file stops compiling,
 * rather than shipping a blank frame into the middle of someone's reel.
 *
 * Renders scene CONTENT only. The feed owns the frame, the background video, the
 * scrim, the caption bar and the progress rail.
 */

import type { Scene } from '@/lib/storyboard.types';
import { BulletsScene } from './BulletsScene';
import { CodeScene } from './CodeScene';
import { CompareScene } from './CompareScene';
import { DiagramScene } from './DiagramScene';
import { OutroScene } from './OutroScene';
import { SceneShell, TEXT_SHADOW } from './SceneShell';
import { TitleScene } from './TitleScene';

export interface SceneViewProps {
  scene: Scene;
  /** true when this scene is the active one in the feed; drives entry animation */
  active: boolean;
  /**
   * How far through this scene's narration AUDIO the voice is, 0..1, or null when
   * there is no audio to follow (muted, or the Web Speech fallback, which reports no
   * position). The templates that build up piece by piece use it to reveal a piece as
   * the voice reaches it; null means fall back to staggering on a timer.
   */
  progress?: number | null;
}

/**
 * Identity of the scene being shown, as a React key.
 *
 * This is what makes the reel's scene change ANIMATE. The feed keeps SceneView mounted
 * and swaps `scene` underneath it, so two consecutive bullets scenes were the same
 * element in the same position: React reused the DOM, and SceneShell's entry animation
 * — a CSS animation, which only runs on mount — never fired again. Scenes therefore
 * snapped in. A key that changes with the scene remounts the template, and the fade
 * plays for every scene rather than only the first.
 *
 * `narration` is required on every scene by the contract and is what the scene is
 * about, so it identifies one. Two adjacent scenes that somehow shared a type and a
 * narration would simply not re-animate — no flicker, no double render.
 */
function sceneKey(scene: Scene): string {
  return `${scene.type}:${scene.narration}`;
}

export function SceneView({ scene, active, progress = null }: SceneViewProps): React.ReactElement {
  const key = sceneKey(scene);
  switch (scene.type) {
    case 'title':
      return <TitleScene key={key} scene={scene} active={active} />;
    case 'bullets':
      return <BulletsScene key={key} scene={scene} active={active} progress={progress} />;
    case 'diagram':
      return <DiagramScene key={key} scene={scene} active={active} progress={progress} />;
    case 'compare':
      return <CompareScene key={key} scene={scene} active={active} />;
    case 'code':
      return <CodeScene key={key} scene={scene} active={active} />;
    case 'outro':
      return <OutroScene key={key} scene={scene} active={active} />;
    default: {
      // Compile-time exhaustiveness. Reachable at runtime only if the backend sends a
      // type this build has never heard of, which is a deploy skew, not a viewer error.
      const unreachable: never = scene;
      return (
        <UnsupportedScene
          key={key}
          type={(unreachable as { type?: string }).type}
          active={active}
        />
      );
    }
  }
}

function UnsupportedScene({ type, active }: { type?: string; active: boolean }) {
  return (
    <SceneShell active={active} centered>
      <p className={`max-w-[24ch] text-balance text-base font-semibold text-neutral-200 ${TEXT_SHADOW}`}>
        This scene needs a newer version of the app.
      </p>
      <p className="font-mono text-[11px] text-neutral-400">{type ?? 'unknown scene type'}</p>
    </SceneShell>
  );
}
