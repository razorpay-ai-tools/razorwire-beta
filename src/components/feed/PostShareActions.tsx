'use client';

/**
 * Download + Share for a generated post.
 *
 * Only a Deep Dive (rendered MP4) has a file to download or a link to share — a reel is
 * played in the browser from its storyboard and has no video file. So both actions are
 * enabled only when `post.mediaUrl` is set; for a reel they render greyed-out and
 * unclickable, with a hover tooltip explaining why.
 */

import { useState, type ReactNode } from 'react';
import { Icon } from '@/components/ui';
import { videoDownloadHref, type Post } from '@/lib/api';

const REEL_MESSAGE = 'Available only for Deep Dive videos';

export function PostShareActions({
  post,
  className = '',
  tone = 'panel',
}: {
  post: Post;
  className?: string;
  /** "panel" sits on the light desktop panel; "overlay" sits on the dark video stage. */
  tone?: 'panel' | 'overlay';
}) {
  const canDownload = Boolean(post.mediaUrl);
  const [copied, setCopied] = useState(false);

  async function copyLink() {
    if (!post.mediaUrl) return;
    try {
      await navigator.clipboard.writeText(post.mediaUrl);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard can be blocked (insecure context / permissions); nothing to recover.
    }
  }

  const pill =
    'group relative inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold transition';
  const on =
    tone === 'overlay'
      ? 'border-white/15 bg-neutral-950/60 text-neutral-100 backdrop-blur-md hover:border-white/30 hover:text-white'
      : 'border-hairline bg-surface-2 text-ink hover:border-brand-500/50';
  const off =
    tone === 'overlay'
      ? 'cursor-not-allowed border-white/10 bg-neutral-950/40 text-neutral-400 backdrop-blur-md'
      : 'cursor-not-allowed border-hairline bg-surface-2 text-ink-subtle';

  return (
    <div className={`flex flex-wrap items-center gap-2 ${className}`}>
      {canDownload ? (
        <a href={videoDownloadHref(post.id)} className={`${pill} ${on}`} title="Download this video">
          <Icon name="download" label={null} className="size-4" />
          Download
        </a>
      ) : (
        <span className={`${pill} ${off}`} aria-disabled="true" title={REEL_MESSAGE}>
          <Icon name="download" label={null} className="size-4" />
          Download
          <Tooltip>{REEL_MESSAGE}</Tooltip>
        </span>
      )}

      {canDownload ? (
        <button type="button" onClick={copyLink} className={`${pill} ${on}`} title="Copy a shareable link">
          <Icon name={copied ? 'check' : 'link'} label={null} className="size-4" />
          {copied ? 'Link copied' : 'Share'}
        </button>
      ) : (
        <span className={`${pill} ${off}`} aria-disabled="true" title={REEL_MESSAGE}>
          <Icon name="link" label={null} className="size-4" />
          Share
          <Tooltip>{REEL_MESSAGE}</Tooltip>
        </span>
      )}
    </div>
  );
}

function Tooltip({ children }: { children: ReactNode }) {
  return (
    <span
      role="tooltip"
      className="pointer-events-none absolute bottom-full left-1/2 z-40 mb-1.5 -translate-x-1/2 whitespace-nowrap rounded-md border border-white/10 bg-neutral-950 px-2 py-1 text-[11px] font-medium text-neutral-200 opacity-0 shadow-lg transition-opacity group-hover:opacity-100"
    >
      {children}
    </span>
  );
}
