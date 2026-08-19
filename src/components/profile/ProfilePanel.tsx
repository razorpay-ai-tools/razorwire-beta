'use client';

/**
 * A profile: who someone is, what they follow, and a way into their posts.
 *
 * Their videos are not listed here. `GET /feed?author=` returns them with the same
 * shape and pagination the feed already has, so "See their videos" hands the feed a
 * filter instead of this panel growing a second, worse feed.
 */

import { useEffect, useState, type FormEvent } from 'react';
import { api, initialsOf, type Profile } from '@/lib/api';
import { Icon } from '@/components/ui';

function messageOf(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

interface ProfilePanelProps {
  userId: string;
  /** True for the signed-in user, who may edit their name and bio. */
  editable?: boolean;
  onOpenChannel: (slug: string) => void;
  onOpenPosts: (userId: string) => void;
}

export function ProfilePanel({
  userId,
  editable = false,
  onOpenChannel,
  onOpenPosts,
}: ProfilePanelProps) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState('');
  const [bio, setBio] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .profile(userId)
      .then((next) => {
        if (!live) return;
        setProfile(next);
        setName(next.user.name);
        setBio(next.user.bio);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (live) setError(messageOf(cause, 'Could not load the profile.'));
      });
    return () => {
      live = false;
    };
  }, [userId]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const user = await api.updateMe({ name: name.trim(), bio: bio.trim() });
      setProfile((current) => (current ? { ...current, user } : current));
      setSaved(true);
    } catch (cause: unknown) {
      setError(messageOf(cause, 'Could not save the profile.'));
    } finally {
      setSaving(false);
    }
  }

  if (error && !profile) {
    return (
      <p
        role="alert"
        className="flex items-start gap-2 rounded-xl border border-danger/40 bg-danger/10 p-3 text-sm text-neutral-100"
      >
        <Icon name="alert" label="Error" className="mt-0.5 size-4 shrink-0 text-danger" />
        <span>{error}</span>
      </p>
    );
  }

  if (!profile) {
    return (
      <p role="status" className="text-sm text-neutral-400">
        Loading the profile…
      </p>
    );
  }

  const { user, posts, channels } = profile;

  return (
    <div className="space-y-5">
      <div className="flex items-start gap-3.5">
        <span
          aria-hidden
          className="grid size-12 shrink-0 place-items-center rounded-full border border-white/15 bg-neutral-900 font-mono text-sm font-bold text-brand-300"
        >
          {initialsOf(user)}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-base font-semibold tracking-tight text-neutral-50">{user.name}</h3>
          <p className="truncate font-mono text-[11px] text-neutral-500">{user.email}</p>
          {user.bio ? (
            <p className="mt-1.5 text-sm leading-relaxed text-neutral-300">{user.bio}</p>
          ) : null}
          <p className="mt-2 font-mono text-[10px] uppercase tracking-[0.14em] text-neutral-500">
            {posts} {posts === 1 ? 'video' : 'videos'} · following {channels.length}{' '}
            {channels.length === 1 ? 'channel' : 'channels'}
          </p>
        </div>
      </div>

      <button
        type="button"
        onClick={() => onOpenPosts(user.id)}
        className="inline-flex items-center gap-2 rounded-xl border border-neutral-700 bg-neutral-900 px-3.5 py-2 text-xs font-semibold text-neutral-100 transition hover:border-brand-500/50"
      >
        <Icon name="play" label={null} className="size-3.5 text-brand-300" filled />
        See their videos
      </button>

      <section aria-labelledby="profile-channels">
        <h4
          id="profile-channels"
          className="font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-brand-300"
        >
          Follows
        </h4>
        {channels.length === 0 ? (
          <p className="mt-2 text-sm text-neutral-400">
            No channels followed yet — the Channels sheet is where you pick some.
          </p>
        ) : (
          <ul className="mt-2 flex flex-wrap gap-2">
            {channels.map((channel) => (
              <li key={channel.id}>
                <button
                  type="button"
                  onClick={() => onOpenChannel(channel.slug)}
                  className="rounded-full border border-neutral-700 bg-neutral-900 px-3 py-1.5 text-xs font-medium text-neutral-200 transition hover:border-brand-500/50 hover:text-white"
                >
                  {channel.name}
                  <span className="ml-1.5 font-mono text-[10px] text-neutral-500">
                    {channel.posts}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {editable ? (
        <form onSubmit={save} className="panel space-y-3 p-4" noValidate>
          <div>
            <label htmlFor="profile-name" className="block text-xs font-semibold text-neutral-300">
              Display name
            </label>
            <input
              id="profile-name"
              name="profile-name"
              type="text"
              className="input mt-1.5"
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={saving}
            />
          </div>
          <div>
            <label htmlFor="profile-bio" className="block text-xs font-semibold text-neutral-300">
              Bio
            </label>
            <input
              id="profile-bio"
              name="profile-bio"
              type="text"
              className="input mt-1.5"
              placeholder="Payments platform. Explains mandates to anyone who asks."
              value={bio}
              onChange={(event) => setBio(event.target.value)}
              disabled={saving}
              maxLength={280}
            />
          </div>

          {error ? (
            <p
              role="alert"
              className="flex items-start gap-2 rounded-xl border border-danger/40 bg-danger/10 p-3 text-sm text-neutral-100"
            >
              <Icon name="alert" label="Error" className="mt-0.5 size-4 shrink-0 text-danger" />
              <span>{error}</span>
            </p>
          ) : null}

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={saving}
              className="rounded-xl bg-brand-500 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-600 disabled:opacity-60"
            >
              {saving ? 'Saving…' : 'Save profile'}
            </button>
            {saved ? (
              <p role="status" className="flex items-center gap-1.5 text-xs text-success">
                <Icon name="check" label={null} className="size-3.5" />
                Saved
              </p>
            ) : null}
          </div>
        </form>
      ) : null}
    </div>
  );
}
