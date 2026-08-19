'use client';

/**
 * The app shell. The feed is the product, so it is the default view and it owns the
 * whole viewport; creating is a sheet over it rather than a separate page.
 *
 * Deliberately one route. A three-day build does not need router state for two
 * sheets, and `h-dvh` snap scrolling survives fewer layout ancestors.
 */

import { useCallback, useState, type ReactNode } from 'react';
import { GeneratePanel } from '@/components/create/GeneratePanel';
import { UploadClipForm } from '@/components/create/UploadClipForm';
import { FeedScreen } from '@/components/feed/FeedScreen';
import { ThemeToggle } from '@/components/ThemeToggle';
import { Icon } from '@/components/ui';

type Sheet = 'none' | 'generate' | 'upload';

export default function Home() {
  const [sheet, setSheet] = useState<Sheet>('none');
  // Remounts the feed so a newly published post appears without a page reload.
  const [feedKey, setFeedKey] = useState(0);

  const onPublished = useCallback(() => {
    setSheet('none');
    setFeedKey((key) => key + 1);
  }, []);

  return (
    <main className="relative h-dvh w-full overflow-hidden bg-neutral-950">
      <FeedScreen key={feedKey} />

      {/*
       * App chrome sits at the BOTTOM. At the top it collided with the post's own
       * chrome — progress rail, AI-reel badge and mute all live in that strip, and the
       * create bar was drawn straight over them.
       */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-50 flex justify-center px-4 pb-4">
        <div className="pointer-events-auto flex items-center gap-1 rounded-full border border-white/10 bg-neutral-950/70 p-1 backdrop-blur-md">
          <button
            type="button"
            onClick={() => setSheet('generate')}
            className="flex items-center gap-1.5 rounded-full bg-brand-500 px-3.5 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-brand-600"
          >
            <Icon name="sparkle" label={null} className="size-3.5" />
            From a spec
          </button>
          <button
            type="button"
            onClick={() => setSheet('upload')}
            className="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold text-neutral-300 transition-colors hover:text-white"
          >
            <Icon name="upload" label={null} className="size-3.5" />
            Upload
          </button>
          <span aria-hidden className="mx-0.5 h-5 w-px bg-white/10" />
          <ThemeToggle />
        </div>
      </div>

      {sheet !== 'none' ? (
        <CreateSheet
          title={sheet === 'generate' ? 'Generate from a spec' : 'Upload a clip'}
          onClose={() => setSheet('none')}
        >
          {sheet === 'generate' ? (
            <GeneratePanel onPublished={onPublished} />
          ) : (
            <UploadClipForm onPublished={onPublished} />
          )}
        </CreateSheet>
      ) : null}
    </main>
  );
}

function CreateSheet({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div className="absolute inset-0 z-60 flex items-end justify-center bg-neutral-950/70 backdrop-blur-sm sm:items-center">
      {/* Click-away as a sibling button, not a handler on the container, so a click
          inside the panel cannot bubble out and close it. */}
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 cursor-default"
      />

      <section
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="relative z-10 flex max-h-[92dvh] w-full max-w-lg flex-col overflow-hidden rounded-t-2xl border border-neutral-800 bg-neutral-900 sm:rounded-2xl"
      >
        <header className="flex shrink-0 items-center justify-between border-b border-neutral-800 px-5 py-3.5">
          <h2 className="text-sm font-semibold text-white">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-neutral-400 transition-colors hover:bg-neutral-800 hover:text-white"
          >
            <Icon name="close" label="Close" className="size-4" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">{children}</div>
      </section>
    </div>
  );
}
