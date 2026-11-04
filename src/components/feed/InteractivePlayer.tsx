'use client';

/**
 * The HyperFrames composition itself, played live: the same page the MP4 is rendered
 * from, so the interactive reel carries the theme, the motion and the diagram build-up
 * the video has, and can be scrubbed, paused and replayed scene by scene.
 *
 * The player registers a custom element that touches `HTMLElement` at import, so it is
 * imported inside the effect and never enters the server bundle.
 */

import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type DetailedHTMLProps,
  type HTMLAttributes,
} from 'react';

declare module 'react' {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX {
    interface IntrinsicElements {
      'hyperframes-player': DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> & {
        src: string;
        poster?: string;
        controls?: string;
        loop?: string;
        muted?: string;
      };
    }
  }
}

type PlayerElement = HTMLElement & {
  play(): void;
  pause(): void;
  seek(seconds: number): void;
};

export function InteractivePlayer({
  src,
  poster,
  active,
  muted,
  className = 'absolute inset-0 size-full',
}: {
  src: string;
  poster?: string | null;
  active: boolean;
  muted: boolean;
  className?: string;
}) {
  const ref = useRef<PlayerElement>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void import('@hyperframes/player').then(() => {
      if (!cancelled) setReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const player = ref.current;
    if (!ready || !player) return;
    if (active) {
      player.play();
    } else {
      player.pause();
      player.seek(0);
    }
  }, [active, ready]);

  // Boolean attributes as "" / undefined: a custom element gets attributes, not props.
  return (
    <hyperframes-player
      ref={ref}
      src={src}
      poster={poster ?? undefined}
      controls=""
      loop=""
      muted={muted ? '' : undefined}
      // The composition burns its captions just above the player's own control strip,
      // and the stock 0.7-black gradient under that strip dimmed their bottom line.
      style={{ '--hfp-controls-bg': 'linear-gradient(transparent, rgb(0 0 0 / 0.35))' } as CSSProperties}
      className={className}
    />
  );
}
