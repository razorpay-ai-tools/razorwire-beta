'use client';

/**
 * The right-hand action column, plus the comment sheet it opens.
 *
 * Rendered as a full-frame overlay layer rather than a floating column so the
 * sheet can be positioned against the post frame instead of against the rail.
 * Every affordance is a real `<button>` or `<a>`; state is carried by icon fill
 * and by the accessible name, never by colour alone.
 */

import { useState } from 'react';
import { Icon, type IconName } from '@/components/ui';
import { api, compactCount, type Post, type Toggle } from '@/lib/api';
import { CommentSheet } from './CommentSheet';

function RailButton({
  icon,
  label,
  count,
  filled = false,
  pressed,
  onClick,
}: {
  icon: IconName;
  label: string;
  count: number;
  filled?: boolean;
  pressed?: boolean;
  onClick: () => void;
}) {
  const shown = compactCount(count);

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={pressed}
      aria-label={`${label}, ${shown}`}
      className="flex w-14 flex-col items-center gap-1 py-1 text-neutral-100 transition-colors hover:text-white"
    >
      <span
        className={`grid size-11 place-items-center rounded-full border backdrop-blur-md transition-colors ${
          filled
            ? 'border-brand-400/60 bg-brand-500/30 text-brand-300'
            : 'border-white/15 bg-neutral-950/60'
        }`}
      >
        <Icon name={icon} label={null} filled={filled} className="size-[22px]" />
      </span>
      <span className="font-mono text-[11px] font-semibold tabular-nums text-neutral-200 [text-shadow:0_1px_2px_rgb(0_0_0/0.9)]">
        {shown}
      </span>
    </button>
  );
}

export function ActionRail({
  post,
  specHref = null,
  anchorClassName = 'bottom-48 right-3',
}: {
  post: Post;
  /** Source document link. Generated posts only, and only when the storyboard carries a URL. */
  specHref?: string | null;
  anchorClassName?: string;
}) {
  const [like, setLike] = useState<Toggle>({ active: post.liked, count: post.likes });
  const [save, setSave] = useState<Toggle>({ active: post.saved, count: post.saves });
  const [comments, setComments] = useState(post.comments);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

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
      apply(await call());
    } catch {
      apply(current);
      setFailure(`Could not ${what}. Try again.`);
    }
  }

  return (
    <div className="pointer-events-none absolute inset-0 z-30">
      <div className={`pointer-events-auto absolute flex flex-col items-center ${anchorClassName}`}>
        <RailButton
          icon="bolt"
          label={like.active ? 'Remove like' : 'Like'}
          count={like.count}
          filled={like.active}
          pressed={like.active}
          onClick={() => void optimistic(like, setLike, () => api.toggleLike(post.id), 'like this')}
        />

        <RailButton
          icon="comment"
          label={sheetOpen ? 'Hide comments' : 'Show comments'}
          count={comments}
          pressed={sheetOpen}
          onClick={() => setSheetOpen((open) => !open)}
        />

        <RailButton
          icon="bookmark"
          label={save.active ? 'Remove from saved' : 'Save'}
          count={save.count}
          filled={save.active}
          pressed={save.active}
          onClick={() => void optimistic(save, setSave, () => api.toggleSave(post.id), 'save this')}
        />

        {specHref ? (
          <a
            href={specHref}
            target="_blank"
            rel="noreferrer"
            className="flex w-14 flex-col items-center gap-1 py-1 text-neutral-100 transition-colors hover:text-white"
          >
            <span className="grid size-11 place-items-center rounded-full border border-white/15 bg-neutral-950/60 backdrop-blur-md">
              <Icon name="doc" label={null} className="size-[22px]" />
            </span>
            <span className="font-mono text-[10px] font-semibold uppercase tracking-wider text-neutral-200 [text-shadow:0_1px_2px_rgb(0_0_0/0.9)]">
              Spec
            </span>
            <span className="sr-only">Open the source document in a new tab</span>
          </a>
        ) : null}
      </div>

      {failure ? (
        <p
          role="status"
          className="pointer-events-auto absolute inset-x-4 bottom-2 flex items-center justify-center gap-1.5 rounded-lg border border-danger/40 bg-neutral-950/90 px-3 py-1.5 text-center text-[11px] font-medium text-neutral-100 backdrop-blur-md"
        >
          <Icon name="alert" label={null} className="size-3.5 shrink-0 text-danger" />
          {failure}
        </p>
      ) : null}

      {sheetOpen ? (
        <CommentSheet
          postId={post.id}
          onClose={() => setSheetOpen(false)}
          onCountChange={(delta) => setComments((count) => Math.max(0, count + delta))}
        />
      ) : null}
    </div>
  );
}
