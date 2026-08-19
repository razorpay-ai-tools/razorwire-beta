'use client';

/**
 * The focus screen.
 *
 * Native scroll snap does the paging — no carousel library, no virtualisation, no
 * transform maths. Exactly one post is `active` at a time and only that post plays
 * anything; everything else is paused and rewound, so a ten-post feed is never ten
 * running videos and ten running timers.
 *
 * Two observers, both rooted on the scroll container: one decides which post is
 * active, one pages the cursor in. The sentinel is one pixel tall and lives past
 * the last snap point, so it is fetched via `rootMargin` rather than by ever
 * becoming visible — `snap-mandatory` would refuse to scroll to it.
 */

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Icon } from '@/components/ui';
import { api, type Post } from '@/lib/api';
import { FeedPost } from './FeedPost';
import { MuteProvider } from './chrome';

/** Fetch the next page while the reader still has this much feed left below them. */
const PREFETCH_MARGIN = '900px';

type Phase = 'loading' | 'ready' | 'error';

function messageFor(cause: unknown): string {
  return cause instanceof Error ? cause.message : 'Could not reach the feed.';
}

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable;
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="grid h-dvh w-full place-items-center bg-neutral-950 px-6">
      <div className="max-w-xs text-center">{children}</div>
    </div>
  );
}

export function FeedScreen({ aside }: { aside?: ReactNode }) {
  const [posts, setPosts] = useState<Post[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>('loading');
  const [error, setError] = useState<string | null>(null);
  const [paging, setPaging] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [reloadToken, setReloadToken] = useState(0);

  const scrollRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const viewed = useRef(new Set<string>());
  const inFlight = useRef(false);

  // First page. State only ever changes in the promise callbacks — updating it
  // synchronously in an effect body cascades an extra render.
  useEffect(() => {
    let live = true;
    inFlight.current = true;

    api
      .feed()
      .then((page) => {
        if (!live) return;
        setPosts(page.items);
        setCursor(page.nextCursor);
        setError(null);
        setPhase('ready');
      })
      .catch((cause: unknown) => {
        if (!live) return;
        setError(messageFor(cause));
        setPhase('error');
      })
      .finally(() => {
        inFlight.current = false;
      });

    return () => {
      live = false;
    };
  }, [reloadToken]);

  /** Subsequent pages. Only ever called from an observer or a click. */
  const loadMore = useCallback(async (from: string) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setPaging(true);

    try {
      const page = await api.feed(from);
      setPosts((current) => {
        // StrictMode double-invokes effects in dev; de-dupe rather than show doubles.
        const seen = new Set(current.map((post) => post.id));
        return [...current, ...page.items.filter((post) => !seen.has(post.id))];
      });
      setCursor(page.nextCursor);
      setError(null);
    } catch (cause) {
      setError(messageFor(cause));
    } finally {
      inFlight.current = false;
      setPaging(false);
    }
  }, []);

  // Which post is active. 60% visible is past the point where snap has committed.
  useEffect(() => {
    const root = scrollRef.current;
    if (!root || posts.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const index = Number((entry.target as HTMLElement).dataset.index);
          if (Number.isInteger(index)) setActiveIndex(index);
        }
      },
      { root, threshold: 0.6 },
    );

    root.querySelectorAll('[data-index]').forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, [posts.length]);

  // Paging. Held back while a tail request is failing so a dead API is not hammered.
  useEffect(() => {
    const root = scrollRef.current;
    const sentinel = sentinelRef.current;
    if (!root || !sentinel || !cursor || error) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void loadMore(cursor);
      },
      { root, rootMargin: `0px 0px ${PREFETCH_MARGIN} 0px` },
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [cursor, error, loadMore, posts.length]);

  // Views are the headline metric: one per post per session, on first activation.
  useEffect(() => {
    const post = posts[activeIndex];
    if (!post || viewed.current.has(post.id)) return;
    viewed.current.add(post.id);
    void api.registerView(post.id).catch(() => {
      // Keep it marked. A retry loop on a counter is worse than a lost count.
    });
  }, [activeIndex, posts]);

  // Up/down page the feed; left/right belong to the active post's scenes.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
      if (isTyping(event.target)) return;
      const root = scrollRef.current;
      if (!root) return;
      event.preventDefault();
      // No smooth behaviour: snap does the animating, per globals.css.
      root.scrollBy({ top: event.key === 'ArrowDown' ? root.clientHeight : -root.clientHeight });
    }

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  let body: ReactNode;

  if (phase === 'loading') {
    body = (
      <Centered>
        <div
          aria-hidden
          className="mx-auto size-12 animate-pulse rounded-2xl border border-neutral-800 bg-neutral-900"
        />
        <p role="status" className="mt-4 text-sm text-neutral-400">
          Loading the feed…
        </p>
      </Centered>
    );
  } else if (phase === 'error') {
    body = (
      <Centered>
        <Icon name="alert" label={null} className="mx-auto size-7 text-warning" />
        <h2 className="mt-3 text-base font-semibold text-white">The feed did not load</h2>
        <p className="mt-1.5 text-sm text-neutral-400">{error}</p>
        <button
          type="button"
          onClick={() => {
            setPhase('loading');
            setError(null);
            setReloadToken((token) => token + 1);
          }}
          className="mt-5 rounded-xl bg-brand-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-brand-600"
        >
          Try again
        </button>
      </Centered>
    );
  } else if (posts.length === 0) {
    body = (
      <Centered>
        <Icon name="sparkle" label={null} className="mx-auto size-7 text-brand-300" />
        <h2 className="mt-3 text-base font-semibold text-white">Nothing here yet</h2>
        <p className="mt-1.5 text-sm text-neutral-400">
          Post a clip, or turn a spec into an explainer, and it lands here.
        </p>
      </Centered>
    );
  } else {
    body = (
      <>
        {posts.map((post, index) => (
          <div key={post.id} data-index={index} className="h-dvh w-full shrink-0 snap-start">
            <FeedPost post={post} active={index === activeIndex} />
          </div>
        ))}
        {cursor ? <div ref={sentinelRef} aria-hidden className="h-px w-full" /> : null}
      </>
    );
  }

  const tailFailed = phase === 'ready' && error !== null;

  return (
    <MuteProvider>
      <div className="flex h-dvh w-full justify-center bg-neutral-950 md:gap-6 md:px-6">
        <div className="relative h-dvh w-full md:max-w-md">
          <div
            ref={scrollRef}
            className="h-dvh w-full snap-y snap-mandatory overflow-y-scroll overscroll-y-contain bg-neutral-950 md:rounded-2xl md:ring-1 md:ring-neutral-800"
          >
            {body}
          </div>

          {paging || tailFailed ? (
            <div className="absolute inset-x-0 bottom-3 z-40 flex justify-center px-4">
              {tailFailed ? (
                <button
                  type="button"
                  onClick={() => {
                    setError(null);
                    if (cursor) void loadMore(cursor);
                  }}
                  className="panel flex items-center gap-2 px-3 py-2 text-xs font-semibold text-neutral-100"
                >
                  <Icon name="alert" label={null} className="size-3.5 shrink-0 text-warning" />
                  More posts failed to load — retry
                </button>
              ) : (
                <p
                  role="status"
                  className="panel px-3 py-2 font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-neutral-300"
                >
                  Loading more…
                </p>
              )}
            </div>
          ) : null}
        </div>

        {/* Reserved for the inspector panel. Owned elsewhere; this is only the slot. */}
        <div className="hidden shrink-0 self-stretch overflow-y-auto py-6 md:block md:w-72 lg:w-80">
          {aside}
        </div>
      </div>
    </MuteProvider>
  );
}
