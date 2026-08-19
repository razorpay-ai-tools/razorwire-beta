'use client';

/**
 * Minimal in-frame comment sheet.
 *
 * Exists because the action rail must have a comment *button*, and a button that
 * does nothing is a defect. It is deliberately not the desktop inspector panel —
 * that slot is left empty for whoever owns it.
 */

import { useEffect, useRef, useState } from 'react';
import { Icon } from '@/components/ui';
import { api, initialsOf, type Comment } from '@/lib/api';

export function CommentSheet({
  postId,
  onClose,
  onCountChange,
}: {
  postId: string;
  onClose: () => void;
  onCountChange: (delta: number) => void;
}) {
  const [comments, setComments] = useState<Comment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let live = true;
    api
      .comments(postId)
      .then((items) => {
        if (live) setComments(items);
      })
      .catch(() => {
        if (live) setError('Could not load comments.');
      });
    return () => {
      live = false;
    };
  }, [postId]);

  useEffect(() => {
    closeRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const body = text.trim();
    if (!body || sending) return;

    setSending(true);
    setError(null);
    try {
      const created = await api.addComment(postId, body);
      setComments((current) => [created, ...(current ?? [])]);
      onCountChange(1);
      setText('');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Comment failed to send.');
    } finally {
      setSending(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-label="Comments"
      className="pointer-events-auto absolute inset-x-0 bottom-0 top-[38%] flex flex-col gap-3 rounded-t-2xl border-t border-white/10 bg-neutral-950/95 p-4 backdrop-blur-xl"
    >
      <div className="flex items-center justify-between">
        <h3 className="font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-neutral-300">
          Comments
        </h3>
        <button
          ref={closeRef}
          type="button"
          onClick={onClose}
          className="rounded-full p-1.5 text-neutral-400 transition-colors hover:text-white"
        >
          <Icon name="close" label="Close comments" className="size-4" />
        </button>
      </div>

      <ul className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain pr-1">
        {comments === null && !error ? (
          <li className="text-xs text-neutral-500">Loading…</li>
        ) : null}
        {comments?.length === 0 ? (
          <li className="text-xs text-neutral-500">No comments yet.</li>
        ) : null}
        {comments?.map((comment) => (
          <li key={comment.id} className="flex gap-2.5">
            <span
              aria-hidden
              className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-full border border-white/10 bg-neutral-900 font-mono text-[10px] font-bold text-brand-300"
            >
              {initialsOf(comment.author)}
            </span>
            <p className="min-w-0 text-sm leading-snug text-neutral-200">
              <span className="mr-1.5 font-semibold text-white">
                {comment.author.name || comment.author.email}
              </span>
              {comment.text}
            </p>
          </li>
        ))}
      </ul>

      {error ? (
        <p role="status" className="flex items-center gap-1.5 text-xs text-danger">
          <Icon name="alert" label={null} className="size-3.5 shrink-0" />
          {error}
        </p>
      ) : null}

      <form onSubmit={submit} className="flex items-center gap-2">
        <label htmlFor={`comment-${postId}`} className="sr-only">
          Add a comment
        </label>
        <input
          id={`comment-${postId}`}
          className="input"
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="Add a comment"
          maxLength={500}
        />
        <button
          type="submit"
          disabled={sending || text.trim().length === 0}
          className="shrink-0 rounded-xl bg-brand-500 p-2.5 text-white transition-colors hover:bg-brand-600 disabled:bg-neutral-800 disabled:text-neutral-500"
        >
          <Icon name="send" label="Post comment" className="size-4" />
        </button>
      </form>
    </div>
  );
}
