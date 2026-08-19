'use client';

/**
 * Chrome shared by both post variants.
 *
 * Mute lives in context rather than in each post because a mute preference that
 * resets every time you scroll is not a preference. `FeedPost` takes exactly
 * `{ post, active }`, so there is nowhere to thread it as a prop.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type ReactNode,
} from 'react';
import { CategoryChip, Icon } from '@/components/ui';
import { compactCount, initialsOf, type Post } from '@/lib/api';
import { nextRate } from './narration';

interface MuteState {
  muted: boolean;
  toggle: () => void;
  /** Narration speed. Lives here with mute because both are the same preference. */
  rate: number;
  cycleRate: () => void;
}

/** Default keeps a post renderable outside the feed; `FeedScreen` supplies the real one. */
const MuteContext = createContext<MuteState>({
  muted: true,
  toggle: () => {},
  rate: 1,
  cycleRate: () => {},
});

/** True when the keystroke belongs to whatever the user is typing in. */
function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return (
    el.tagName === 'INPUT' ||
    el.tagName === 'TEXTAREA' ||
    el.tagName === 'SELECT' ||
    el.isContentEditable
  );
}

export function MuteProvider({ children }: { children: ReactNode }) {
  // Muted by default: browsers block unmuted autoplay, so anything else would
  // silently fail to start on first paint.
  const [muted, setMuted] = useState(true);
  const [rate, setRate] = useState<number>(1);
  const toggle = useCallback(() => setMuted((value) => !value), []);
  const cycleRate = useCallback(() => setRate((current) => nextRate(current)), []);

  // m mutes, s changes speed. Both belong to the feed rather than to one post, so a
  // preference survives scrolling to the next one.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey || isTyping(event.target)) return;
      if (event.key === 'm' || event.key === 'M') {
        event.preventDefault();
        setMuted((value) => !value);
      } else if (event.key === 's' || event.key === 'S') {
        event.preventDefault();
        setRate((current) => nextRate(current));
      }
    }

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const value = useMemo(() => ({ muted, toggle, rate, cycleRate }), [muted, toggle, rate, cycleRate]);
  return <MuteContext.Provider value={value}>{children}</MuteContext.Provider>;
}

export function useMute(): MuteState {
  return useContext(MuteContext);
}

/**
 * The one unmute control. Carries a word as well as an icon — a slashed speaker
 * alone is the kind of glyph people read as "no sound available".
 */
export function MuteButton({ className = '' }: { className?: string }) {
  const { muted, toggle } = useMute();

  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={muted}
      className={`panel pointer-events-auto flex items-center gap-1.5 px-2.5 py-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-neutral-200 transition-colors hover:text-white ${className}`}
    >
      <Icon name={muted ? 'muted' : 'unmuted'} label={null} className="size-3.5 shrink-0" />
      <span>{muted ? 'Muted' : 'Sound on'}</span>
      <span className="sr-only">, press M to toggle</span>
    </button>
  );
}

/**
 * Narration speed. Only shown once the narration can be heard — a speed control on a
 * muted reel is a control for nothing, and it would sit next to the unmute button
 * competing for the same glance.
 *
 * The rate also paces the reel, because scenes advance when the voice finishes a line.
 * So this is a speed control for the whole thing, not just for the voice.
 */
export function NarrationRateButton({ className = '' }: { className?: string }) {
  const { muted, rate, cycleRate } = useMute();
  if (muted) return null;

  return (
    <button
      type="button"
      onClick={cycleRate}
      className={`panel pointer-events-auto flex items-center gap-1 px-2.5 py-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-neutral-200 transition-colors hover:text-white ${className}`}
    >
      <span className="tabular-nums">{rate}×</span>
      <span className="sr-only">narration speed, press S to change</span>
    </button>
  );
}

/**
 * Bottom metadata. Views sit here rather than in the action rail because they are
 * the product's headline metric, not one engagement number among four.
 */
export function PostMeta({ post }: { post: Post }) {
  const author = post.author.name || post.author.email;

  return (
    <div className="flex items-start gap-3">
      <span
        aria-hidden
        className="grid size-9 shrink-0 place-items-center rounded-full border border-white/15 bg-neutral-900/85 font-mono text-[11px] font-bold tracking-tight text-brand-300 backdrop-blur-md"
      >
        {initialsOf(post.author)}
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
          <span className="font-semibold text-white">{author}</span>
          {post.team ? (
            <>
              <span aria-hidden className="text-neutral-600">
                &middot;
              </span>
              <span className="text-neutral-400">{post.team}</span>
            </>
          ) : null}
          {/* The channel is the label that matters once you can follow one; the
              category is the fallback for posts that predate channels. */}
          <CategoryChip category={post.channel ? `#${post.channel.slug}` : post.category} />
        </div>

        <h2 className="mt-1.5 text-pretty text-[17px] font-semibold leading-snug tracking-tight text-white [text-shadow:0_1px_3px_rgb(0_0_0/0.9)]">
          {post.title}
        </h2>

        <p className="mt-1.5 flex items-center gap-1.5 font-mono text-[11px] font-medium text-neutral-300">
          <Icon name="eye" label={null} className="size-3.5 shrink-0" />
          <span>
            {compactCount(post.views)} <span className="text-neutral-400">views</span>
          </span>
        </p>
      </div>
    </div>
  );
}

/**
 * The never-a-black-void plate. Used when b-roll 404s and when a clip has no
 * media. `accent` is a free-form string on the wire and is empty in practice, so
 * anything that is not obviously a CSS colour falls back to the brand ramp.
 */
export function accentBackdrop(accent: string): CSSProperties {
  const colour = /^(#|rgb|hsl|oklch|color-mix)/.test(accent.trim())
    ? accent.trim()
    : 'var(--color-brand-500)';

  return {
    backgroundImage: [
      `radial-gradient(120% 85% at 18% 10%, color-mix(in oklab, ${colour} 60%, transparent) 0%, transparent 62%)`,
      `radial-gradient(95% 75% at 88% 92%, color-mix(in oklab, ${colour} 34%, transparent) 0%, transparent 58%)`,
      'linear-gradient(180deg, var(--color-neutral-900) 0%, var(--color-neutral-950) 100%)',
    ].join(','),
  };
}
