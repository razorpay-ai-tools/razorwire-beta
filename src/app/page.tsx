'use client';

/**
 * The app shell. The feed is the product, so it is the default view and it owns the
 * whole viewport; creating, channels and profiles are sheets over it rather than
 * separate pages.
 *
 * Deliberately one route. A three-day build does not need router state for four
 * sheets, and `h-dvh` snap scrolling survives fewer layout ancestors.
 *
 * `view` is a feed filter, not a page: For you, Following, one channel and one
 * person's videos are the same screen with a different WHERE — see `GET /feed`.
 */

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import Image from 'next/image';
import { ChannelsPanel } from '@/components/channels/ChannelsPanel';
import { GeneratePanel } from '@/components/create/GeneratePanel';
import { UploadClipForm } from '@/components/create/UploadClipForm';
import { FeedScreen } from '@/components/feed/FeedScreen';
import { ProfilePanel } from '@/components/profile/ProfilePanel';
import { ThemeToggle } from '@/components/ThemeToggle';
import { Icon } from '@/components/ui';
import { api, type ApiUser, type FeedFilter } from '@/lib/api';

type Sheet = 'none' | 'generate' | 'upload' | 'channels' | 'profile';

type View =
  | { kind: 'all' }
  | { kind: 'following' }
  | { kind: 'channel'; slug: string }
  | { kind: 'author'; id: string };

const SHEET_TITLE: Record<Exclude<Sheet, 'none'>, string> = {
  generate: 'Generate from a spec',
  upload: 'Upload a clip',
  channels: 'Channels',
  profile: 'Profile',
};

function filterFor(view: View): FeedFilter {
  if (view.kind === 'following') return { scope: 'following' };
  if (view.kind === 'channel') return { channel: view.slug };
  if (view.kind === 'author') return { author: view.id };
  return {};
}

function emptyNoteFor(view: View): string {
  if (view.kind === 'following') {
    return 'Nothing from the channels you follow yet. Follow a few more, or post something to one.';
  }
  if (view.kind === 'channel') return 'This channel has no videos yet. Post the first one.';
  if (view.kind === 'author') return 'This person has not posted anything yet.';
  return 'Post a clip, or turn a spec into an explainer, and it lands here.';
}

export default function Home() {
  const [sheet, setSheet] = useState<Sheet>('none');
  const [view, setView] = useState<View>({ kind: 'all' });
  const [me, setMe] = useState<ApiUser | null>(null);
  const [profileId, setProfileId] = useState<string | null>(null);
  // Remounts the feed so a newly published post appears without a page reload.
  const [feedKey, setFeedKey] = useState(0);

  useEffect(() => {
    let live = true;
    api
      .me()
      .then((user) => {
        if (live) setMe(user);
      })
      .catch(() => {
        // The feed already reports an unreachable API; the chrome need not say it twice.
      });
    return () => {
      live = false;
    };
  }, []);

  const onPublished = useCallback(() => {
    setSheet('none');
    setFeedKey((key) => key + 1);
  }, []);

  const openChannel = useCallback((slug: string) => {
    setView({ kind: 'channel', slug });
    setSheet('none');
  }, []);

  const openAuthor = useCallback((id: string) => {
    setView({ kind: 'author', id });
    setSheet('none');
  }, []);

  const scoped = view.kind === 'channel' || view.kind === 'author';

  return (
    <main className="relative h-dvh w-full overflow-hidden bg-surface-0">
      <FeedScreen key={feedKey} filter={filterFor(view)} emptyNote={emptyNoteFor(view)} />

      {/*
       * The app header. md+ only: below md the feed is full-bleed and every strip of
       * the frame already belongs to the post's own chrome (see the note on the bottom
       * bar), so phones carry the brand in the nav pill instead. From md the feed is a
       * centred card and the top-left corner is genuinely empty. Theme-aware surface —
       * unlike the nav pill this floats over the page, not over video.
       */}
      <header className="pointer-events-none absolute left-5 top-5 z-50 hidden md:block">
        <div className="pointer-events-auto flex items-center gap-2.5 rounded-full border border-hairline bg-surface-1/85 py-1.5 pl-2 pr-4 shadow-lg backdrop-blur-md">
          <Image
            src="/razorwire-logo.png"
            alt=""
            width={32}
            height={32}
            priority
            className="size-8 rounded-[9px]"
          />
          <span className="text-sm font-semibold tracking-tight text-ink">RazorWire</span>
        </div>
      </header>

      {/*
       * App chrome sits at the BOTTOM. At the top it collided with the post's own
       * chrome — progress rail, AI-reel badge and mute all live in that strip, and the
       * create bar was drawn straight over them. The active-filter pill goes here for
       * the same reason.
       */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-50 flex flex-col items-center gap-2 px-4 pb-4">
        {scoped ? (
          <div className="pointer-events-auto flex items-center gap-1.5 rounded-full border border-white/10 bg-[#131415]/80 py-1.5 pl-3 pr-1.5 backdrop-blur-md">
            <Icon
              name={view.kind === 'channel' ? 'hash' : 'user'}
              label={null}
              className="size-3.5 shrink-0 text-brand-300"
            />
            <span className="max-w-[50vw] truncate text-xs font-semibold text-white">
              {view.kind === 'channel' ? view.slug : 'One person’s videos'}
            </span>
            <button
              type="button"
              onClick={() => setView({ kind: 'all' })}
              className="rounded-full p-1 text-neutral-300 transition-colors hover:bg-white/10 hover:text-white"
            >
              <Icon name="close" label="Clear this filter" className="size-3.5" />
            </button>
          </div>
        ) : null}

        <div /* Deliberately a dark pill in both themes: it floats over the video stage, not
             over the page surface. gap-0.5 rather than gap-1: with the brand logo added,
             everything has to fit a 390px viewport minus px-4 — measured at 355px. */
          className="pointer-events-auto flex items-center gap-0.5 rounded-full border border-white/10 bg-[#131415]/80 p-1 backdrop-blur-md">
          {/* The brand on phones, where the md+ header above is hidden. Measured: with
              the logo the pill is 356px, exactly what a 390px viewport leaves it — so
              below 390 (where even the logo-less pill never fit) the logo yields. */}
          <Image
            src="/razorwire-logo.png"
            alt="RazorWire"
            width={28}
            height={28}
            className="size-7 shrink-0 rounded-lg max-[389px]:hidden md:hidden"
          />
          <ScopeTab
            label="For you"
            active={view.kind === 'all'}
            onClick={() => setView({ kind: 'all' })}
          />
          <ScopeTab
            label="Following"
            active={view.kind === 'following'}
            onClick={() => setView({ kind: 'following' })}
          />

          <span aria-hidden className="mx-0.5 h-5 w-px bg-white/10" />

          <IconTab icon="hash" label="Channels" onClick={() => setSheet('channels')} />
          <IconTab
            icon="user"
            label="Your profile"
            disabled={!me}
            onClick={() => {
              if (!me) return;
              setProfileId(me.id);
              setSheet('profile');
            }}
          />
          <IconTab
            icon="sparkle"
            label="Generate from a spec"
            onClick={() => setSheet('generate')}
          />
          <IconTab icon="upload" label="Upload a clip" onClick={() => setSheet('upload')} />

          <span aria-hidden className="mx-0.5 h-5 w-px bg-white/10" />
          <ThemeToggle />
        </div>
      </div>

      {sheet !== 'none' ? (
        <CreateSheet title={SHEET_TITLE[sheet]} onClose={() => setSheet('none')}>
          {sheet === 'generate' ? <GeneratePanel onPublished={onPublished} /> : null}
          {sheet === 'upload' ? <UploadClipForm onPublished={onPublished} /> : null}
          {sheet === 'channels' ? <ChannelsPanel onOpen={openChannel} /> : null}
          {sheet === 'profile' && profileId ? (
            <ProfilePanel
              userId={profileId}
              editable={profileId === me?.id}
              onOpenChannel={openChannel}
              onOpenPosts={openAuthor}
            />
          ) : null}
        </CreateSheet>
      ) : null}
    </main>
  );
}

function ScopeTab({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-semibold transition-colors ${
        active ? 'bg-brand-500 text-white' : 'text-neutral-300 hover:text-white'
      }`}
    >
      {label}
    </button>
  );
}

/** Icon-only so the whole bar still fits a phone. The label is the accessible name. */
function IconTab({
  icon,
  label,
  onClick,
  disabled = false,
}: {
  icon: 'hash' | 'user' | 'sparkle' | 'upload';
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      className="rounded-full p-1.5 text-neutral-300 transition-colors hover:bg-white/10 hover:text-white disabled:opacity-40"
    >
      <Icon name={icon} label={label} className="size-4" />
    </button>
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
