'use client';

/**
 * The desktop split card. `lg:` and up only — mobile keeps the full-bleed snap feed.
 *
 * The player docks left at 9:16 and the audit panel sits right, because the product's
 * claim is that narration can be checked against the source spec. Overlaying the
 * metadata, the citation and the conversation on top of the video is what mobile has to
 * do; a 1440px window does not, and reading a citation against the narration that used
 * it is much easier side by side than stacked over moving footage.
 *
 * Which stage a post gets:
 *   - `clip`, and any generated post the render pipeline has produced an MP4 for
 *     (`mediaUrl` set), play the file in `ClipStage` — mirroring `GeneratedPost` on
 *     mobile, which routes `mediaUrl` to a real `<video>` too. Only a generated post
 *     WITHOUT an MP4 is played as live DOM scenes by `SceneView`.
 *
 * What this deliberately does NOT do:
 *   - It does not render its own citation chip. `SceneShell` (scenes/SceneShell.tsx)
 *     already renders one for the current scene inside `SceneView`, so a chip here would
 *     be the same citation printed twice.
 *
 * The two layouts are mutually exclusive by media query rather than by `hidden lg:block`,
 * because both trees mounting at once means two mermaid renders, two b-roll videos and
 * two speech-synthesis utterances per post.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
} from 'react';
import { SceneView } from '@/components/scenes/SceneView';
import { CaptionBar, Icon, ProgressRail, scrimFor } from '@/components/ui';
import { brollSrc, type Post } from '@/lib/api';
import { Broll } from './GeneratedPost';
import {
  MuteButton,
  NarrationNotice,
  NarrationRateButton,
  accentBackdrop,
  useMute,
} from './chrome';
import { DesktopPanel } from './DesktopPanel';
import { useNarration } from './useNarration';
import { useReel, type Reel } from './useReel';

/** Tailwind's `lg` breakpoint, as a media query. Kept in one place on purpose. */
const DESKTOP_QUERY = '(min-width: 64rem)';

function subscribeToDesktop(onChange: () => void): () => void {
  const query = window.matchMedia(DESKTOP_QUERY);
  query.addEventListener('change', onChange);
  return () => query.removeEventListener('change', onChange);
}

/**
 * Read as an external store, the same way `usePrefersReducedMotion` does. The server
 * snapshot is `false` so SSR renders the mobile tree; the feed's posts only exist after
 * a client fetch, so nothing is hydrated twice.
 */
export function useIsDesktop(): boolean {
  return useSyncExternalStore(
    subscribeToDesktop,
    () => window.matchMedia(DESKTOP_QUERY).matches,
    () => false,
  );
}

/**
 * `scene-safe` reserves 17.5rem at the bottom, measured against the MOBILE chrome —
 * metadata block, caption bar and the app nav all stack there. In this card only the
 * caption bar is inside the stage, so that reserve would throw away a third of the
 * frame. globals.css already reads the reserve from this variable, so it is overridden
 * here rather than edited there.
 */
const STAGE_STYLE = { '--rw-scene-bottom': '6.5rem' } as CSSProperties;

function clock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable;
}

export function DesktopCard({ post, active }: { post: Post; active: boolean }) {
  const scenes = useMemo(() => post.storyboard?.scenes ?? [], [post.storyboard]);
  const generated = post.kind === 'generated';
  // A generated post with an MP4 plays the file; only without one is it live scenes.
  const scenePost = generated && !post.mediaUrl;
  const { muted, rate } = useMute();
  // Unmuted, the voice paces the reel and the timer stands down. See useNarration.
  // Never for an MP4 post: the file carries its own spoken track.
  const spoken = scenePost && !muted && active;
  // Called unconditionally: a clip simply has no scenes, so the reel is empty and idle.
  const reel = useReel(scenes, active, spoken);
  const { next, prev } = reel;

  // Left/right step scenes, as on mobile. Only the visible post listens.
  useEffect(() => {
    if (!active || !scenePost) return;

    function onKeyDown(event: KeyboardEvent) {
      if (isTyping(event.target)) return;
      if (event.key === 'ArrowRight') {
        event.preventDefault();
        next();
      } else if (event.key === 'ArrowLeft') {
        event.preventDefault();
        prev();
      }
    }

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [active, scenePost, next, prev]);

  /**
   * There is no audio track on the generated path — narration is the Web Speech API, so
   * the shared mute control drives the synth. Without this the unmute button would be a
   * control that does nothing on desktop. Same hook as mobile: one implementation of
   * "speak the caption, then advance", two compositions.
   */
  useNarration({
    text: reel.caption,
    enabled: spoken && reel.playing,
    rate,
    onDone: reel.advance,
  });

  return (
    <article
      aria-label={`${generated ? 'Generated reel' : 'Clip'}: ${post.title}`}
      /*
       * pb-20 clears the app's create bar, which is pinned to the bottom centre.
       *
       * `--rw-panel-w` sets the panel's width; the stage takes the rest.
       */
      /*
       * The CARD is centred, not the stage.
       *
       * There used to be a spacer mirroring the panel's width on the far side of the
       * stage, which put the 9:16 player exactly on the viewport midpoint. Measured, it
       * also pushed the card 200px right of centre and left a visible dead band down
       * the left edge — the composition read as shifted even though the player was
       * technically centred. Balancing the whole card is what actually looks centred;
       * the stage now sits a half-panel left of the midpoint, which nobody perceives.
       */
      className="flex h-full w-full items-center justify-center px-6 pb-20 pt-6 [--rw-panel-w:21rem] xl:[--rw-panel-w:25rem] 2xl:[--rw-panel-w:28rem]"
    >

      {/*
       * `max-h-[75vw]` is the responsive decision on the other axis. The stage is a true
       * 9:16 box sized off the card's height, so on a tall narrow lg window (1024x1600,
       * say) it would grow to 840px wide and leave the panel nothing. Capping the card's
       * height at 75% of the viewport width bounds the stage's width, so the panel always
       * keeps a readable column and the player letterboxes instead. At every width checked
       * (1024x768, 1280x800, 1440x900) the viewport height is the binding constraint and
       * this cap does nothing.
       */}
      <div className="flex h-full max-h-[75vw] shrink-0 overflow-hidden rounded-2xl border border-hairline bg-surface-1 shadow-2xl">
        {/*
         * `stage-dark` — the one deliberate exception to the theme. Captions, citation
         * chips and scene text sit over arbitrary footage; a light scrim cannot hold them
         * legible, so this column stays dark in both themes.
         *
         * The class is here for what it genuinely does: `color-scheme: dark` (which the
         * clip's `<input type="range">` and any scrollbar inside the stage read), and the
         * `--rw-*` variables that `.input` consumes directly.
         *
         * The BACKGROUND is `bg-neutral-950`, a raw always-dark step, NOT `bg-surface-0`.
         * `stage-dark` cannot flip Tailwind's semantic colour utilities: `@theme` declares
         * `--color-surface-0: var(--rw-surface-0)` on `:root`, so that indirection is
         * resolved to a literal there and inherited as an already-computed value.
         * Re-declaring `--rw-surface-0` further down the tree comes too late. Measured:
         * `--rw-surface-0` reads #131415 on this element while `bg-surface-0` still paints
         * #f7f7f7. Every other thing inside the stage already uses raw dark steps, so this
         * is consistent rather than a special case.
         */}
        <div
          data-testid="desktop-stage"
          style={STAGE_STYLE}
          className="stage-dark relative aspect-[9/16] h-full shrink-0 overflow-hidden bg-neutral-950"
        >
          {scenePost ? (
            <SceneStage post={post} active={active} reel={reel} />
          ) : (
            <ClipStage post={post} active={active} generated={generated} />
          )}
        </div>

        {/*
         * `currentIndex` only while this post is the active one. The inspector keeps the
         * current scene in view with `scrollIntoView`, and scrollIntoView walks EVERY
         * scrollable ancestor — including the feed's snap container. With an index passed
         * for off-screen posts too, the last card's inspector scrolled the whole feed to
         * itself on first paint, so the reader landed three posts down. With it undefined
         * no row is marked current, the inspector's ref is null, and nothing scrolls.
         *
         * It is also the honest value: `useReel` rewinds an inactive post to scene 0, so
         * there is no scene "on screen" for a post that is not on screen.
         */}
        <DesktopPanel
          post={post}
          active={active}
          currentIndex={scenePost && active ? reel.index : undefined}
        />
      </div>
    </article>
  );
}

/**
 * The generated stage. Same layer order as `GeneratedPost`: b-roll plate, scrim, scene
 * layer, tap zones, chrome.
 *
 * The scene layer sits ABOVE the tap zones and is `pointer-events-none`, so a click on
 * empty scene area still reaches the zone underneath while anything a scene makes
 * interactive — the outro's link, the code scene's scroll region — still receives its
 * own clicks. With the zones on top, the outro's link was visible and dead.
 */
function SceneStage({ post, active, reel }: { post: Post; active: boolean; reel: Reel }) {
  const { index, count, scene, caption, playing, setPlaying, next, prev } = reel;

  if (!scene) {
    return (
      <>
        <div aria-hidden className="absolute inset-0" style={accentBackdrop(post.accent)} />
        <div aria-hidden className="absolute inset-0 scrim-heavy" />
        <p className="panel absolute left-4 right-4 top-1/2 -translate-y-1/2 p-4 text-center text-sm text-neutral-300">
          <Icon name="alert" label={null} className="mx-auto mb-2 size-5 text-warning" />
          This reel has no scenes yet.
        </p>
      </>
    );
  }

  return (
    <>
      <Broll src={brollSrc(scene)} accent={post.accent} active={active} />
      <div aria-hidden className={`absolute inset-0 ${scrimFor(scene.type)}`} />

      {/*
       * `active={false}` deliberately, which means "do not play the entry animation" —
       * it is the ONLY thing `active` controls in every scene template (SceneShell's
       * fade-in, and BulletsScene's staggered bullets).
       *
       * Why: `--animate-fade-in` has no fill mode and `@keyframes fade-in` starts at
       * `opacity: 0`, so while that animation is in flight it is the only thing setting
       * the scene's opacity. Any window where the page drops frames therefore paints the
       * whole stage BLANK for as long as the stall lasts — measured here at ~2s with
       * `animation.currentTime` pinned to 0 while `playState` stayed "running", headless
       * and headed alike. BulletsScene is worse: its bullets use
       * `[animation-fill-mode:backwards]`, so they hold opacity 0 through their delay too.
       *
       * A 220ms flourish is not worth a stage whose legibility depends on the frame
       * pipeline, least of all on the surface built for reading a spec against narration.
       * The b-roll still gets the real `active` below — that drives playback, not opacity.
       */}
      {/*
       * `[&_.scene-safe]:pr-5` puts the scene's right padding back to the normal inline
       * 1.25rem. SceneShell reserves 4.75rem there to clear the feed's floating action
       * rail, which is correct on mobile and wrong here: this card's like/comment/save
       * live in the panel's footer, so nothing floats over the frame and the reserve just
       * shifts every scene visibly off-centre. Overridden from the container that knows
       * the premise changed rather than by editing the shared shell.
       */}
      <div className="pointer-events-none absolute inset-0 z-20 [&_.scene-safe]:pr-5">
        <SceneView scene={scene} active={false} />
      </div>

      <div className="absolute inset-0 z-10 grid grid-cols-3">
        <button
          type="button"
          tabIndex={active ? 0 : -1}
          onClick={prev}
          aria-label="Previous scene"
          className="focus-visible:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-400"
        />
        <button
          type="button"
          tabIndex={active ? 0 : -1}
          onClick={() => setPlaying(!playing)}
          aria-label={playing ? 'Pause scenes' : 'Play scenes'}
          className="focus-visible:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-400"
        />
        <button
          type="button"
          tabIndex={active ? 0 : -1}
          onClick={next}
          aria-label="Next scene"
          className="focus-visible:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-400"
        />
      </div>

      <div className="pointer-events-none absolute inset-x-0 top-0 z-30 flex flex-col items-start gap-2.5 px-4 pt-4">
        <ProgressRail count={count} current={index} />

        <div className="flex w-full items-center gap-2">
          <button
            type="button"
            onClick={() => setPlaying(!playing)}
            aria-label={playing ? 'Pause scenes' : 'Play scenes'}
            className="panel pointer-events-auto grid size-8 place-items-center text-neutral-200 transition-colors hover:text-white"
          >
            <Icon name={playing ? 'pause' : 'play'} label={null} filled className="size-3.5" />
          </button>

          <span className="panel flex items-center gap-1.5 px-2.5 py-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-neutral-300">
            <Icon name="sparkle" label={null} className="size-3.5 shrink-0 text-brand-300" />
            AI reel
            <span aria-hidden className="text-neutral-600">
              &middot;
            </span>
            <span className="tabular-nums">
              {index + 1}/{count}
            </span>
          </span>

          {/* Grouped so the pair stays right-aligned when the rate button is hidden. */}
          <div className="ml-auto flex items-center gap-2">
            <NarrationNotice />
            <NarrationRateButton />
            <MuteButton />
          </div>
        </div>
      </div>

      {caption ? (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-30 px-4 pb-4">
          <CaptionBar text={caption} />
        </div>
      ) : null}
    </>
  );
}

/**
 * The clip stage. No scenes, so no progress segments, no citation and no captions —
 * a continuous position bar and a clock instead, exactly as on mobile. The metadata
 * and the conversation live in the right-hand panel.
 *
 * `generated` marks a rendered AI reel (an MP4 the pipeline produced): same player,
 * but badged "AI reel" so it is not mistaken for footage someone uploaded.
 */
function ClipStage({
  post,
  active,
  generated = false,
}: {
  post: Post;
  active: boolean;
  generated?: boolean;
}) {
  const { muted } = useMute();
  const ref = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState((post.durationMs ?? 0) / 1000);
  const [broken, setBroken] = useState(false);
  const src = post.mediaUrl;
  const usable = Boolean(src) && !broken;

  useEffect(() => {
    const video = ref.current;
    if (!video) return;

    if (active) {
      void video.play().catch(() => {
        // Refused (usually unmuted autoplay). The play overlay is the recovery.
      });
    } else {
      video.pause();
      video.currentTime = 0;
    }
  }, [active]);

  const toggle = useCallback(() => {
    const video = ref.current;
    if (!video) return;
    if (video.paused) void video.play().catch(() => {});
    else video.pause();
  }, []);

  return (
    <>
      {usable && src ? (
        <video
          ref={ref}
          src={src}
          poster={post.thumbnailUrl ?? undefined}
          muted={muted}
          loop
          playsInline
          preload="metadata"
          tabIndex={-1}
          onError={() => setBroken(true)}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onTimeUpdate={(event) => setTime(event.currentTarget.currentTime)}
          onLoadedMetadata={(event) => {
            const measured = event.currentTarget.duration;
            if (Number.isFinite(measured) && measured > 0) setDuration(measured);
          }}
          className="absolute inset-0 size-full object-cover"
        />
      ) : (
        <>
          <div aria-hidden className="absolute inset-0" style={accentBackdrop(post.accent)} />
          <p className="panel absolute left-4 right-4 top-1/2 z-10 -translate-y-1/2 p-4 text-center text-sm text-neutral-300">
            <Icon name="alert" label={null} className="mx-auto mb-2 size-5 text-warning" />
            This clip&rsquo;s video could not be loaded.
          </p>
        </>
      )}

      {/* Bands, not the shared scrim: footage someone shot stays visible mid-frame. */}
      <div
        aria-hidden
        className="absolute inset-x-0 top-0 z-10 h-24 bg-gradient-to-b from-neutral-950/85 to-transparent"
      />
      <div
        aria-hidden
        className="absolute inset-x-0 bottom-0 z-10 h-32 bg-gradient-to-t from-neutral-950 via-neutral-950/70 to-transparent"
      />

      {usable ? (
        <button
          type="button"
          tabIndex={active ? 0 : -1}
          onClick={toggle}
          aria-label={playing ? 'Pause clip' : 'Play clip'}
          className="absolute inset-0 z-20 grid place-items-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-400"
        >
          {!playing ? (
            <span className="grid size-16 place-items-center rounded-full border border-white/20 bg-neutral-950/70 text-white backdrop-blur-md">
              <Icon name="play" label={null} filled className="size-7 translate-x-0.5" />
            </span>
          ) : null}
        </button>
      ) : null}

      <div className="pointer-events-none absolute inset-x-0 top-0 z-30 flex items-center gap-2 px-4 pt-4">
        <span className="panel flex items-center gap-1.5 px-2.5 py-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-neutral-300">
          {generated ? (
            <Icon name="sparkle" label={null} className="size-3.5 shrink-0 text-brand-300" />
          ) : (
            <Icon name="play" label={null} filled className="size-3 shrink-0 text-neutral-400" />
          )}
          {generated ? 'AI reel' : 'Clip'}
          <span aria-hidden className="text-neutral-600">
            &middot;
          </span>
          <span className="tabular-nums">{clock(duration)}</span>
        </span>
        <MuteButton className="ml-auto" />
      </div>

      <div className="absolute inset-x-0 bottom-0 z-30 flex items-center gap-3 px-4 pb-4">
        <label htmlFor={`desktop-seek-${post.id}`} className="sr-only">
          Seek clip
        </label>
        <input
          id={`desktop-seek-${post.id}`}
          type="range"
          min={0}
          max={duration || 0}
          step={0.1}
          value={Math.min(time, duration || 0)}
          disabled={!usable || duration <= 0}
          onChange={(event) => {
            const nextTime = Number(event.target.value);
            const video = ref.current;
            if (video) video.currentTime = nextTime;
            setTime(nextTime);
          }}
          aria-valuetext={`${clock(time)} of ${clock(duration)}`}
          className="h-1.5 w-full cursor-pointer accent-brand-400 disabled:cursor-default disabled:opacity-50"
        />
        <span className="shrink-0 font-mono text-[11px] font-medium tabular-nums text-neutral-300">
          {clock(time)}
          <span aria-hidden className="mx-1 text-neutral-600">
            /
          </span>
          {clock(duration)}
        </span>
      </div>
    </>
  );
}
