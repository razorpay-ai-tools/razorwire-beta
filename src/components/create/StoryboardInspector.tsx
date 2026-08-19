'use client';

/**
 * The audit view — the anti-hallucination proof, rendered.
 *
 * The spine is one narration paragraph and the citation that backs it, stacked on a
 * single rule so the pairing is the thing you read. Absence is stated too: a `bullets`,
 * `diagram`, `compare` or `code` scene with no `cite` is an unsupported claim and says
 * so; `title` and `outro` assert no fact and are marked as such rather than left blank.
 *
 * Sizes from its container — full screen on mobile, `md:w-96` side panel on desktop —
 * so no width is set at the root.
 */

import { useEffect, useRef } from 'react';
import { docHref } from '@/lib/api';
import type { Scene, SceneType, Storyboard } from '@/lib/storyboard.types';
import { CitationChip, Icon } from '@/components/ui';

/** Scene types the contract requires a `cite` on, because they state something. */
const FACTUAL: ReadonlySet<SceneType> = new Set(['bullets', 'diagram', 'compare', 'code']);

function headingOf(scene: Scene): string | null {
  if (scene.type === 'outro') return scene.cta;
  return scene.heading ?? null;
}

interface StoryboardInspectorProps {
  storyboard: Storyboard;
  /** Scene currently on screen in the player, when there is one. */
  currentIndex?: number;
}

export function StoryboardInspector({ storyboard, currentIndex }: StoryboardInspectorProps) {
  const { meta, source, scenes } = storyboard;
  const cited = scenes.filter((scene) => scene.cite).length;
  const unsupported = scenes.filter((scene) => !scene.cite && FACTUAL.has(scene.type)).length;
  const href = docHref(storyboard);

  const activeRef = useRef<HTMLLIElement | null>(null);

  // Keep the current scene in view when the player moves on.
  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: 'nearest' });
  }, [currentIndex]);

  return (
    <section
      className="flex h-full min-h-0 w-full flex-col border-neutral-800 bg-neutral-950 md:border-l"
      aria-label="Storyboard inspector"
    >
      <header className="shrink-0 border-b border-neutral-800 px-4 py-4">
        <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-brand-300">
          Storyboard
        </p>
        <h2 className="mt-1.5 text-base font-semibold leading-snug tracking-tight text-neutral-50">
          {meta.title}
        </h2>

        <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[11px] text-neutral-400">
          <span>
            {scenes.length} {scenes.length === 1 ? 'scene' : 'scenes'}
          </span>
          <span aria-hidden="true" className="text-neutral-700">
            ·
          </span>
          <span className="inline-flex items-center gap-1">
            <Icon name="quote" label={null} className="size-3 shrink-0" />
            {cited} of {scenes.length} cited
          </span>
          {unsupported > 0 ? (
            <>
              <span aria-hidden="true" className="text-neutral-700">
                ·
              </span>
              <span className="inline-flex items-center gap-1 text-warning">
                <Icon name="alert" label={null} className="size-3 shrink-0" />
                {unsupported} unsupported
              </span>
            </>
          ) : null}
        </p>

        {meta.tags.length > 0 ? (
          <ul className="mt-2.5 flex flex-wrap gap-1.5">
            {meta.tags.map((tag) => (
              <li
                key={tag}
                className="rounded-full border border-white/10 bg-neutral-900 px-2 py-0.5 font-mono text-[10px] text-neutral-300"
              >
                {tag}
              </li>
            ))}
          </ul>
        ) : null}

        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 inline-flex max-w-full items-center gap-2 rounded-xl border border-neutral-800 bg-neutral-900 px-3 py-2 text-xs font-medium text-neutral-200 transition hover:border-brand-500/50 hover:text-brand-200"
          >
            <Icon name="doc" label={null} className="size-3.5 shrink-0" />
            <span className="truncate">{source.title ?? source.docId ?? 'Open the source doc'}</span>
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        ) : (
          <p className="mt-3 flex items-start gap-2 text-[11px] leading-relaxed text-neutral-500">
            <Icon name="alert" label={null} className="mt-px size-3.5 shrink-0 text-warning" />
            <span>
              Generated from a topic, not a document. There is no source to check this against.
            </span>
          </p>
        )}
      </header>

      <ol className="min-h-0 flex-1 divide-y divide-neutral-800/70 overflow-y-auto">
        {scenes.map((scene, index) => {
          const current = index === currentIndex;
          const heading = headingOf(scene);
          return (
            <li
              key={index}
              ref={current ? activeRef : null}
              aria-current={current ? 'true' : undefined}
              className={`px-4 py-4 ${current ? 'bg-brand-500/10' : ''}`}
            >
              <div className="flex items-center gap-2">
                <span
                  className={`font-mono text-[11px] font-semibold ${current ? 'text-brand-200' : 'text-neutral-500'}`}
                >
                  {String(index + 1).padStart(2, '0')}
                </span>
                <span className="rounded-full border border-white/10 bg-neutral-900 px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-neutral-300">
                  {scene.type}
                </span>
                {current ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-brand-500 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-white">
                    <Icon name="play" label={null} className="size-2.5" filled />
                    On screen
                  </span>
                ) : null}
              </div>

              {heading ? (
                <p className="mt-2 text-sm font-semibold leading-snug text-neutral-100">{heading}</p>
              ) : null}

              {/* The spine: narration, then the citation that backs it, on one rule. */}
              <div
                className={`mt-2 border-l-2 pl-3 ${current ? 'border-brand-400' : 'border-neutral-700'}`}
              >
                <p className="text-[13px] leading-relaxed text-neutral-300">{scene.narration}</p>

                {scene.cite ? (
                  <span className="mt-2 flex">
                    <CitationChip cite={scene.cite} />
                  </span>
                ) : FACTUAL.has(scene.type) ? (
                  <p className="mt-2 flex items-start gap-1.5 text-[11px] leading-relaxed text-warning">
                    <Icon name="alert" label={null} className="mt-px size-3 shrink-0" />
                    <span>Uncited claim — nothing to check this scene against.</span>
                  </p>
                ) : (
                  <p className="mt-2 text-[11px] leading-relaxed text-neutral-500">
                    No citation needed — a {scene.type} card states no fact.
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
