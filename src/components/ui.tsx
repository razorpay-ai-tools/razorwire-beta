/**
 * Shared primitives. Owned centrally because the feed, the scene templates and the
 * inspector all need them.
 *
 * Icons are inline SVG, not emoji. The first design pass used emoji for the whole
 * action rail, which renders at different widths per platform, cannot be recoloured,
 * and reads as "Unicode character" to a screen reader. Every icon here takes a
 * required label.
 */

import type { Scene } from '@/lib/storyboard.types';

export type IconName =
  | 'sun'
  | 'moon'
  | 'bolt'
  | 'comment'
  | 'bookmark'
  | 'doc'
  | 'eye'
  | 'muted'
  | 'unmuted'
  | 'play'
  | 'pause'
  | 'close'
  | 'send'
  | 'upload'
  | 'check'
  | 'alert'
  | 'sparkle'
  | 'quote';

const PATHS: Record<IconName, string> = {
  sun: 'M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v3M12 20v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M1 12h3M20 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1',
  moon: 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z',
  bolt: 'M13 2 4.5 13.2h5.2L9 22l8.6-11.3h-5.3z',
  comment: 'M21 12a8 8 0 0 1-8 8H8l-5 3 1.3-4.6A8 8 0 1 1 21 12z',
  bookmark: 'M6 3h12v18l-6-4.5L6 21z',
  doc: 'M7 2h7l5 5v15H7zM14 2v5h5',
  eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
  muted: 'M11 5 6 9H3v6h3l5 4zM17 9l4 6M21 9l-4 6',
  unmuted: 'M11 5 6 9H3v6h3l5 4zM16 8a5 5 0 0 1 0 8M19 5a9 9 0 0 1 0 14',
  play: 'M6 4l14 8-14 8z',
  pause: 'M7 4h4v16H7zM13 4h4v16h-4z',
  close: 'M5 5l14 14M19 5 5 19',
  send: 'M3 20l18-8L3 4l4 8z',
  upload: 'M12 16V4m0 0L7 9m5-5 5 5M4 18v2h16v-2',
  check: 'M4 12l5 5L20 6',
  alert: 'M12 3l9 16H3zM12 9v5M12 17h.01',
  sparkle: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z',
  quote: 'M7 7h4v6H7zM13 7h4v6h-4zM7 13c0 2 1 3 3 4M13 13c0 2 1 3 3 4',
};

interface IconProps {
  name: IconName;
  /** Required. Pass `null` only when an adjacent visible label already names the control. */
  label: string | null;
  className?: string;
  filled?: boolean;
}

export function Icon({ name, label, className = 'size-6', filled = false }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill={filled ? 'currentColor' : 'none'}
      stroke="currentColor"
      strokeWidth={filled ? 0 : 1.9}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={label ? 'img' : undefined}
      aria-label={label ?? undefined}
      aria-hidden={label ? undefined : true}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

/**
 * The trust feature, rendered.
 *
 * Only ever shown for scenes that assert something about the source document. The
 * contract requires `cite` on bullets, diagram, compare and code; title and outro
 * carry no factual claim and must NOT display a chip. The first design pass put one
 * on the title scene, which invents a citation for a scene that has none.
 */
export function CitationChip({ cite, className = '' }: { cite: string; className?: string }) {
  return (
    <span
      className={`inline-flex max-w-full items-center gap-1.5 rounded-full border border-brand-500/30 bg-neutral-900/80 px-2.5 py-1 font-mono text-[11px] font-medium tracking-tight text-brand-300 shadow-sm backdrop-blur-md ${className}`}
    >
      <Icon name="doc" label={null} className="size-3 shrink-0" />
      <span className="truncate">{cite}</span>
      <span className="sr-only">— source section for this scene</span>
    </span>
  );
}

/** Burned-in caption. Most people watch muted, so this is the primary read path. */
export function CaptionBar({ text, className = '' }: { text: string; className?: string }) {
  return (
    <p
      key={text}
      className={`mx-auto w-full max-w-[92%] animate-fade-in rounded-xl border border-white/10 bg-neutral-950/85 px-4 py-2.5 text-center text-sm font-medium leading-snug text-white shadow-xl backdrop-blur-lg ${className}`}
    >
      {text}
    </p>
  );
}

/**
 * Stories-style scene progress. Segment count equals scene count.
 *
 * Fixed from the first pass, whose class string combined `h-1.5` with `pt-3 pb-1` —
 * 6px tall with 16px of vertical padding is not satisfiable. Padding lives on the
 * wrapper, height on the track.
 */
export function ProgressRail({
  count,
  current,
  className = '',
}: {
  count: number;
  current: number;
  className?: string;
}) {
  return (
    <div
      className={`flex w-full gap-1 ${className}`}
      role="progressbar"
      aria-valuemin={1}
      aria-valuemax={count}
      aria-valuenow={current + 1}
      aria-label={`Scene ${current + 1} of ${count}`}
    >
      {Array.from({ length: count }, (_, i) => (
        <span key={i} className="h-1 flex-1 overflow-hidden rounded-full bg-white/25">
          <span
            className={`block h-full rounded-full transition-[width] duration-300 ${
              i <= current ? 'w-full bg-brand-400' : 'w-0'
            }`}
          />
        </span>
      ))}
    </div>
  );
}

/** Category pill. Text carries the meaning; colour only reinforces it. */
export function CategoryChip({ category }: { category: string }) {
  return (
    <span className="inline-flex items-center rounded-full border border-white/15 bg-neutral-950/60 px-2.5 py-1 font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-neutral-300 backdrop-blur-md">
      {category}
    </span>
  );
}

/**
 * Dense scenes need a heavier scrim than title cards, so the weight is a property
 * of what the scene renders rather than a global constant.
 */
export function scrimFor(sceneType: Scene['type']): 'scrim-light' | 'scrim-heavy' {
  return sceneType === 'title' || sceneType === 'outro' ? 'scrim-light' : 'scrim-heavy';
}
