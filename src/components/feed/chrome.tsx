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
import { CategoryChip, Icon, ThemeBadge } from '@/components/ui';
import { postTheme } from '@/lib/themes';
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
 * Saves the rendered MP4 so it can be shared outside the feed.
 *
 * Links `/downloads/…` rather than the `/media/…` the player uses: the anchor
 * `download` attribute is ignored cross-origin, so the backend's
 * Content-Disposition header is what actually makes the browser save the file.
 */
export function DownloadButton({
  mediaUrl,
  className = '',
}: {
  mediaUrl: string | null | undefined;
  className?: string;
}) {
  if (!mediaUrl) return null;

  return (
    <a
      href={mediaUrl.replace('/media/', '/downloads/')}
      download
      aria-label="Download video"
      title="Download video"
      // Icon-only: the strip holds five controls on a phone, and a labelled download
      // was the one that got pushed off the edge or under the stage switch.
      className={`panel pointer-events-auto grid place-items-center p-1.5 text-neutral-200 transition-colors hover:text-white ${className}`}
    >
      <Icon name="download" label={null} className="size-3.5 shrink-0" />
    </a>
  );
}

/**
 * How long the top controls stay up before getting out of the way. Long enough to
 * notice and reach them, short enough that a reel you are actually watching is
 * unobstructed for most of its length.
 */
const CONTROLS_IDLE_MS = 3000;

interface IdleState {
  visible: boolean;
  wake: () => void;
}

const IdleContext = createContext<IdleState>({ visible: true, wake: () => {} });

/**
 * One idle clock for every piece of chrome that sits over the video.
 *
 * Deliberately a single shared timer rather than one per overlay: the control strip,
 * the action rail, the metadata block, the seek bar and the app nav all cover the same
 * frame, and three of them fading on their own schedules reads as a glitch rather than
 * as a player getting out of the way. They appear and disappear together or not at all.
 *
 * Mounted in `page.tsx` rather than in `FeedScreen`, because the app nav pill is a
 * sibling of the feed and has to read the same clock.
 */
export function ChromeIdleProvider({ children }: { children: ReactNode }) {
  const [visible, setVisible] = useState(true);

  const wake = useCallback(() => setVisible(true), []);

  useEffect(() => {
    let timer = 0;
    const arm = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => setVisible(false), CONTROLS_IDLE_MS);
    };
    const bump = () => {
      setVisible(true);
      arm();
    };

    arm();
    // On `window`, not on the feed element: this is a full-bleed snap feed, so a
    // pointer moving anywhere is a viewer reaching for the controls of whatever post
    // is on screen. `keydown` is what keeps the chrome reachable without a mouse.
    for (const event of ['pointermove', 'pointerdown', 'keydown', 'touchstart'] as const) {
      window.addEventListener(event, bump, { passive: true });
    }
    return () => {
      window.clearTimeout(timer);
      for (const event of ['pointermove', 'pointerdown', 'keydown', 'touchstart'] as const) {
        window.removeEventListener(event, bump);
      }
    };
  }, []);

  const value = useMemo(() => ({ visible, wake }), [visible, wake]);
  return <IdleContext.Provider value={value}>{children}</IdleContext.Provider>;
}

export function useChromeIdle(): IdleState {
  return useContext(IdleContext);
}

/**
 * Fades its children out once the viewer stops interacting, and back in the moment
 * they do.
 *
 * Hidden with `opacity`, deliberately not `visibility` or `hidden`: both of those drop
 * anything focusable out of the tab order, and a control a keyboard user can no longer
 * reach is not hidden, it is gone. Opacity keeps them focusable and `focusin` brings
 * the group straight back, so tabbing to the speed button shows it.
 *
 * `.controls-idle` (globals.css) switches pointer events off underneath while hidden —
 * a parent's `pointer-events: none` is re-enabled by any descendant setting `auto`, so
 * an invisible Download link or Like button would otherwise still swallow the tap
 * meant for play/pause.
 *
 * Hover pins it open too, or the group fades out from under a pointer already resting
 * on the button about to be clicked.
 */
export function AutoHide({
  className = '',
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  const { visible } = useChromeIdle();
  const [pinned, setPinned] = useState(false);
  const shown = visible || pinned;

  return (
    <div
      onFocusCapture={() => setPinned(true)}
      onBlurCapture={() => setPinned(false)}
      onPointerEnter={() => setPinned(true)}
      onPointerLeave={() => setPinned(false)}
      className={`${className} transition-opacity duration-300 motion-reduce:transition-none ${
        shown ? 'opacity-100' : 'controls-idle opacity-0'
      }`}
    >
      {children}
    </div>
  );
}

/**
 * The top control strip — badge, speed, mute, download. Positioning only; the fade
 * and the pointer-event handling belong to {@link AutoHide}, which every other
 * overlay on the frame shares so they move as one.
 */
export function ControlBar({
  active = true,
  children,
}: {
  active?: boolean;
  children: ReactNode;
}) {
  const { wake } = useChromeIdle();

  // A post scrolling into view shows its chrome again — otherwise the strip is only
  // ever discoverable on the first post of a session. Reset during render rather than
  // in an effect, which is what `react-hooks/set-state-in-effect` is for and what
  // `PipelineStepper` already does for the same reason: waking from an effect paints
  // one frame of the previous post's hidden state first.
  const [trackedActive, setTrackedActive] = useState(active);
  if (trackedActive !== active) {
    setTrackedActive(active);
    if (active) wake();
  }

  return (
    <AutoHide className="pointer-events-none absolute inset-x-0 top-0 z-30 flex items-center gap-2 whitespace-nowrap px-4 pt-4 [&>*]:shrink-0">
      {children}
    </AutoHide>
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
  const theme = postTheme(post);

  return (
    <div className="flex items-start gap-3">
      <span
        aria-hidden
        className="grid size-9 shrink-0 place-items-center rounded-full border border-white/15 bg-neutral-900/85 font-mono text-[11px] font-bold tracking-tight text-[var(--post-accent,var(--color-brand-300))] backdrop-blur-md"
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
          {theme ? <ThemeBadge theme={theme} /> : null}
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
