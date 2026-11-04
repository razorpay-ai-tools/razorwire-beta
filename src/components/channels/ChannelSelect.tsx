'use client';

/**
 * The channel picker on the create surfaces.
 *
 * A plain `<select>` on purpose: the list is short, the native control is keyboard
 * and screen-reader correct without any work, and a combobox would be a day spent
 * rebuilding what the platform ships.
 *
 * "No channel" is a real option. A post without one still reaches the main feed —
 * only the following feed and the channel views filter on it.
 */

import { useEffect, useState } from 'react';
import { api, type Channel } from '@/lib/api';

export function ChannelSelect({
  value,
  onChange,
  disabled = false,
  id = 'channel',
  lockedSlug,
  lockedReason,
}: {
  value: string;
  onChange: (channelId: string) => void;
  disabled?: boolean;
  id?: string;
  /**
   * Pin the picker to this channel and stop it being changed. A slug rather than an id,
   * because the caller cannot know an id the server generated.
   *
   * A LOCK, not a default, because the server enforces the same rule and overwrites
   * whatever it is sent (`create_post` and `_run_job` in main.py). Offering a free choice
   * the backend silently discards is worse than offering none: the post appears somewhere
   * the picker said it would not.
   */
  lockedSlug?: string;
  /** Why it is locked. Shown in place of the usual hint. */
  lockedReason?: string;
}) {
  const [channels, setChannels] = useState<Channel[]>([]);

  useEffect(() => {
    let live = true;
    api
      .channels()
      .then((list) => {
        if (live) setChannels(list);
      })
      .catch(() => {
        // A missing list is not a reason to block posting; the field stays empty.
      });
    return () => {
      live = false;
    };
  }, []);

  const locked = lockedSlug ? channels.find((channel) => channel.slug === lockedSlug) : undefined;

  /*
   * Report the locked channel upward so the request carries it too. Belt and braces: the
   * server pins it regardless, but sending the right value keeps the payload honest and
   * means a reader watching the network tab sees what actually happened.
   *
   * Safe to run on every change because it only ever fires when the resolved lock and the
   * current value disagree, so it settles in one pass rather than looping.
   */
  useEffect(() => {
    if (locked && value !== locked.id) onChange(locked.id);
  }, [locked, value, onChange]);

  return (
    <div>
      <label htmlFor={id} className="block text-xs font-semibold text-neutral-300">
        Channel
      </label>
      <select
        id={id}
        name={id}
        className="input mt-1.5 disabled:cursor-not-allowed disabled:opacity-70"
        value={locked ? locked.id : value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled || Boolean(lockedSlug)}
        aria-describedby={`${id}-hint`}
      >
        {/* While a lock is pending — the list has not arrived, or the channel does not
            exist yet — show the name rather than "No channel", which would be a lie. The
            server creates the channel on publish either way. */}
        {lockedSlug && !locked ? (
          <option value="">{lockedReason ? 'Announcements' : lockedSlug}</option>
        ) : (
          <option value="">No channel</option>
        )}
        {channels.map((channel) => (
          <option key={channel.id} value={channel.id}>
            {channel.name}
          </option>
        ))}
      </select>
      <p id={`${id}-hint`} className="mt-1.5 text-[11px] leading-relaxed text-neutral-500">
        {lockedSlug && lockedReason
          ? lockedReason
          : 'Followers of the channel see this in their Following feed.'}
      </p>
    </div>
  );
}
