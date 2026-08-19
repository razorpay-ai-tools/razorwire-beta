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

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Icon } from '@/components/ui';
import { api, type FeedFilter, type FeedPage, type Post } from '@/lib/api';
import { FeedPost } from './FeedPost';
import { MuteProvider } from './chrome';

/** Fetch the next page while the reader still has this much feed left below them. */
const PREFETCH_MARGIN = '900px';
const FEED_CACHE_KEY = 'razorwire.feed.v1';
const FEED_REFRESH_MS = 15_000;

type Phase = 'loading' | 'ready' | 'error';

function messageFor(cause: unknown): string {
  return cause instanceof Error ? cause.message : 'Could not reach the feed.';
}

/**
 * One cache entry per slice, not one for the feed.
 *
 * The cache is keyed on the filter because "For you", "Following" and a single
 * channel are different lists behind the same component. A single key would paint
 * the previous slice's posts under the new slice's heading, which reads as a bug in
 * follow rather than as a stale cache.
 */
function cacheKeyFor(filterKey: string): string {
  return `${FEED_CACHE_KEY}:${filterKey}`;
}

function readCachedFeed(key: string): FeedPage | null {
  if (typeof window === 'undefined') return null;
  try {
    const cached = localStorage.getItem(key);
    if (!cached) return null;
    const page = JSON.parse(cached) as FeedPage;
    return Array.isArray(page.items) ? page : null;
  } catch {
    return null;
  }
}

function writeCachedFeed(key: string, page: FeedPage) {
  try {
    localStorage.setItem(key, JSON.stringify(page));
  } catch {
    // Cache is an optimization. Private mode/quota failures should not break feed.
  }
}

function mergeFirstPage(current: Post[], fresh: Post[]): Post[] {
  const ids = new Set(fresh.map((post) => post.id));
  return [...fresh, ...current.filter((post) => !ids.has(post.id))];
}

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable;
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="grid h-dvh w-full place-items-center bg-surface-0 px-6">
      <div className="max-w-xs text-center">{children}</div>
    </div>
  );
}

interface FeedScreenProps {
  aside?: ReactNode;
  /** Which slice to read. Changing it refetches from page one. */
  filter?: FeedFilter;
  /** Shown instead of the stock copy when the slice is empty. */
  emptyNote?: ReactNode;
}

export function FeedScreen({ aside, filter, emptyNote }: FeedScreenProps) {
  // Callers pass an object literal, so its identity changes every render. Key the
  // fetches on the values instead, or the feed refetches forever.
  const filterKey = JSON.stringify(filter ?? {});
  const activeFilter = useMemo(() => JSON.parse(filterKey) as FeedFilter, [filterKey]);
  const cacheKey = cacheKeyFor(filterKey);

  /*
   * The cache is NOT read while rendering. `localStorage` does not exist on the server,
   * so seeding state from it made the server render "Loading the feed…" while the client
   * rendered the cached posts, and React threw the whole tree away with a hydration
   * error. It is applied in the fetch effect below instead, which costs one frame of the
   * skeleton and is the honest price of server rendering.
   */
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

  // A different slice means everything on screen belongs to the previous one. Reset
  // during render rather than in an effect, which would paint the stale posts once.
  const [trackedFilter, setTrackedFilter] = useState(filterKey);
  if (trackedFilter !== filterKey) {
    setTrackedFilter(filterKey);
    setPosts([]);
    setCursor(null);
    setActiveIndex(0);
    setError(null);
    setPhase('loading');
  }

  // First page. State only ever changes in the promise callbacks — updating it
  // synchronously in an effect body cascades an extra render.
  useEffect(() => {
    let live = true;

    async function refresh(quiet: boolean) {
      if (inFlight.current) return;
      inFlight.current = true;
      try {
        const page = await api.feed(null, activeFilter);
        if (!live) return;
        setPosts((current) => (quiet ? mergeFirstPage(current, page.items) : page.items));
        setCursor(page.nextCursor);
        writeCachedFeed(cacheKey, page);
        setError(null);
        setPhase('ready');
      } catch (cause: unknown) {
        if (!live) return;
        setError(messageFor(cause));
        if (!quiet) setPhase('error');
      } finally {
        inFlight.current = false;
      }
    }

    /*
     * Paint this slice's cache, then refresh behind it. In a callback, not in the effect
     * body: reading it during render broke hydration (no `localStorage` on the server),
     * and setting state straight from the body cascades a render — which is also what
     * `react-hooks/set-state-in-effect` is there to stop.
     *
     * Quiet only when there was something to paint. A first visit to a channel has to be
     * able to show its loading and error states.
     */
    void Promise.resolve().then(() => {
      if (!live) return;
      const cached = readCachedFeed(cacheKey);
      if (cached) {
        setPosts(cached.items);
        setCursor(cached.nextCursor);
        setPhase('ready');
      }
      void refresh(cached !== null);
    });

    const interval = window.setInterval(() => {
      if (document.visibilityState === 'visible') void refresh(true);
    }, FEED_REFRESH_MS);

    return () => {
      live = false;
      window.clearInterval(interval);
    };
  }, [reloadToken, activeFilter, cacheKey]);

  /**
   * Subsequent pages. Only ever called from an observer or a click.
   *
   * The setters are in the dep list on purpose. It has to be memoized, because the
   * paging effect below takes it as a dependency and would re-subscribe its observer
   * on every render otherwise. But once this closed over `activeFilter`, the React
   * Compiler refused to preserve a `[activeFilter]` memoization — the deps it infers
   * include the setters — and skipped optimizing the whole component. `useState`
   * setters are stable for the life of the component, so naming them changes nothing
   * at runtime and satisfies both rules.
   */
  const loadMore = useCallback(
    async (from: string) => {
      if (inFlight.current) return;
      inFlight.current = true;
      setPaging(true);

      try {
        const page = await api.feed(from, activeFilter);
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
    },
    [activeFilter, setPaging, setPosts, setCursor, setError],
  );

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
          className="mx-auto size-12 animate-pulse rounded-2xl border border-hairline bg-surface-2"
        />
        <p role="status" className="mt-4 text-sm text-ink-muted">
          Loading the feed…
        </p>
      </Centered>
    );
  } else if (phase === 'error') {
    body = (
      <Centered>
        <Icon name="alert" label={null} className="mx-auto size-7 text-warning" />
        <h2 className="mt-3 text-base font-semibold text-ink">The feed did not load</h2>
        <p className="mt-1.5 text-sm text-ink-muted">{error}</p>
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
        <h2 className="mt-3 text-base font-semibold text-ink">Nothing here yet</h2>
        <p className="mt-1.5 text-sm text-ink-muted">
          {emptyNote ?? 'Post a clip, or turn a spec into an explainer, and it lands here.'}
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
      {/* lg:px-0 — from lg the post is a self-bounding card that centres its own player
          against the viewport, so outer padding here would shift it off the centre line. */}
      <div className="flex h-dvh w-full justify-center bg-surface-0 md:gap-6 md:px-6 lg:px-0">
        {/*
         * The 9:16 frame up to md. At lg the post itself becomes a split card that owns
         * its own frame, so the column goes full width and the outer ring comes off rather
         * than drawing a second border around the card's.
         *
         * `lg:max-w-none` matters: a max width here was capping the row the card centres
         * itself in, which pulled the player 72px left of the viewport's centre line.
         */}
        <div className="relative h-dvh w-full md:max-w-md lg:max-w-none">
          <div
            ref={scrollRef}
            className="h-dvh w-full snap-y snap-mandatory overflow-y-scroll overscroll-y-contain bg-surface-0 md:rounded-2xl md:ring-1 md:ring-hairline lg:rounded-none lg:ring-0"
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

        {/*
         * Optional side slot. Rendered only when something is passed: from lg the audit
         * trail lives inside the post's own card, so an always-present empty column would
         * just take 320px away from it.
         */}
        {aside ? (
          <div className="hidden shrink-0 self-stretch overflow-y-auto py-6 md:block md:w-72 lg:w-80">
            {aside}
          </div>
        ) : null}
      </div>
    </MuteProvider>
  );
}
