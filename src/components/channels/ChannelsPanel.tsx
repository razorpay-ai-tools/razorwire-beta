'use client';

/**
 * Browse, follow and open channels; create one.
 *
 * The follow button writes optimistically and rolls back on failure — a follow that
 * waits for a round trip before it looks pressed reads as a dead button, and the
 * server's own count comes back in the same response so there is nothing to guess.
 */

import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { api, type Channel } from '@/lib/api';
import { Icon } from '@/components/ui';

function messageOf(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

export function ChannelsPanel({ onOpen }: { onOpen: (slug: string) => void }) {
  const [channels, setChannels] = useState<Channel[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setChannels(await api.channels());
      setLoadError(null);
    } catch (err: unknown) {
      setLoadError(messageOf(err, 'Could not load the channels.'));
    }
  }, []);

  // State is set from the promise callbacks, never synchronously in the effect body —
  // the latter cascades an extra render and the lint rule rejects it. `live` guards
  // against a resolve landing after unmount, and against StrictMode's double invoke.
  useEffect(() => {
    let live = true;
    api
      .channels()
      .then((rows) => {
        if (live) {
          setChannels(rows);
          setLoadError(null);
        }
      })
      .catch((err: unknown) => {
        if (live) setLoadError(messageOf(err, 'Could not load the channels.'));
      });
    return () => {
      live = false;
    };
  }, []);

  async function follow(channel: Channel) {
    const optimistic = {
      ...channel,
      following: !channel.following,
      followers: channel.followers + (channel.following ? -1 : 1),
    };
    setChannels((current) =>
      (current ?? []).map((c) => (c.id === channel.id ? optimistic : c)),
    );

    try {
      const result = await api.toggleFollow(channel.slug);
      setChannels((current) =>
        (current ?? []).map((c) =>
          c.id === channel.id ? { ...c, following: result.active, followers: result.count } : c,
        ),
      );
    } catch {
      setChannels((current) => (current ?? []).map((c) => (c.id === channel.id ? channel : c)));
    }
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed.length < 2) {
      setCreateError('Give the channel a name of at least two characters.');
      return;
    }

    setCreating(true);
    setCreateError(null);
    try {
      const channel = await api.createChannel({ name: trimmed, description: description.trim() });
      setName('');
      setDescription('');
      // Creating follows it server-side, so the list is refetched rather than patched.
      await load();
      onOpen(channel.slug);
    } catch (err: unknown) {
      setCreateError(messageOf(err, 'Could not create the channel.'));
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="space-y-5">
      <form onSubmit={create} className="panel space-y-3 p-4" noValidate>
        <div>
          <label htmlFor="channel-name" className="block text-xs font-semibold text-neutral-300">
            New channel
          </label>
          <input
            id="channel-name"
            name="channel-name"
            type="text"
            className="input mt-1.5"
            placeholder="Payments Core"
            value={name}
            onChange={(event) => setName(event.target.value)}
            disabled={creating}
          />
        </div>
        <div>
          <label
            htmlFor="channel-description"
            className="block text-xs font-semibold text-neutral-300"
          >
            What goes in it
          </label>
          <input
            id="channel-description"
            name="channel-description"
            type="text"
            className="input mt-1.5"
            placeholder="Mandates, refunds, routing — the money path."
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            disabled={creating}
          />
        </div>

        {createError ? (
          <p
            role="alert"
            className="flex items-start gap-2 rounded-xl border border-danger/40 bg-danger/10 p-3 text-sm text-neutral-100"
          >
            <Icon name="alert" label="Error" className="mt-0.5 size-4 shrink-0 text-danger" />
            <span>{createError}</span>
          </p>
        ) : null}

        <button
          type="submit"
          disabled={creating}
          className="inline-flex items-center gap-2 rounded-xl bg-brand-500 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-600 disabled:opacity-60"
        >
          <Icon name="sparkle" label={null} className="size-4" />
          {creating ? 'Creating…' : 'Create channel'}
        </button>
      </form>

      {loadError ? (
        <p
          role="alert"
          className="flex items-start gap-2 rounded-xl border border-danger/40 bg-danger/10 p-3 text-sm text-neutral-100"
        >
          <Icon name="alert" label="Error" className="mt-0.5 size-4 shrink-0 text-danger" />
          <span>{loadError}</span>
        </p>
      ) : null}

      {channels === null && !loadError ? (
        <p role="status" className="text-sm text-neutral-400">
          Loading channels…
        </p>
      ) : null}

      {channels?.length === 0 ? (
        <p className="text-sm text-neutral-400">
          No channels yet. The one you create above will be the first.
        </p>
      ) : null}

      <ul className="space-y-2">
        {(channels ?? []).map((channel) => (
          <li key={channel.id} className="panel flex items-start gap-3 p-4">
            <div className="min-w-0 flex-1">
              <button
                type="button"
                onClick={() => onOpen(channel.slug)}
                className="text-left text-sm font-semibold text-neutral-50 underline decoration-transparent underline-offset-4 transition hover:decoration-brand-500/60"
              >
                {channel.name}
              </button>
              {channel.description ? (
                <p className="mt-0.5 text-xs leading-relaxed text-neutral-400">
                  {channel.description}
                </p>
              ) : null}
              <p className="mt-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-neutral-500">
                {channel.posts} {channel.posts === 1 ? 'video' : 'videos'} · {channel.followers}{' '}
                {channel.followers === 1 ? 'follower' : 'followers'}
              </p>
            </div>

            <button
              type="button"
              onClick={() => void follow(channel)}
              aria-pressed={channel.following}
              className={`shrink-0 rounded-full px-3.5 py-1.5 text-xs font-semibold transition ${
                channel.following
                  ? 'border border-neutral-700 bg-neutral-900 text-neutral-300 hover:border-danger/50 hover:text-neutral-100'
                  : 'bg-brand-500 text-white hover:bg-brand-600'
              }`}
            >
              {channel.following ? 'Following' : 'Follow'}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
