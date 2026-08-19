'use client';

/**
 * The differentiator: a real mermaid diagram, rendered in the browser.
 *
 * Three things make this safe to put in front of a viewer:
 *   1. mermaid is imported inside the effect, so it never enters the server bundle
 *      and never runs during SSR (it needs a DOM to measure text).
 *   2. A `cancelled` flag, because React 19 runs effects twice in development —
 *      without it the first pass can resolve last and paint a stale diagram.
 *   3. The node list is the fallback AND the pending state AND the screen-reader
 *      alternative. A failed render shows a readable list, never an error string.
 */

import { useEffect, useState } from 'react';
import { Icon } from '@/components/ui';
import type { DiagramScene as DiagramSceneData } from '@/lib/storyboard.types';
import { parseMermaidNodes } from './mermaid-nodes';
import { SceneShell, TEXT_SHADOW } from './SceneShell';

/**
 * Matches globals.css. mermaid inlines these into the SVG, so the tokens must be
 * literal hex — a `var(--color-brand-500)` here would not resolve inside the
 * generated markup. Values are Blade's azure.500 and blueGrayDark, so they must be
 * updated together with the @theme block.
 */
const THEME_VARIABLES = {
  fontFamily: 'var(--font-mono)',
  fontSize: '14px',
  background: 'transparent',
  primaryColor: '#1f2123',
  primaryBorderColor: '#1364f1',
  primaryTextColor: '#eaebeb',
  secondaryColor: '#1f2123',
  secondaryBorderColor: '#1364f1',
  secondaryTextColor: '#eaebeb',
  tertiaryColor: '#1f2123',
  tertiaryBorderColor: '#1364f1',
  tertiaryTextColor: '#eaebeb',
  mainBkg: '#1f2123',
  nodeBorder: '#1364f1',
  nodeTextColor: '#eaebeb',
  lineColor: '#1364f1',
  textColor: '#eaebeb',
  edgeLabelBackground: '#131415',
  clusterBkg: 'transparent',
  clusterBorder: '#3b3d40',
};

/** mermaid requires a DOM-unique id per render call. */
let renderSeq = 0;

/**
 * mermaid hard-codes a pixel width/height and an inline `max-width` on the root
 * <svg>. Left alone, a 7-node graph either overflows the frame or renders postage
 * stamp sized. Strip those three attributes off the ROOT TAG ONLY — the width and
 * height attributes on child <rect>s are the diagram itself — and let CSS bound it.
 */
function fitSvg(svg: string): string {
  return svg.replace(/<svg[^>]*>/, (tag) =>
    tag
      .replace(/\s(?:width|height|style)="[^"]*"/g, '')
      // Both dimensions at 100% plus `meet` letterboxes inside whatever box CSS gives
      // us. Width alone leaves height intrinsic, which is how a tall graph grew to
      // 919px inside an 844px viewport. mermaid's viewBox survives the strip above and
      // is what makes preserveAspectRatio work.
      .replace('<svg', '<svg width="100%" height="100%" preserveAspectRatio="xMidYMid meet"'),
  );
}

/**
 * `svg: null` means that source failed to render. The result carries the source it was
 * produced from so a scene whose mermaid has changed is derived as pending during
 * render — no reset setState at the top of the effect, so no cascading render and no
 * frame where a stale diagram is shown for new source.
 */
type Attempt = { src: string; svg: string | null };

export function DiagramScene({ scene, active }: { scene: DiagramSceneData; active: boolean }) {
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const nodes = parseMermaidNodes(scene.mermaid);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      const src = scene.mermaid;
      try {
        const { default: mermaid } = await import('mermaid');
        mermaid.initialize({
          startOnLoad: false,
          theme: 'dark',
          securityLevel: 'strict',
          flowchart: { useMaxWidth: true, htmlLabels: false, padding: 8 },
          themeVariables: THEME_VARIABLES,
        });
        renderSeq += 1;
        const { svg } = await mermaid.render(`rw-diagram-${renderSeq}`, src);
        if (!cancelled) setAttempt({ src, svg: fitSvg(svg) });
      } catch {
        // Deliberately swallowed. A viewer gets the node list; the source is in the doc.
        if (!cancelled) setAttempt({ src, svg: null });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [scene.mermaid]);

  const current = attempt?.src === scene.mermaid ? attempt : null;
  const svg = current?.svg ?? null;
  const failed = current !== null && current.svg === null;

  return (
    <SceneShell cite={scene.cite} active={active}>
      <h2
        className={`text-balance text-[22px] font-bold leading-tight tracking-[-0.02em] text-white ${TEXT_SHADOW}`}
      >
        {scene.heading}
      </h2>

      <div className="panel flex min-h-0 flex-1 items-center justify-center overflow-hidden p-3">
        {svg ? (
          <>
            <NodeList nodes={nodes} heading={scene.heading} srOnly />
            {/* A DEFINITE height, not max-h-full. `max-height: 100%` resolves against
                the parent's height, and this parent had none, so nothing clamped and a
                tall graph overflowed the frame. */}
            <div
              aria-hidden="true"
              className="flex h-full min-h-0 w-full items-center justify-center [&>svg]:h-full [&>svg]:w-full"
              dangerouslySetInnerHTML={{ __html: svg }}
            />
          </>
        ) : (
          <NodeList nodes={nodes} heading={scene.heading} failed={failed} />
        )}
      </div>
    </SceneShell>
  );
}

/**
 * The fallback, the pending state, and the accessible text alternative.
 *
 * Reads as a flow (step n of m, in source order) rather than a set, because that is
 * what the contract's graphs are. No mention of a failure: the viewer did not do
 * anything wrong and cannot fix it.
 */
function NodeList({
  nodes,
  heading,
  failed = false,
  srOnly = false,
}: {
  nodes: string[];
  heading: string;
  failed?: boolean;
  srOnly?: boolean;
}) {
  if (srOnly) {
    return (
      <p className="sr-only">
        {`Diagram: ${heading}. ${
          nodes.length ? `Nodes, in order: ${nodes.join(', ')}.` : 'No labelled nodes.'
        }`}
      </p>
    );
  }

  if (!nodes.length) {
    return (
      <p className={`text-center text-sm font-medium text-neutral-300 ${TEXT_SHADOW}`}>
        {failed ? heading : 'Drawing the diagram…'}
      </p>
    );
  }

  return (
    <ol className="flex w-full flex-col gap-1.5">
      {nodes.map((node, i) => (
        <li key={`${i}-${node}`} className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="flex size-5 shrink-0 items-center justify-center rounded-md border border-brand-500/40 bg-brand-500/20 font-mono text-[10px] font-semibold text-brand-300"
          >
            {i + 1}
          </span>
          <span className="truncate font-mono text-[13px] font-medium text-neutral-100">
            {node}
          </span>
          {i < nodes.length - 1 ? (
            /* Points down the list: this is a flow, not a set. */
            <Icon
              name="play"
              label={null}
              filled
              className="size-2.5 shrink-0 rotate-90 text-brand-400"
            />
          ) : null}
        </li>
      ))}
    </ol>
  );
}
