/**
 * AiSites adapter smoke check. Run:
 *
 *   node src/lib/__check-aisites-api.mts
 *
 * No network. It mocks `/__flash_me__` and `/__flash_db__`, then drives the same
 * `api` object the UI imports.
 */

import assert from 'node:assert/strict';

process.env.NEXT_PUBLIC_BACKEND_MODE = 'aisites';
delete process.env.NEXT_PUBLIC_API_URL;

type Row = Record<string, unknown> & { id: string };

let viewer = {
  id: 'usr_one',
  email: 'one@razorpay.com',
  display_name: 'User One',
  avatar_url: null,
};

const db = new Map<string, Map<string, Row>>();
const calls: string[] = [];

function collection(name: string) {
  if (!db.has(name)) db.set(name, new Map());
  return db.get(name)!;
}

globalThis.fetch = async (input, init) => {
  const url = String(input);
  calls.push(url);

  if (url === '/__flash_me__') return Response.json(viewer);

  const match = url.match(/^\/__flash_db__\/([^/]+)(?:\/([^/]+))?$/);
  assert.ok(match, `unexpected fetch ${url}`);
  const [, name, rawId] = match;
  const rows = collection(name);
  const id = rawId ? decodeURIComponent(rawId) : null;
  const method = init?.method ?? 'GET';

  if (method === 'GET' && !id) return Response.json({ items: [...rows.values()] });
  if (method === 'GET' && id) {
    const row = rows.get(id);
    return row ? Response.json(row) : new Response('missing', { status: 404 });
  }
  if (method === 'PUT' && id) {
    if (!rows.has(id)) return new Response('missing', { status: 404 });
    const body = JSON.parse(String(init?.body)) as Row;
    rows.set(id, { ...body, id });
    return Response.json(rows.get(id));
  }
  if (method === 'POST' && !id) {
    const body = JSON.parse(String(init?.body)) as Row;
    const row = { ...body, id: `row_${rows.size + 1}` };
    rows.set(row.id, row);
    return Response.json(row);
  }
  if (method === 'DELETE' && id) {
    rows.delete(id);
    return new Response(null, { status: 204 });
  }

  return new Response('bad mock request', { status: 400 });
};

const { api, ApiError } = await import('./api.ts');

const me = await api.me();
assert.equal(me.email, 'one@razorpay.com');

const updated = await api.updateMe({ name: 'One Updated', bio: 'builder' });
assert.equal(updated.bio, 'builder');

const channel = await api.createChannel({ name: 'Storage Demos', description: 'shared state' });
assert.equal(channel.following, true);
assert.equal((await api.channels(true)).length, 1);

const post = await api.createPost({
  title: 'Uploaded clip metadata',
  kind: 'clip',
  mediaUrl: 'https://cdn.example.test/clip.mp4',
  channelId: channel.id,
});
assert.equal(post.author.email, 'one@razorpay.com');

viewer = {
  id: 'usr_two',
  email: 'two@razorpay.com',
  display_name: 'User Two',
  avatar_url: null,
};

assert.deepEqual(await api.toggleLike(post.id), { active: true, count: 1 });
assert.deepEqual(await api.toggleSave(post.id), { active: true, count: 1 });
const comment = await api.addComment(post.id, 'visible to everyone');
assert.equal(comment.author.email, 'two@razorpay.com');
assert.equal((await api.comments(post.id)).length, 1);
assert.equal((await api.registerView(post.id)).views, 1);

viewer = {
  id: 'usr_one',
  email: 'one@razorpay.com',
  display_name: 'User One',
  avatar_url: null,
};

const feed = await api.feed(null, { channel: channel.slug });
assert.equal(feed.items.length, 1);
assert.equal(feed.items[0].likes, 1);
assert.equal(feed.items[0].saves, 1);
assert.equal(feed.items[0].comments, 1);
assert.equal(feed.items[0].liked, false);
assert.equal(feed.items[0].saved, false);

assert.equal((await api.profile('usr_one')).posts, 1);
await api.deleteComment(comment.id);
assert.equal((await api.comments(post.id)).length, 0);
await api.deletePost(post.id);
assert.equal((await api.feed()).items.length, 0);

assert.throws(() => api.upload(new File(['x'], 'clip.mp4')), ApiError);
assert.throws(() => api.generate({ kind: 'aidoc', input: '', docId: 'doc_x' }), ApiError);

assert.ok(calls.every((url) => url.startsWith('/__flash_')), calls.join('\n'));
console.log('ok — AiSites adapter social/feed ops use only /__flash_* with dummy users');
