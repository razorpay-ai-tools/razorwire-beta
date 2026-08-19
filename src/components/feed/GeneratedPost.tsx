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
import { MuteButton, PostMeta, accentBackdrop, useMute } from './chrome';
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
  const scenes = useMemo(() => post.storyboard?.scenes ?? [], [post.storyboard]);
  const { index, count, scene, caption, playing, setPlaying, next, prev } = useReel(scenes, active);
  const { muted } = useMute();

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
   * Narration is the Web Speech API on this path — there is no audio track to
   * unmute, so the shared mute control drives the speech synth instead. It only
   * ever starts after the user clicks unmute, which also keeps it clear of
   * autoplay policy.
   */
  useEffect(() => {
    const synth = typeof window === 'undefined' ? undefined : window.speechSynthesis;
    if (!synth || muted || !active || !scene) return;

    const utterance = new SpeechSynthesisUtterance(scene.narration);
    utterance.rate = 1.02;
    synth.speak(utterance);
    return () => synth.cancel();
  }, [muted, active, scene]);

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

          <MuteButton className="ml-auto" />
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
