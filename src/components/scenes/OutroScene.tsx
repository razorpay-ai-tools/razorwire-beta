/**
 * The ask. No citation chip — an outro makes no claim about the source.
 *
 * When there is a url the CTA text IS the button, which is the one thing a viewer is
 * meant to do here. The url is validated before it becomes an href: this data comes
 * off a model-driven pipeline, and `javascript:` in an href is a live XSS. Anything
 * that is not http(s) degrades to plain text rather than a link.
 */

import type { OutroScene as OutroSceneData } from '@/lib/storyboard.types';
import { Icon } from '@/components/ui';
import { SceneShell, TEXT_SHADOW } from './SceneShell';

function httpHost(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.host : null;
  } catch {
    return null;
  }
}

export function OutroScene({ scene, active }: { scene: OutroSceneData; active: boolean }) {
  const host = scene.url ? httpHost(scene.url) : null;

  return (
    <SceneShell active={active} centered>
      {host && scene.url ? (
        <>
          <p
            className={`font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-neutral-300 ${TEXT_SHADOW}`}
          >
            Next step
          </p>

          <a
            href={scene.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex max-w-full items-center justify-center gap-2 rounded-2xl bg-brand-500 px-5 py-3.5 text-[15px] font-semibold text-white shadow-lg shadow-brand-700/40 transition hover:bg-brand-600"
          >
            <Icon name="doc" label={null} className="size-4 shrink-0" />
            <span className="line-clamp-2 text-left">{scene.cta}</span>
            <span className="sr-only">(opens in a new tab)</span>
          </a>

          <p className={`font-mono text-[11px] text-neutral-300 ${TEXT_SHADOW}`}>{host}</p>
        </>
      ) : (
        <h2
          className={`w-full max-w-[22ch] text-balance text-2xl font-bold leading-tight tracking-[-0.03em] text-white ${TEXT_SHADOW}`}
        >
          {scene.cta}
        </h2>
      )}
    </SceneShell>
  );
}
