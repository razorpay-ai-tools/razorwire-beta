'use client';

/**
 * An uploaded clip. Deliberately not a generated post with the interesting parts
 * removed.
 *
 * A clip has no scenes, so there is nothing to segment: it gets a continuous
 * position bar and a clock instead of a progress rail, tap-anywhere play/pause
 * instead of tap-thirds, its own description instead of burned-in captions, and no
 * citation or Spec affordance, because an upload makes no claim about a document.
 */

import { useEffect, useRef, useState } from 'react';
import { Icon } from '@/components/ui';
import type { Post } from '@/lib/api';
import { ActionRail } from './ActionRail';
import { MuteButton, PostMeta, accentBackdrop, useMute } from './chrome';

function clock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

export function ClipPost({ post, active }: { post: Post; active: boolean }) {
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
        // Refused (usually an unmuted autoplay). The play overlay is the recovery.
      });
    } else {
      video.pause();
      // Rewinding fires `timeupdate`, which is what resets the clock and the bar.
      video.currentTime = 0;
    }
  }, [active]);

  function toggle() {
    const video = ref.current;
    if (!video) return;
    if (video.paused) void video.play().catch(() => {});
    else video.pause();
  }

  function seek(next: number) {
    const video = ref.current;
    if (video) video.currentTime = next;
    setTime(next);
  }

  return (
    <article
      aria-label={`Clip: ${post.title}`}
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

      {/*
       * Bands, not the shared scrim recipe: a clip is footage someone shot, so it
       * stays visible mid-frame and only darkens where chrome sits.
       */}
      <div
        aria-hidden
        className="absolute inset-x-0 top-0 z-10 h-28 bg-gradient-to-b from-neutral-950/85 to-transparent"
      />
      <div
        aria-hidden
        className="absolute inset-x-0 bottom-0 z-10 h-2/5 bg-gradient-to-t from-neutral-950 via-neutral-950/70 to-transparent"
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
          <Icon name="play" label={null} filled className="size-3 shrink-0 text-neutral-400" />
          Clip
          <span aria-hidden className="text-neutral-600">
            &middot;
          </span>
          <span className="tabular-nums">{clock(duration)}</span>
        </span>
        <MuteButton className="ml-auto" />
      </div>

      <div className="absolute inset-x-0 bottom-0 z-30 flex flex-col gap-3 pb-16">
        <div className="pl-4 pr-20">
          <PostMeta post={post} />
          {post.description ? (
            <p className="mt-2 line-clamp-2 text-[13px] leading-snug text-neutral-300">
              {post.description}
            </p>
          ) : null}
        </div>

        {/*
         * Native range: keyboard seeking, drag, and touch for free, and it reads as
         * a video position bar rather than as story segments.
         */}
        <div className="flex items-center gap-3 px-4">
          <label htmlFor={`seek-${post.id}`} className="sr-only">
            Seek clip
          </label>
          <input
            id={`seek-${post.id}`}
            type="range"
            min={0}
            max={duration || 0}
            step={0.1}
            value={Math.min(time, duration || 0)}
            disabled={!usable || duration <= 0}
            onChange={(event) => seek(Number(event.target.value))}
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
      </div>

      {/* No Spec action: a clip has no source document. */}
      <ActionRail post={post} anchorClassName="bottom-56 right-3" />
    </article>
  );
}
