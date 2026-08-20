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

export function SceneView({ scene, active, progress = null }: SceneViewProps): React.ReactElement {
  switch (scene.type) {
    case 'title':
      return <TitleScene scene={scene} active={active} />;
    case 'bullets':
      return <BulletsScene scene={scene} active={active} progress={progress} />;
    case 'diagram':
      return <DiagramScene scene={scene} active={active} progress={progress} />;
    case 'compare':
      return <CompareScene scene={scene} active={active} />;
    case 'code':
      return <CodeScene scene={scene} active={active} />;
    case 'outro':
      return <OutroScene scene={scene} active={active} />;
    default: {
      // Compile-time exhaustiveness. Reachable at runtime only if the backend sends a
      // type this build has never heard of, which is a deploy skew, not a viewer error.
      const unreachable: never = scene;
      return <UnsupportedScene type={(unreachable as { type?: string }).type} active={active} />;
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
