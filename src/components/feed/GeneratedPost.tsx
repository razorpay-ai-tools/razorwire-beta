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
  AutoHide,
  ControlBar,
  DownloadButton,
  MuteButton,
  NarrationNotice,
  PostMeta,
  SpeedButton,
  accentBackdrop,
  useMute,
  usePlaybackRate,
  useSpeed,
} from './chrome';
import { accentStyle } from '@/lib/themes';
import { InteractivePlayer } from './InteractivePlayer';
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
  // A video post that also has its composition published can be flipped to it.
  const [interactive, setInteractive] = useState(false);
  const both = Boolean(post.mediaUrl && post.interactiveUrl);
  if (post.mediaUrl && !(interactive && both)) {
    return (
      <GeneratedVideo
        post={post}
        active={active}
        onSwitch={both ? () => setInteractive(true) : undefined}
      />
    );
  }
  if (post.interactiveUrl) {
    return (
      <GeneratedInteractive
        post={post}
        active={active}
        onSwitch={both ? () => setInteractive(false) : undefined}
      />
    );
  }
  return <GeneratedReel post={post} active={active} />;
}

/** Flips a post with both an MP4 and a composition between the two. */
export function StageSwitch({ to, onSwitch }: { to: 'Video' | 'Interactive'; onSwitch: () => void }) {
  return (
    <button
      type="button"
      onClick={onSwitch}
      aria-label={`Switch to ${to.toLowerCase()}`}
      title={`Switch to ${to.toLowerCase()}`}
      className="panel pointer-events-auto flex items-center gap-1.5 px-2.5 py-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-neutral-200 hover:text-white"
    >
      <Icon name={to === 'Video' ? 'play' : 'sparkle'} label={null} className="size-3.5 shrink-0" />
      {/* Icon-only on phones, where the label pushed download off the strip. */}
      <span className="hidden sm:inline">{to}</span>
    </button>
  );
}

/** A browser reel with a published HyperFrames composition: the themed, animated
 *  reel played live and scrubbable, instead of the plain DOM scenes. */
function GeneratedInteractive({
  post,
  active,
  onSwitch,
}: {
  post: Post;
  active: boolean;
  onSwitch?: () => void;
}) {
  const { muted } = useMute();
  return (
    <article
      aria-label={`Interactive reel: ${post.title}`}
      style={accentStyle(post)}
      className="relative flex size-full flex-col overflow-hidden bg-neutral-950"
    >
      {/* The reel burns its captions into its own bottom band, so the metadata gets a
          band of its own below the stage instead of a scrim over the captions. */}
      <div className="relative min-h-0 flex-1">
        <InteractivePlayer
          src={post.interactiveUrl as string}
          poster={post.thumbnailUrl}
          active={active}
          muted={muted}
        />
      </div>
      <ControlBar active={active}>
        <span className="panel flex items-center gap-1.5 px-2.5 py-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-neutral-300">
          <Icon
            name="sparkle"
            label={null}
            className="size-3.5 shrink-0 text-[var(--post-accent,var(--color-brand-300))]"
          />
          Interactive
        </span>
        {onSwitch ? <StageSwitch to="Video" onSwitch={onSwitch} /> : null}
        <MuteButton className="ml-auto" />
        <DownloadButton mediaUrl={post.mediaUrl} />
      </ControlBar>
      <div className="shrink-0 pb-20 pl-4 pr-20 pt-3">
        <PostMeta post={post} />
      </div>
      <ActionRail post={post} specHref={docHref(post.storyboard)} />
    </article>
  );
}

/** A generated explainer that has been rendered to an MP4. Plays the file, keeps the
 *  "AI reel" badge and the Spec citation action that a plain clip does not have. */
function GeneratedVideo({
  post,
  active,
  onSwitch,
}: {
  post: Post;
  active: boolean;
  onSwitch?: () => void;
}) {
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

  usePlaybackRate(ref, src);

  function toggle() {
    const video = ref.current;
    if (!video) return;
    if (video.paused) void video.play().catch(() => {});
    else video.pause();
  }

  return (
    <article
      aria-label={`Generated reel: ${post.title}`}
      style={accentStyle(post)}
      className="relative flex size-full flex-col overflow-hidden bg-neutral-950"
    >
      {/* Stage above, metadata below: the MP4 carries burned-in captions in its bottom
          band, and a full-bleed cover crop plus a 40% scrim hid exactly that band. */}
      <div className="relative min-h-0 flex-1">
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
            className="absolute inset-0 size-full object-contain"
          />
        ) : (
          <div aria-hidden className="absolute inset-0" style={accentBackdrop(post.accent)} />
        )}

        {/* Top band only: the badge strip sits over the frame's title padding. */}
        <div
          aria-hidden
          className="absolute inset-x-0 top-0 z-10 h-24 bg-gradient-to-b from-neutral-950/85 to-transparent"
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
      </div>

      <ControlBar active={active}>
        <span className="panel flex items-center gap-1.5 px-2.5 py-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-neutral-300">
          <Icon name="sparkle" label={null} className="size-3.5 shrink-0 text-brand-300" />
          AI reel
        </span>
        {onSwitch ? <StageSwitch to="Interactive" onSwitch={onSwitch} /> : null}
        <SpeedButton className="ml-auto" />
        <MuteButton />
        <DownloadButton mediaUrl={post.mediaUrl} />
      </ControlBar>

      <div className="shrink-0 pb-20 pl-4 pr-20 pt-3">
        <PostMeta post={post} />
      </div>

      <ActionRail post={post} specHref={docHref(post.storyboard)} />
    </article>
  );
}

function GeneratedReel({ post, active }: { post: Post; active: boolean }) {
  const scenes = useMemo(() => post.storyboard?.scenes ?? [], [post.storyboard]);
  const { muted } = useMute();
  // Unmuted, the voice paces the reel and the timer stands down. See useNarration.
  const spoken = !muted && active;
  const { rate } = useSpeed();
  const { index, count, scene, caption, playing, setPlaying, next, prev, advance } = useReel(
    scenes,
    active,
    spoken,
    rate,
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
   *
   * A scene with pre-generated audio (`audioUrl`, the kokoro voice) plays that instead
   * of the synthesizer. The file covers the whole scene's narration, so its `ended`
   * event advances the scene, not the line.
   */
  const audioUrl = scene?.audioUrl ?? null;
  // Where the voice has got to in this scene's audio, so the scene's own build-up
  // (diagram nodes, bullet rows) lands on the words rather than on a blind timer.
  // Null once there is no audio to follow, which is what selects that timer.
  const [progress, setProgress] = useState(0);
  useNarration({
    text: caption,
    audioUrl,
    enabled: spoken && playing,
    rate,
    onDone: audioUrl ? next : advance,
    onProgress: setProgress,
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
      style={accentStyle(post)}
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
        <SceneView
          scene={scene}
          active={active}
          progress={audioUrl && spoken ? progress : null}
        />
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

          {/* Grouped so the pair stays right-aligned. */}
          <div className="ml-auto flex items-center gap-2">
            <NarrationNotice />
            <SpeedButton />
            <MuteButton />
          </div>
        </div>
      </div>

      <AutoHide className="absolute inset-x-0 bottom-0 z-30 flex flex-col gap-3 pb-16">
        <div className="pl-4 pr-20">
          <PostMeta post={post} />
        </div>
        {caption ? (
          <div className="px-4">
            <CaptionBar text={caption} />
          </div>
        ) : null}
      </AutoHide>

      <ActionRail post={post} specHref={docHref(post.storyboard)} />
    </article>
  );
}
