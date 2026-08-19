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
}: {
  value: string;
  onChange: (channelId: string) => void;
  disabled?: boolean;
  id?: string;
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
