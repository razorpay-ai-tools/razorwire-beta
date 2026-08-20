'use client';

/**
 * A storyboard, played as a sequence.
 *
 * Layer order, bottom to top: Veo b-roll plate, scrim, scene template, tap zones,
 * chrome. The b-roll is decoration only — every legible thing on screen is DOM,
 * which is the whole reason the diagram is trustworthy.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { SceneView } from '@/components/scenes/SceneView';
import { CaptionBar, Icon, ProgressRail, scrimFor } from '@/components/ui';
import { brollSrc, docHref, type Post } from '@/lib/api';
import { ActionRail } from './ActionRail';
import {
  MuteButton,
  NarrationNotice,
  NarrationRateButton,
  PostMeta,
  accentBackdrop,
  useMute,
} from './chrome';
import { useNarration } from './useNarration';
import { useReel } from './useReel';

/**
 * Background plate. A missing clip is normal — the library is mood-keyed and
 * cached, so a storyboard can reference a mood we never generated. Falling back to
 * the accent gradient keeps the frame from going black.
 *
 * Exported for the desktop card's stage, which needs the identical fallback and
 * play/pause behaviour. One implementation, two compositions.
 */
export function Broll({
  src,
  accent,
  active,
}: {
  src: string | null;
  accent: string;
  active: boolean;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  const [brokenSrc, setBrokenSrc] = useState<string | null>(null);

  useEffect(() => {
    const video = ref.current;
    if (!video) return;

    if (active) {
      void video.play().catch(() => {
        // Autoplay refused. The plate stays on its first frame; nothing to recover.
      });
    } else {
      video.pause();
      video.currentTime = 0;
    }
  }, [active, src]);

  if (!src || brokenSrc === src) {
    return <div aria-hidden className="absolute inset-0" style={accentBackdrop(accent)} />;
  }

  return (
    <video
      ref={ref}
      key={src}
      src={src}
      muted
      loop
      playsInline
      preload="metadata"
      aria-hidden
      tabIndex={-1}
      onError={() => setBrokenSrc(src)}
      className="absolute inset-0 size-full object-cover"
    />
  );
}

export function GeneratedPost({ post, active }: { post: Post; active: boolean }) {
  // Once the render pipeline has produced an MP4, play that; the storyboard is kept
  // on the post for the Spec view. Without an MP4 (tooling absent, or still on the
  // browser-reel path) fall back to the live scene player. Two components, so the
  // hooks in each stay stable regardless of which path a post takes.
  if (post.mediaUrl) return <GeneratedVideo post={post} active={active} />;
  return <GeneratedReel post={post} active={active} />;
}

/** A generated explainer that has been rendered to an MP4. Plays the file, keeps the
 *  "AI reel" badge and the Spec citation action that a plain clip does not have. */
function GeneratedVideo({ post, active }: { post: Post; active: boolean }) {
  const { muted } = useMute();
  const ref = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [broken, setBroken] = useState(false);
  const src = post.mediaUrl;
  const usable = Boolean(src) && !broken;

  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    if (active) {
      void video.play().catch(() => {
        // Autoplay refused (usually unmuted). The centre play overlay is the recovery.
      });
    } else {
      video.pause();
      video.currentTime = 0;
    }
  }, [active]);

  function toggle() {
    const video = ref.current;
    if (!video) return;
    if (video.paused) void video.play().catch(() => {});
    else video.pause();
  }

  return (
    <article
      aria-label={`Generated reel: ${post.title}`}
      className="relative size-full overflow-hidden bg-neutral-950"
    >
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
          className="absolute inset-0 size-full object-cover"
        />
      ) : (
        <div aria-hidden className="absolute inset-0" style={accentBackdrop(post.accent)} />
      )}

      {/* Bands, as on ClipPost: the badge and PostMeta sit over arbitrary rendered
          footage, and without these the metadata was raw white text on the frame. */}
      <div
        aria-hidden
        className="absolute inset-x-0 top-0 z-10 h-24 bg-gradient-to-b from-neutral-950/85 to-transparent"
      />
      <div
        aria-hidden
        className="absolute inset-x-0 bottom-0 z-10 h-2/5 bg-gradient-to-t from-neutral-950 via-neutral-950/70 to-transparent"
      />

      <button
        type="button"
        tabIndex={active ? 0 : -1}
        onClick={toggle}
        aria-label={playing ? 'Pause reel' : 'Play reel'}
        className="absolute inset-0 z-20 grid place-items-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-400"
      >
        {!playing ? (
          <span className="grid size-16 place-items-center rounded-full border border-white/20 bg-neutral-950/70 text-white backdrop-blur-md">
            <Icon name="play" label={null} filled className="size-7 translate-x-0.5" />
          </span>
        ) : null}
      </button>

      <div className="pointer-events-none absolute inset-x-0 top-0 z-30 flex items-center gap-2 px-4 pt-4">
        <span className="panel flex items-center gap-1.5 px-2.5 py-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-neutral-300">
          <Icon name="sparkle" label={null} className="size-3.5 shrink-0 text-brand-300" />
          AI reel
        </span>
        <MuteButton className="ml-auto" />
      </div>

      <div className="absolute inset-x-0 bottom-0 z-30 flex flex-col gap-3 pb-16">
        <div className="pl-4 pr-20">
          <PostMeta post={post} />
        </div>
      </div>

      <ActionRail post={post} specHref={docHref(post.storyboard)} />
    </article>
  );
}

function GeneratedReel({ post, active }: { post: Post; active: boolean }) {
  const scenes = useMemo(() => post.storyboard?.scenes ?? [], [post.storyboard]);
  const { muted, rate } = useMute();
  // Unmuted, the voice paces the reel and the timer stands down. See useNarration.
  const spoken = !muted && active;
  const { index, count, scene, caption, playing, setPlaying, next, prev, advance } = useReel(
    scenes,
    active,
    spoken,
  );

  // Left/right arrows move scenes, stories-style. Only the visible post listens.
  useEffect(() => {
    if (!active) return;

    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.isContentEditable)) return;

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
  }, [active, next, prev]);

  /**
   * Narration speaks the caption on screen, and finishing it advances the reel. The
   * shared mute control is what turns it on — there is no audio track to unmute — so
   * nothing is ever spoken before a click, which also keeps it clear of autoplay policy.
   */
  useNarration({
    text: caption,
    enabled: spoken && playing,
    rate,
    onDone: advance,
  });

  if (!scene) {
    return (
      <article
        aria-label={`Generated reel: ${post.title}`}
        className="relative size-full overflow-hidden bg-neutral-950"
      >
        <div aria-hidden className="absolute inset-0" style={accentBackdrop(post.accent)} />
        <div className="absolute inset-0 scrim-heavy" />
        <p className="panel absolute left-4 right-4 top-1/2 -translate-y-1/2 p-4 text-center text-sm text-neutral-300">
          <Icon name="alert" label={null} className="mx-auto mb-2 size-5 text-warning" />
          This reel has no scenes yet.
        </p>
        <div className="absolute inset-x-0 bottom-0 z-30 pb-16 pl-4 pr-20">
          <PostMeta post={post} />
        </div>
        <ActionRail post={post} specHref={docHref(post.storyboard)} />
      </article>
    );
  }

  return (
    <article
      aria-label={`Generated reel: ${post.title}`}
      className="relative size-full overflow-hidden bg-neutral-950"
    >
      <Broll src={brollSrc(scene)} accent={post.accent} active={active} />
      <div aria-hidden className={`absolute inset-0 ${scrimFor(scene.type)}`} />

      {/*
       * SceneShell owns its own safe-area padding AND the citation chip for the
       * current scene (scenes/SceneShell.tsx), so this layer is edge to edge and the
       * feed does not render a second chip.
       *
       * ABOVE the tap zones, not below. This layer is pointer-events-none, so a tap on
       * empty scene area still falls through to the zones underneath — but anything a
       * scene makes interactive (the outro's link, the code scene's scroll region)
       * re-enables pointer events and therefore actually receives its click. With the
       * zones on top, the outro's "Read the full spec" button was visible and dead.
       */}
      <div className="pointer-events-none absolute inset-0 z-20">
        <SceneView scene={scene} active={active} />
      </div>

      {/* Tap thirds: back, pause, forward. Keyboard equivalents live on window. */}
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

      <div className="absolute inset-x-0 bottom-0 z-30 flex flex-col gap-3 pb-16">
        <div className="pl-4 pr-20">
          <PostMeta post={post} />
        </div>
        {caption ? (
          <div className="px-4">
            <CaptionBar text={caption} />
          </div>
        ) : null}
      </div>

      <ActionRail post={post} specHref={docHref(post.storyboard)} />
    </article>
  );
}
