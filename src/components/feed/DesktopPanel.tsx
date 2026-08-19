'use client';

/**
 * The right half of the desktop card: who made this, what it was made from, the audit
 * trail, and the conversation about it.
 *
 * The audit trail is `StoryboardInspector`, not a second implementation of it. Pairing a
 * narration paragraph with the citation behind it is the product's whole argument, and
 * two copies of that logic is two chances for the pairing to drift.
 *
 * Height is allocated by priority, not by a fixed split. The audit trail grows; the
 * conversation sizes to its content and stops at a cap. An earlier fixed 42% split meant
 * an empty conversation held a third of the panel while the narration/citation spine —
 * the reason this layout exists — was cut down to a single row.
 *
 * The two are separated by surface, not just by a rule: the audit trail sits on the card's
 * own card surface, the conversation on a lifted surface-2 with a sticky label. They were
 * previously reported as reading like one continuous list.
 */

import { useEffect, useRef, useState, type FormEvent } from 'react';
import { StoryboardInspector } from '@/components/create/StoryboardInspector';
import { CategoryChip, Icon, type IconName } from '@/components/ui';
import {
  api,
  compactCount,
  docHref,
  initialsOf,
  type Comment,
  type Post,
  type Toggle,
} from '@/lib/api';

/** Marks an appended-but-unconfirmed comment so it can be replaced or rolled back. */
const PENDING_PREFIX = 'pending-';

/** The source is aidocs. Not Confluence, not Notion, not GitHub. */
const AIDOCS_HOST = 'aidocs.razorpay.com';

/**
 * Whether the conversation is expanded, for this tab only. Session storage rather than
 * local: "I don't want to read comments right now" is a mood, not a setting.
 */
const CONVERSATION_KEY = 'rw.desktop.conversation';

function readConversationPref(): boolean {
  if (typeof window === 'undefined') return true;
  try {
    return window.sessionStorage.getItem(CONVERSATION_KEY) !== 'collapsed';
  } catch {
    // Storage can throw when the browser blocks it. Defaulting to open is harmless.
    return true;
  }
}

function writeConversationPref(open: boolean): void {
  try {
    window.sessionStorage.setItem(CONVERSATION_KEY, open ? 'open' : 'collapsed');
  } catch {
    // Not worth surfacing: the panel still works, the choice just will not survive.
  }
}

function hostOf(href: string): string {
  try {
    // The base only ever applies to a relative href, which aidocs links are not.
    return new URL(href, `https://${AIDOCS_HOST}`).host;
  } catch {
    return AIDOCS_HOST;
  }
}

/**
 * The API serialises UTC timestamps without an offset (SQLite drops tzinfo), and JS
 * reads an offset-less string as local time. Left alone, every comment in IST reads as
 * "5h ago" the moment it is posted.
 */
function parsedAt(iso: string): number {
  const normalised = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : `${iso}Z`;
  return new Date(normalised).getTime();
}

function timeAgo(iso: string): string {
  const at = parsedAt(iso);
  if (!Number.isFinite(at)) return '';
  const minutes = Math.round((Date.now() - at) / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

interface DesktopPanelProps {
  post: Post;
  /** Only the active post fetches its conversation; the rest are off screen. */
  active: boolean;
  /** Scene on screen in the player. Undefined for a clip, which has no scenes. */
  currentIndex?: number;
}

export function DesktopPanel({ post, active, currentIndex }: DesktopPanelProps) {
  const [comments, setComments] = useState<Comment[] | null>(null);
  const [count, setCount] = useState(post.comments);
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const [open, setOpen] = useState(readConversationPref);
  const [like, setLike] = useState<Toggle>({ active: post.liked, count: post.likes });
  const [save, setSave] = useState<Toggle>({ active: post.saved, count: post.saves });
  const [failure, setFailure] = useState<string | null>(null);

  const composeRef = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  /**
   * Gated on the state it produces, not on a `useRef` latch. StrictMode double-invokes
   * this in dev: a latch set on the first invocation makes the second bail out, and the
   * first invocation's `live` flag is already false by then, so the response was
   * discarded and the conversation never left "Loading". `GET` is idempotent, so
   * repeating it in dev is the cheaper of the two mistakes.
   */
  useEffect(() => {
    if (!active || comments !== null || loadError !== null) return;
    let live = true;

    api
      .comments(post.id)
      .then((items) => {
        if (!live) return;
        setComments(items);
        setCount(items.length);
      })
      .catch(() => {
        if (live) setLoadError('Could not load the conversation.');
      });

    return () => {
      live = false;
    };
  }, [active, comments, loadError, post.id]);

  function setConversationOpen(next: boolean) {
    setOpen(next);
    writeConversationPref(next);
  }

  /** Append now, swap in the server's row on success, remove it and hand the text back on failure. */
  async function submit(event: FormEvent) {
    event.preventDefault();
    const body = text.trim();
    if (!body || sending) return;

    const pendingId = `${PENDING_PREFIX}${Date.now()}`;
    const pending: Comment = {
      id: pendingId,
      text: body,
      createdAt: new Date().toISOString(),
      // The panel does not know who you are, and one `/me` fetch per card to label a row
      // that is about to be replaced is not worth it.
      author: { id: pendingId, name: 'You', email: '', picture: null, bio: '' },
    };

    setComments((current) => [pending, ...(current ?? [])]);
    setCount((value) => value + 1);
    setText('');
    setSending(true);
    setSendError(null);

    try {
      const created = await api.addComment(post.id, body);
      if (!mounted.current) return;
      setComments((current) =>
        (current ?? []).map((item) => (item.id === pendingId ? created : item)),
      );
    } catch {
      if (!mounted.current) return;
      setComments((current) => (current ?? []).filter((item) => item.id !== pendingId));
      setCount((value) => Math.max(0, value - 1));
      setText(body);
      setSendError('Comment failed to send — your text is back in the box.');
    } finally {
      if (mounted.current) setSending(false);
    }
  }

  /** Flip now, reconcile with the server's count, roll all the way back on failure. */
  async function optimistic(
    current: Toggle,
    apply: (next: Toggle) => void,
    call: () => Promise<Toggle>,
    what: string,
  ) {
    apply({
      active: !current.active,
      count: Math.max(0, current.count + (current.active ? -1 : 1)),
    });
    setFailure(null);

    try {
      const next = await call();
      if (mounted.current) apply(next);
    } catch {
      if (!mounted.current) return;
      apply(current);
      setFailure(`Could not ${what}. Try again.`);
    }
  }

  const author = post.author.name || post.author.email;
  const href = docHref(post.storyboard);
  const storyboard = post.kind === 'generated' ? post.storyboard : null;
  const listId = `desktop-conversation-${post.id}`;

  return (
    <div
      data-testid="desktop-panel"
      /*
       * A bounded width, not `flex-1`: the player is the focal element and it is centred on
       * the viewport, which only works if the panel's width is a known quantity (see the
       * mirrored spacer in DesktopCard). `--rw-panel-w` is declared there and steps up at
       * xl/2xl; 21–28rem keeps the inspector inside the width it was designed for (md:w-96).
       */
      className="flex w-[var(--rw-panel-w)] min-w-0 shrink-0 flex-col border-l border-hairline bg-surface-1"
    >
      <header data-testid="panel-header" className="shrink-0 border-b border-hairline px-5 py-3">
        <div className="flex items-center gap-2.5">
          <span
            aria-hidden
            className="grid size-8 shrink-0 place-items-center rounded-full bg-brand-500 font-mono text-[11px] font-bold tracking-tight text-white"
          >
            {initialsOf(post.author)}
          </span>

          {/* One meta line, not three rows: author, team and reach read together. */}
          <p className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 text-xs">
            <span className="font-semibold text-ink">{author}</span>
            {post.team ? (
              <>
                <span aria-hidden className="text-ink-subtle">
                  &middot;
                </span>
                <span className="text-ink-muted">{post.team}</span>
              </>
            ) : null}
            {/* No separator dot before this one: the line wraps at narrow panel widths and
                the dot was left dangling at the end of the row. The icon separates it. */}
            <span className="inline-flex items-center gap-1 font-mono text-[11px] text-ink-muted">
              <Icon name="eye" label={null} className="size-3.5 shrink-0" />
              {compactCount(post.views)} views
            </span>
          </p>

          <CategoryChip category={post.channel ? `#${post.channel.slug}` : post.category} />
        </div>

        <h2 className="mt-2 text-pretty text-base font-semibold leading-snug tracking-tight text-ink">
          {post.title}
        </h2>

        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2 flex max-w-full items-center gap-2 rounded-lg border border-hairline bg-surface-2 px-2.5 py-1.5 text-[11px] transition hover:border-brand-500/50"
          >
            <Icon name="doc" label={null} className="size-3.5 shrink-0 text-brand-500" />
            <span className="font-semibold text-ink">Source spec</span>
            <span aria-hidden className="text-ink-subtle">
              &middot;
            </span>
            <span className="truncate font-mono text-ink-muted">{hostOf(href)}</span>
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        ) : (
          <p className="mt-2 flex items-start gap-1.5 text-[11px] leading-relaxed text-ink-subtle">
            <Icon name="alert" label={null} className="mt-px size-3.5 shrink-0 text-warning" />
            <span>
              {post.kind === 'clip'
                ? 'An uploaded clip. There is no source spec to check this against.'
                : 'Generated from a topic, not a document. There is no source spec to check this against.'}
            </span>
          </p>
        )}
      </header>

      {/*
       * The audit trail. Generated posts only — a clip cites nothing.
       *
       * `flex-1` so it absorbs every pixel the conversation does not claim, including all
       * of it when the conversation is collapsed.
       *
       * `[&>section]:border-l-0` drops the inspector's own left rule. It carries one for
       * when it is docked as a standalone side panel; here the card's divider is already
       * at that exact x, so the two stack into a 2px line in this band only.
       */}
      {storyboard ? (
        <div
          data-testid="panel-audit"
          /*
           * The mask fades the last few pixels of the scroll region. Without it the
           * trail clipped a narration line mid-word directly against the conversation
           * header, which reads as broken text instead of "there is more above".
           */
          className="min-h-0 flex-1 overflow-hidden [mask-image:linear-gradient(to_bottom,black_calc(100%-1.5rem),transparent)] [&>section]:border-l-0"
        >
          <StoryboardInspector storyboard={storyboard} currentIndex={currentIndex} />
        </div>
      ) : (
        /* A clip has no audit trail, and an empty band would read as a loading failure.
           Saying why also keeps the collapsed conversation from leaving a dead gap. */
        <div
          data-testid="panel-audit-absent"
          className="flex min-h-0 flex-1 flex-col justify-center gap-2 px-5 py-6 text-center"
        >
          <Icon name="quote" label={null} className="mx-auto size-5 text-ink-subtle" />
          <p className="text-[13px] font-medium text-ink-muted">No audit trail for a clip</p>
          <p className="mx-auto max-w-[34ch] text-[11px] leading-relaxed text-ink-subtle">
            Nothing here was generated from a document, so there is no narration to check
            against a citation. Uploaded video is taken at face value.
          </p>
        </div>
      )}

      <section
        aria-label="Conversation"
        data-testid="panel-conversation"
        /*
         * Lifted surface + its own rule, so it cannot be mistaken for more of the audit
         * list. Content height capped at 38% of the card when expanded; when collapsed it
         * is just the label bar and the audit trail takes the rest.
         */
        className={`flex min-h-0 shrink-0 flex-col border-t border-hairline bg-surface-2 ${
          open ? 'max-h-[38%]' : ''
        }`}
      >
        <div className="flex shrink-0 items-center gap-2 px-5 py-2.5">
          <h3 className="font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-ink-muted">
            Conversation{' '}
            <span className="tabular-nums text-ink-subtle">({compactCount(count)})</span>
          </h3>
          <button
            type="button"
            onClick={() => setConversationOpen(!open)}
            aria-expanded={open}
            aria-controls={listId}
            className="ml-auto flex items-center gap-1.5 rounded-lg border border-hairline bg-surface-2 px-2 py-1 text-[11px] font-semibold text-neutral-300 transition-colors hover:border-hairline hover:text-ink"
          >
            <Icon name={open ? 'close' : 'comment'} label={null} className="size-3 shrink-0" />
            {open ? 'Hide' : 'Show'}
            <span className="sr-only">the conversation</span>
          </button>
        </div>

        {/* Tailwind's `hidden` utility, not the `hidden` attribute: a `display:flex`
            class would win over the attribute's UA rule and the panel would stay open. */}
        <div id={listId} className={open ? 'flex min-h-0 flex-1 flex-col' : 'hidden'}>
          <ol className="min-h-0 flex-1 space-y-2.5 overflow-y-auto px-5 pb-3">
            {loadError ? (
              <li className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
                <Icon name="alert" label={null} className="size-3.5 shrink-0 text-warning" />
                {loadError}
                <button
                  type="button"
                  onClick={() => setLoadError(null)}
                  className="rounded-lg border border-hairline px-2 py-1 text-[11px] font-semibold text-ink transition-colors hover:border-ink-muted hover:text-ink"
                >
                  Try again
                </button>
              </li>
            ) : null}
            {comments === null && !loadError ? (
              <li className="text-xs text-ink-subtle">Loading the conversation…</li>
            ) : null}
            {comments?.length === 0 ? (
              <li className="text-xs text-ink-subtle">
                No comments yet. Reviewing a claim? Say which scene.
              </li>
            ) : null}
            {comments?.map((comment) => {
              const pending = comment.id.startsWith(PENDING_PREFIX);
              return (
                <li
                  key={comment.id}
                  className={`rounded-xl border border-hairline bg-surface-1 p-3 ${
                    pending ? 'opacity-70' : ''
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span
                      aria-hidden
                      className="grid size-6 shrink-0 place-items-center rounded-full bg-brand-500 font-mono text-[10px] font-bold text-white"
                    >
                      {initialsOf(comment.author)}
                    </span>
                    <span className="truncate text-xs font-semibold text-ink">
                      {comment.author.name || comment.author.email}
                    </span>
                    <span aria-hidden className="text-ink-subtle">
                      &middot;
                    </span>
                    {pending ? (
                      <span className="font-mono text-[10px] text-ink-muted">Sending…</span>
                    ) : (
                      <time
                        dateTime={comment.createdAt}
                        className="font-mono text-[10px] text-ink-subtle"
                      >
                        {timeAgo(comment.createdAt)}
                      </time>
                    )}
                  </div>

                  {/* Same spine as the audit trail: a rule ties the body to its author. */}
                  <p className="mt-2 border-l-2 border-hairline pl-3 text-[13px] leading-relaxed text-ink">
                    {comment.text}
                  </p>
                </li>
              );
            })}
          </ol>

          {sendError ? (
            <p
              role="status"
              className="mx-5 mb-2 flex shrink-0 items-center gap-1.5 text-[11px] text-danger"
            >
              <Icon name="alert" label={null} className="size-3.5 shrink-0" />
              {sendError}
            </p>
          ) : null}

          <form
            onSubmit={submit}
            className="flex shrink-0 items-center gap-2 border-t border-hairline px-5 py-2.5"
          >
            <label htmlFor={`desktop-comment-${post.id}`} className="sr-only">
              Add a comment
            </label>
            <input
              ref={composeRef}
              id={`desktop-comment-${post.id}`}
              className="input"
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="Add a comment"
              maxLength={500}
            />
            <button
              type="submit"
              disabled={sending || text.trim().length === 0}
              className="shrink-0 rounded-xl bg-brand-500 p-2.5 text-white transition-colors hover:bg-brand-600 disabled:bg-surface-2 disabled:text-ink-subtle"
            >
              <Icon name="send" label="Post comment" className="size-4" />
            </button>
          </form>
        </div>
      </section>

      <footer className="shrink-0 border-t border-hairline px-5 py-2.5">
        {failure ? (
          <p role="status" className="mb-2 flex items-center gap-1.5 text-[11px] text-danger">
            <Icon name="alert" label={null} className="size-3.5 shrink-0" />
            {failure}
          </p>
        ) : null}

        <div className="flex items-center gap-2">
          <PanelAction
            icon="bolt"
            text={like.active ? 'Liked' : 'Like'}
            label={like.active ? 'Remove like' : 'Like'}
            count={like.count}
            on={like.active}
            onClick={() =>
              void optimistic(like, setLike, () => api.toggleLike(post.id), 'like this')
            }
          />
          <PanelAction
            icon="comment"
            text="Comment"
            label="Write a comment"
            count={count}
            onClick={() => {
              setConversationOpen(true);
              // After the region has been revealed, not in the same frame.
              requestAnimationFrame(() => composeRef.current?.focus());
            }}
          />
          <PanelAction
            icon="bookmark"
            text={save.active ? 'Saved' : 'Save'}
            label={save.active ? 'Remove from saved' : 'Save'}
            count={save.count}
            on={save.active}
            onClick={() =>
              void optimistic(save, setSave, () => api.toggleSave(post.id), 'save this')
            }
          />
        </div>
      </footer>
    </div>
  );
}

/**
 * State is carried by the word, the icon fill AND `aria-pressed` — never by colour on its
 * own. `on` is undefined for the comment button, which is an action, not a toggle.
 */
function PanelAction({
  icon,
  text,
  label,
  count,
  on,
  onClick,
}: {
  icon: IconName;
  text: string;
  label: string;
  count: number;
  on?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      aria-label={`${label}, ${compactCount(count)}`}
      className={`flex flex-1 items-center justify-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-semibold transition-colors ${
        on
          ? 'border-brand-500 bg-brand-500 text-white'
          : 'border-hairline bg-surface-2 text-ink hover:border-hairline hover:text-ink'
      }`}
    >
      <Icon name={icon} label={null} filled={on} className="size-4 shrink-0" />
      <span>{text}</span>
      <span className={`font-mono tabular-nums ${on ? 'text-white/80' : 'text-ink-muted'}`}>
        {compactCount(count)}
      </span>
    </button>
  );
}
