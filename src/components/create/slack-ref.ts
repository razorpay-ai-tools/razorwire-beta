/**
 * Slack permalink parsing for the generate form.
 *
 * Its own module rather than a helper inside GeneratePanel for one reason: this regex
 * has a twin in `backend/app/slack.py` (`_PERMALINK`), and a client regex that is
 * STRICTER than the server's rejects links the server would have accepted — which
 * reads as "Slack ingestion is broken", not as "two regexes disagreed". Keeping it
 * importable by plain node is what lets `__check.mts` pin the cases that differ.
 */

/**
 * Slack writes a permalink as `/archives/<channel>/p<10s><6us>` — the message
 * timestamp with its dot dropped.
 *
 * Mirrors the backend pattern, minus its optional `thread_ts` group: a link to a reply
 * is accepted here without reading it, because the server resolves a reply to its
 * parent thread and the channel id is the same either way.
 */
const PERMALINK = /^https?:\/\/[\w-]+\.slack\.com\/archives\/([A-Z][A-Z0-9]+)\/p\d{16}/;

/**
 * The channel id out of a Slack permalink, or null when it is not one.
 *
 * Returns the id rather than a boolean because the id is exactly what an operator has
 * to add to `SLACK_ALLOWED_CHANNELS`. The form shows it back, so nobody has to go
 * digging in Slack for a channel id after being told 403.
 */
export function parseSlackChannel(raw: string): string | null {
  return PERMALINK.exec(raw.trim())?.[1] ?? null;
}
