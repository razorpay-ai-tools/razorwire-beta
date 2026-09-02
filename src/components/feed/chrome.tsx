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
import { primeSpeech, useSpeechVoiceCount } from './useNarration';

interface MuteState {
  muted: boolean;
  toggle: () => void;
}

/** Default keeps a post renderable outside the feed; `FeedScreen` supplies the real one. */
const MuteContext = createContext<MuteState>({
  muted: true,
  toggle: () => {},
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

  // Priming runs here, in the click itself. Narration starts in an effect a tick
  // later, which is outside the gesture Safari and iOS require, so without this the
  // reel played through in silence with no error to find. Harmless when muting, and
  // kept out of the state updater, which has to stay pure.
  const toggle = useCallback(() => {
    primeSpeech();
    setMuted((value) => !value);
  }, []);

  // m mutes. It belongs to the feed rather than to one post, so the preference
  // survives scrolling to the next one.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey || isTyping(event.target)) return;
      if (event.key === 'm' || event.key === 'M') {
        event.preventDefault();
        // A keystroke is a gesture too, so prime from here as well.
        primeSpeech();
        setMuted((value) => !value);
      }
    }

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const value = useMemo(() => ({ muted, toggle }), [muted, toggle]);
  return <MuteContext.Provider value={value}>{children}</MuteContext.Provider>;
}

export function useMute(): MuteState {
  return useContext(MuteContext);
}

/**
 * Playback speed, shared by both post variants for the same reason mute is: it is a
 * preference, and a preference that resets on scroll is not one.
 *
 * The values are the ones a reader actually reaches for. 2x is deliberately the top:
 * `SpeechSynthesis` rates above roughly 2 are clipped or refused outright by several
 * engines, so offering 3x would work on an MP4 post and silently do nothing on a
 * browser reel two posts down.
 */
export const SPEEDS = [0.75, 1, 1.25, 1.5, 2] as const;

interface SpeedState {
  rate: number;
  cycle: () => void;
}

const SpeedContext = createContext<SpeedState>({ rate: 1, cycle: () => {} });

export function SpeedProvider({ children }: { children: ReactNode }) {
  const [rate, setRate] = useState(1);

  const cycle = useCallback(() => {
    setRate((current) => SPEEDS[(SPEEDS.indexOf(current as (typeof SPEEDS)[number]) + 1) % SPEEDS.length]);
  }, []);

  // `>` and `<` step the speed, matching the single-key convention `m` already sets.
  // Shift is deliberately not excluded here — `>` IS shift-period on most layouts.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey || isTyping(event.target)) return;
      const delta = event.key === '>' || event.key === '.' ? 1 : event.key === '<' || event.key === ',' ? -1 : 0;
      if (delta === 0) return;
      event.preventDefault();
      setRate((current) => {
        const at = SPEEDS.indexOf(current as (typeof SPEEDS)[number]);
        return SPEEDS[Math.min(SPEEDS.length - 1, Math.max(0, at + delta))];
      });
    }

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const value = useMemo(() => ({ rate, cycle }), [rate, cycle]);
  return <SpeedContext.Provider value={value}>{children}</SpeedContext.Provider>;
}

export function useSpeed(): SpeedState {
  return useContext(SpeedContext);
}

/**
 * Keeps a `<video>` at the shared rate.
 *
 * `playbackRate` is a property, not an attribute, so React cannot set it and it has
 * to be assigned imperatively. It also resets to 1 whenever the element loads new
 * media, which is why `src` is a dependency and why `loadedmetadata` re-applies it:
 * setting it once on mount silently loses the rate the moment the source changes.
 */
export function usePlaybackRate(
  ref: { current: HTMLVideoElement | null },
  src: string | null | undefined,
): void {
  const { rate } = useSpeed();

  useEffect(() => {
    const video = ref.current;
    if (!video) return;

    const apply = () => {
      video.playbackRate = rate;
    };
    apply();
    video.addEventListener('loadedmetadata', apply);
    return () => video.removeEventListener('loadedmetadata', apply);
  }, [ref, rate, src]);
}

/** Cycles through {@link SPEEDS}. Shows the rate as a number, because "1.5x" needs no legend. */
export function SpeedButton({ className = '' }: { className?: string }) {
  const { rate, cycle } = useSpeed();

  return (
    <button
      type="button"
      onClick={cycle}
      aria-label={`Playback speed ${rate}x, press to change`}
      className={`panel pointer-events-auto flex items-center gap-1.5 px-2.5 py-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-neutral-200 transition-colors hover:text-white ${className}`}
    >
      <Icon name="gauge" label={null} className="size-3.5 shrink-0" />
      <span>{rate}x</span>
      <span className="sr-only">, press &gt; to speed up and &lt; to slow down</span>
    </button>
  );
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
 * Says so when this browser cannot speak.
 *
 * A synthesizer with no voices returns no sound and no error, so an unmuted reel looked
 * broken in exactly the way a bug looks. Naming it turns "the app is broken" into "this
 * browser has no voices", which the reader can act on — and the captions are still the
 * whole text, so nothing is actually lost.
 */
export function NarrationNotice() {
  const { muted } = useMute();
  const voices = useSpeechVoiceCount();
  if (muted || voices > 0) return null;

  return (
    <span
      role="status"
      title="Narration uses the browser's speech synthesizer, which has no voices installed here. The captions carry the same words."
      className="panel pointer-events-auto flex items-center gap-1.5 px-2.5 py-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-warning"
    >
      <Icon name="alert" label={null} className="size-3.5 shrink-0" />
      No voices — captions only
    </span>
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
