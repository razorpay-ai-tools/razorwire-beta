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

import { useEffect, useRef, useState } from 'react';
import { usePrefersReducedMotion } from '@/components/feed/useReel';
import { Icon } from '@/components/ui';
import { sceneDurationMs } from '@/lib/api';
import type { DiagramScene as DiagramSceneData } from '@/lib/storyboard.types';
import { parseMermaidNodes } from './mermaid-nodes';
import { SceneShell, TEXT_SHADOW } from './SceneShell';

/**
 * Matches globals.css. mermaid inlines these into the SVG, so the tokens must be
 * literal hex — a `var(--color-brand-500)` here would not resolve inside the
 * generated markup. Values are the logo-sampled brand-500 and Blade blueGrayDark,
 * so they must be updated together with the @theme block.
 */
const THEME_VARIABLES = {
  fontFamily: 'var(--font-mono)',
  fontSize: '14px',
  background: 'transparent',
  primaryColor: '#1f2123',
  primaryBorderColor: '#0364fa',
  primaryTextColor: '#eaebeb',
  secondaryColor: '#1f2123',
  secondaryBorderColor: '#0364fa',
  secondaryTextColor: '#eaebeb',
  tertiaryColor: '#1f2123',
  tertiaryBorderColor: '#0364fa',
  tertiaryTextColor: '#eaebeb',
  mainBkg: '#1f2123',
  nodeBorder: '#0364fa',
  nodeTextColor: '#eaebeb',
  lineColor: '#0364fa',
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

export function DiagramScene({
  scene,
  active,
  progress = null,
}: {
  scene: DiagramSceneData;
  active: boolean;
  /** Narration audio position, 0..1, or null for no audio to follow. See SceneView. */
  progress?: number | null;
}) {
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const nodes = parseMermaidNodes(scene.mermaid);
  const svgHostRef = useRef<HTMLDivElement>(null);
  const revealRef = useRef<Reveal | null>(null);
  const reducedMotion = usePrefersReducedMotion();

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

  // Progressive build-up, matching the rendered MP4: nodes appear in declaration
  // order, an edge (and its label) once both endpoints are visible. Runs only for
  // the active scene in the reel; the Spec/desktop preview (active=false) and
  // reduced-motion viewers get the finished diagram immediately.
  //
  // `audioDriven`, not `progress`, in the deps: this effect stages the SVG once per
  // diagram, and re-running it four times a second would restart every transition.
  // The effect below is what follows the voice.
  const audioDriven = progress !== null;
  useEffect(() => {
    if (!svg || !active || reducedMotion) return;
    const svgEl = svgHostRef.current?.querySelector('svg');
    if (!svgEl) return;

    const reveal = hideForReveal(svgEl);
    if (!reveal) return;
    // No audio position to follow: stagger blind across the scene, as before.
    if (!audioDriven) revealOnTimer(svgEl, reveal, sceneDurationMs(scene));
    revealRef.current = reveal;

    return () => {
      revealRef.current = null;
      for (const { el } of reveal.staged) {
        el.style.opacity = '';
        el.style.transition = '';
      }
    };
  }, [svg, active, reducedMotion, scene, audioDriven]);

  /*
   * Follow the voice. `svg` is in the deps as well as `progress` so that the first
   * fraction is applied in the same commit that stages the diagram — effects run in
   * declaration order, so the ref is already set — instead of leaving an empty panel
   * until the next `timeupdate`.
   */
  useEffect(() => {
    const reveal = revealRef.current;
    if (!reveal || progress === null) return;
    revealUpTo(reveal, progress);
  }, [progress, svg]);

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
              ref={svgHostRef}
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

/** A staged diagram: every group that participates, and which step reveals it. */
type Reveal = { staged: { el: SVGGraphicsElement; step: number }[]; steps: number };

/**
 * Stage a reveal over the live SVG, ported from the renderer's _REVEAL_JS
 * (backend/app/render/html.py) — same id parsing, CSS transitions instead of
 * screenshot steps.
 *
 * mermaid v11 node ids look like `<prefix>-flowchart-A-0`; edge ids encode both
 * endpoints as `<prefix>-L_A_B_0`. Node names may contain underscores, so every
 * split is tried until both halves are known nodes. Anything unparseable stays
 * visible rather than never appearing. Opacity only — a CSS transform would
 * override the SVG `transform` attribute mermaid positions these groups with.
 *
 * Everything is hidden on return, and the browser has been forced to commit that
 * hidden state, so the caller's first reveal actually transitions instead of
 * appearing instantly. Returns undefined for a diagram not worth animating.
 */
function hideForReveal(svgEl: SVGSVGElement): Reveal | undefined {
  const nodeEls = Array.from(svgEl.querySelectorAll<SVGGraphicsElement>('.node'));
  if (nodeEls.length < 2) return;
  const ids = nodeEls.map((el) => /flowchart-(.+)-\d+$/.exec(el.id)?.[1]);
  if (ids.some((id) => !id)) return; // unparseable ids: no reveal, one still
  const stepOf = new Map(ids.map((id, i) => [id as string, i]));

  const staged: { el: SVGGraphicsElement; step: number }[] = nodeEls.map((el, i) => ({
    el,
    step: i,
  }));

  const edges = Array.from(svgEl.querySelectorAll<SVGGraphicsElement>('.flowchart-link'));
  const labels = Array.from(svgEl.querySelectorAll<SVGGraphicsElement>('.edgeLabel'));
  edges.forEach((edge, i) => {
    const joined = /(?:^|-)L_(.+)_\d+$/.exec(edge.id)?.[1];
    let step: number | undefined;
    if (joined) {
      for (let cut = 1; cut < joined.length - 1; cut += 1) {
        if (joined[cut] !== '_') continue;
        const a = stepOf.get(joined.slice(0, cut));
        const b = stepOf.get(joined.slice(cut + 1));
        if (a !== undefined && b !== undefined) {
          step = Math.max(a, b);
          break;
        }
      }
    }
    if (step === undefined) return; // unparseable edge stays always visible
    staged.push({ el: edge, step });
    // .edgeLabel elements come in the same order as .flowchart-link elements.
    if (labels[i]) staged.push({ el: labels[i], step });
  });

  for (const { el } of staged) {
    el.style.opacity = '0';
    el.style.transition = 'opacity 400ms ease';
  }
  // Commit the hidden state, so a reveal in this same tick actually transitions.
  void svgEl.getBoundingClientRect();

  return { staged, steps: nodeEls.length };
}

/**
 * Reveal everything up to the step the voice has reached.
 *
 * Only ever sets opacity to 1, so it is monotonic and idempotent by construction: a
 * seek backwards, a re-render on the same fraction, or two ticks inside one step all
 * leave the diagram alone rather than blinking a node back out.
 */
function revealUpTo({ staged, steps }: Reveal, fraction: number): void {
  const upTo = Math.floor(fraction * steps);
  for (const { el, step } of staged) {
    if (step <= upTo) el.style.opacity = '1';
  }
}

/**
 * The no-audio fallback: stagger blind across the first ~80% of the scene, like the
 * MP4's capture steps. Delays on the transitions rather than a timer, so pausing is
 * the only thing this cannot follow — which is exactly the behaviour it replaces.
 */
function revealOnTimer(svgEl: SVGSVGElement, { staged, steps }: Reveal, durationMs: number): void {
  const stepMs = (durationMs * 0.8) / steps;
  for (const { el, step } of staged) {
    el.style.transition = `opacity 400ms ease ${Math.round(step * stepMs)}ms`;
  }
  void svgEl.getBoundingClientRect();
  for (const { el } of staged) el.style.opacity = '1';
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
