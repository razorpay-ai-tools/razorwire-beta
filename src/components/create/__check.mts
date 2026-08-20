/**
 * Self-check for the Slack permalink parser. Run:
 *   node src/components/create/__check.mts
 *
 * Pinned because this regex has a twin — `_PERMALINK` in `backend/app/slack.py`. The
 * cases below are the ones where a hand-written client copy usually ends up stricter
 * than the server, and every one of them fails as "the form rejected my link" rather
 * than as anything that points at a regex.
 */

import assert from 'node:assert/strict';
import { parseSlackChannel } from './slack-ref.ts';

// The plain case, same shape the backend's own tests use.
assert.equal(
  parseSlackChannel('https://razorpay.slack.com/archives/C0192KLMN/p1755601234567800'),
  'C0192KLMN',
);

// A link to a REPLY, which is what "Copy link" gives you from inside a thread. The
// server resolves thread_ts to the parent, so the query string must not be rejected.
assert.equal(
  parseSlackChannel(
    'https://razorpay.slack.com/archives/C0192KLMN/p1755601299000100?thread_ts=1755601234.567800&cid=C0192KLMN',
  ),
  'C0192KLMN',
);

// Pasting out of Slack brings whitespace along.
assert.equal(
  parseSlackChannel('  https://razorpay.slack.com/archives/C0192KLMN/p1755601234567800  '),
  'C0192KLMN',
);

// A private-channel link: the id starts with G, not C. The backend accepts any
// uppercase-initial id, so a `C`-only client pattern would wrongly reject these.
assert.equal(
  parseSlackChannel('https://razorpay.slack.com/archives/GQ1W2E3R4/p1755601234567800'),
  'GQ1W2E3R4',
);

for (const bad of [
  '',
  'C0192KLMN',
  'https://razorpay.slack.com/archives/C0192KLMN', // no message timestamp
  'https://razorpay.slack.com/archives/C0192KLMN/p17556012', // timestamp too short
  'https://example.com/archives/C0192KLMN/p1755601234567800', // not slack
  'https://aidocs.razorpay.com/app/d/doc_r523noskel555f7f', // the other source
]) {
  assert.equal(parseSlackChannel(bad), null, `should have rejected: ${bad || '(empty)'}`);
}

console.log('ok — slack permalink parser');
