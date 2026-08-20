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

import { useEffect, useRef, useState } from 'react';
import { api, type Channel } from '@/lib/api';

export function ChannelSelect({
  value,
  onChange,
  disabled = false,
  id = 'channel',
  defaultSlug,
}: {
  value: string;
  onChange: (channelId: string) => void;
  disabled?: boolean;
  id?: string;
  /**
   * Preselect this channel once the list arrives, if nothing is chosen yet. A slug
   * rather than an id, because the caller cannot know an id the server generated.
   */
  defaultSlug?: string;
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

  /*
   * Apply `defaultSlug`. Separate from the fetch because it also has to fire when the
   * caller CHANGES the default — switching the generate form to a Slack source asks for
   * Announcements after the list has already loaded.
   *
   * Guarded by a ref, not by `value` alone. "No channel" is a real choice and it is also
   * the empty string, so a `!value` test cannot tell "not chosen yet" from "deliberately
   * chose none" — and would silently put the default back every time someone cleared it.
   * Recording the slug we applied means each default lands at most once and the reader's
   * choice is final. Fires from an effect rather than during render because it lifts
   * state to the parent.
   */
  const applied = useRef<string | null>(null);

  useEffect(() => {
    if (!defaultSlug || value || applied.current === defaultSlug) return;
    const match = channels.find((channel) => channel.slug === defaultSlug);
    if (!match) return;
    applied.current = defaultSlug;
    onChange(match.id);
  }, [defaultSlug, channels, value, onChange]);

  return (
    <div>
      <label htmlFor={id} className="block text-xs font-semibold text-neutral-300">
        Channel
      </label>
      <select
        id={id}
        name={id}
        className="input mt-1.5"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        aria-describedby={`${id}-hint`}
      >
        <option value="">No channel</option>
        {channels.map((channel) => (
          <option key={channel.id} value={channel.id}>
            {channel.name}
          </option>
        ))}
      </select>
      <p id={`${id}-hint`} className="mt-1.5 text-[11px] text-neutral-500">
        Followers of the channel see this in their Following feed.
      </p>
    </div>
  );
}
