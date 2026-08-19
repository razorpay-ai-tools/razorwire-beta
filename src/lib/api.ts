/**
 * Typed client for the Python backend.
 *
 * Field names here mirror the FastAPI response models exactly (camelCase on the
 * wire, via a Pydantic alias generator). If something does not exist on this
 * type, it does not exist on the API — the first design pass invented
 * `post.currentCitation`, `post.currentCaption` and `post.videoUrl`, none of which
 * the backend returns. Current scene and caption are client state; see
 * `useReel`.
 */

import type { Scene, Storyboard } from './storyboard.types';

const EXTERNAL_API_BASE = process.env.NEXT_PUBLIC_API_URL;
const BASE = EXTERNAL_API_BASE ?? 'http://localhost:8000';
const BACKEND_MODE = process.env.NEXT_PUBLIC_BACKEND_MODE ?? 'api';

export interface ApiUser {
  id: string;
  email: string;
  name: string;
  picture: string | null;
  bio: string;
}

/** What a post carries about its channel — enough to label and link it. */
export interface ChannelRef {
  id: string;
  slug: string;
  name: string;
}

export interface Channel extends ChannelRef {
  description: string;
  posts: number;
  followers: number;
  /** Whether the caller follows it. */
  following: boolean;
}

export interface Profile {
  user: ApiUser;
  posts: number;
  /** Channels this person follows. */
  channels: Channel[];
}

/** `generated` renders a storyboard; `clip` plays an uploaded video. */
export type PostKind = 'clip' | 'generated';

export interface Post {
  id: string;
  title: string;
  description: string;
  team: string;
  category: string;
  tags: string[];
  accent: string;
  kind: PostKind;
  mediaUrl: string | null;
  storageKey: string | null;
  thumbnailUrl: string | null;
  durationMs: number | null;
  storyboard: Storyboard | null;
  sourceDocId: string | null;
  views: number;
  createdAt: string;
  author: ApiUser;
  channel: ChannelRef | null;
  likes: number;
  saves: number;
  comments: number;
  liked: boolean;
  saved: boolean;
}

export interface FeedPage {
  items: Post[];
  nextCursor: string | null;
}

export interface Comment {
  id: string;
  text: string;
  author: ApiUser;
  createdAt: string;
}

export interface Toggle {
  active: boolean;
  count: number;
}

/**
 * Real job states from `backend/app/models.py`. The browser-reel path is
 * `queued -> scripting -> published`; `voicing` and `rendering` only occur on the
 * MP4 export path. Any stepper UI must render all six, including `failed` —
 * generation can legitimately fail when the model cannot satisfy the contract in
 * three attempts.
 */
export type JobState = 'queued' | 'scripting' | 'voicing' | 'rendering' | 'published' | 'failed';

export interface Job {
  id: string;
  state: JobState;
  progress: number;
  error: string | null;
  storyboard: Storyboard | null;
  postId: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface GenerateRequest {
  kind: 'aidoc' | 'topic';
  input: string;
  docId?: string;
  docTitle?: string;
  docUrl?: string;
}

export interface CreatePostRequest {
  title: string;
  description?: string;
  team?: string;
  category?: string;
  tags?: string[];
  accent?: string;
  kind: PostKind;
  mediaUrl?: string;
  storageKey?: string;
  thumbnailUrl?: string;
  durationMs?: number;
  storyboard?: Storyboard;
  sourceDocId?: string;
  channelId?: string;
}

/**
 * Which slice of the feed to read. All three are the same endpoint with an extra
 * WHERE — the home feed, a channel's videos and a profile's posts share pagination.
 */
export interface FeedFilter {
  scope?: 'all' | 'following';
  /** Channel slug. */
  channel?: string;
  /** Author user id. */
  author?: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'content-type': 'application/json' }),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    // FastAPI puts the message in `detail`; fall back to the status text
    let message = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === 'string') message = body.detail;
    } catch {
      // non-JSON error body, keep statusText
    }
    throw new ApiError(response.status, message);
  }

  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

const pythonApi = {
  me: () => request<ApiUser>('/me'),

  updateMe: (body: { name?: string; bio?: string }) =>
    request<ApiUser>('/me', { method: 'PATCH', body: JSON.stringify(body) }),

  profile: (userId: string) => request<Profile>(`/users/${userId}`),

  feed: (cursor?: string | null, filter: FeedFilter = {}, limit = 10) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (cursor) params.set('cursor', cursor);
    if (filter.scope) params.set('scope', filter.scope);
    if (filter.channel) params.set('channel', filter.channel);
    if (filter.author) params.set('author', filter.author);
    return request<FeedPage>(`/feed?${params}`);
  },

  channels: (following = false) =>
    request<Channel[]>(`/channels${following ? '?following=true' : ''}`),

  createChannel: (body: { name: string; description?: string }) =>
    request<Channel>('/channels', { method: 'POST', body: JSON.stringify(body) }),

  toggleFollow: (slug: string) =>
    request<Toggle>(`/channels/${slug}/follow`, { method: 'POST' }),

  post: (id: string) => request<Post>(`/posts/${id}`),

  createPost: (body: CreatePostRequest) =>
    request<Post>('/posts', { method: 'POST', body: JSON.stringify(body) }),

  deletePost: (id: string) => request<void>(`/posts/${id}`, { method: 'DELETE' }),

  toggleLike: (id: string) => request<Toggle>(`/posts/${id}/like`, { method: 'POST' }),
  toggleSave: (id: string) => request<Toggle>(`/posts/${id}/save`, { method: 'POST' }),
  registerView: (id: string) => request<{ views: number }>(`/posts/${id}/view`, { method: 'POST' }),

  comments: (id: string) => request<Comment[]>(`/posts/${id}/comments`),
  addComment: (id: string, text: string) =>
    request<Comment>(`/posts/${id}/comments`, { method: 'POST', body: JSON.stringify({ text }) }),
  deleteComment: (id: string) => request<void>(`/comments/${id}`, { method: 'DELETE' }),

  upload: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<{ mediaUrl: string; storageKey: string }>('/uploads', { method: 'POST', body: form });
  },

  generate: (body: GenerateRequest) =>
    request<Job>('/generate', { method: 'POST', body: JSON.stringify(body) }),

  job: (id: string) => request<Job>(`/jobs/${id}`),
};

type ApiClient = typeof pythonApi;

type FlashViewer = {
  id?: string;
  email: string;
  display_name?: string;
  name?: string;
  avatar_url?: string;
};

type FlashEnvelope<T> = { items?: unknown[] } | (T & { id?: string; data?: unknown });
type Stored<T> = T & { id: string };

type StoredPost = CreatePostRequest & {
  id: string;
  authorId: string;
  author: ApiUser;
  views: number;
  createdAt: string;
};

type StoredChannel = {
  id: string;
  slug: string;
  name: string;
  description: string;
  createdBy: string;
  createdAt: string;
};

type StoredReaction = {
  id: string;
  userId: string;
  postId?: string;
  channelId?: string;
  createdAt: string;
};

type StoredComment = {
  id: string;
  postId: string;
  authorId: string;
  author: ApiUser;
  text: string;
  createdAt: string;
};

async function flash<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body ? { 'content-type': 'application/json' } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) throw new ApiError(response.status, response.statusText);
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

function unwrap<T>(raw: unknown): Stored<T> {
  const row = raw as { id?: string; _id?: string; data?: unknown };
  const data = row.data && typeof row.data === 'object' ? row.data : row;
  return { ...(data as T), id: row.id ?? row._id ?? (data as { id?: string }).id ?? '' };
}

async function dbList<T>(collection: string): Promise<Stored<T>[]> {
  const body = await flash<FlashEnvelope<T>>(`/__flash_db__/${collection}`);
  const envelope = body as { items?: unknown[] };
  const items = Array.isArray(body) ? body : Array.isArray(envelope.items) ? envelope.items : [];
  return items.map((item) => unwrap<T>(item)).filter((item) => item.id);
}

async function dbGet<T>(collection: string, id: string): Promise<Stored<T> | null> {
  try {
    return unwrap<T>(await flash<FlashEnvelope<T>>(`/__flash_db__/${collection}/${id}`));
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

async function dbPut<T extends { id: string }>(collection: string, item: T): Promise<T> {
  await flash(`/__flash_db__/${collection}/${encodeURIComponent(item.id)}`, {
    method: 'PUT',
    body: JSON.stringify(item),
  });
  return item;
}

async function dbDelete(collection: string, id: string): Promise<void> {
  await flash<void>(`/__flash_db__/${collection}/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

function newId(prefix: string): string {
  const id = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `${prefix}_${id.replaceAll('-', '').slice(0, 16)}`;
}

function safeKey(...parts: string[]): string {
  return parts.join('_').replace(/[^a-zA-Z0-9_-]/g, '_');
}

function slugify(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

async function flashMe(): Promise<ApiUser> {
  const viewer = await flash<FlashViewer>('/__flash_me__');
  const id = viewer.id || viewer.email;
  const profile = await dbGet<Partial<ApiUser>>('profiles', id);
  return {
    id,
    email: viewer.email,
    name: profile?.name || viewer.display_name || viewer.name || viewer.email.split('@')[0],
    picture: profile?.picture ?? viewer.avatar_url ?? null,
    bio: profile?.bio ?? '',
  };
}

function postOut(
  post: StoredPost,
  counts: { likes: number; saves: number; comments: number },
  liked: boolean,
  saved: boolean,
  channel: ChannelRef | null,
): Post {
  return {
    id: post.id,
    title: post.title,
    description: post.description ?? '',
    team: post.team ?? '',
    category: post.category ?? 'Product',
    tags: post.tags ?? [],
    accent: post.accent ?? '',
    kind: post.kind,
    mediaUrl: post.mediaUrl ?? null,
    storageKey: post.storageKey ?? null,
    thumbnailUrl: post.thumbnailUrl ?? null,
    durationMs: post.durationMs ?? null,
    storyboard: post.storyboard ?? null,
    sourceDocId: post.sourceDocId ?? null,
    views: post.views ?? 0,
    createdAt: post.createdAt,
    author: post.author,
    channel,
    likes: counts.likes,
    saves: counts.saves,
    comments: counts.comments,
    liked,
    saved,
  };
}

async function hydratePosts(rows: StoredPost[], user: ApiUser): Promise<Post[]> {
  const [likes, saves, comments, channels] = await Promise.all([
    dbList<StoredReaction>('likes'),
    dbList<StoredReaction>('saves'),
    dbList<StoredComment>('comments'),
    dbList<StoredChannel>('channels'),
  ]);
  const channelById = new Map(channels.map((channel) => [channel.id, channel]));
  return rows.map((post) => {
    const channel = post.channelId ? channelById.get(post.channelId) : null;
    return postOut(
      post,
      {
        likes: likes.filter((like) => like.postId === post.id).length,
        saves: saves.filter((save) => save.postId === post.id).length,
        comments: comments.filter((comment) => comment.postId === post.id).length,
      },
      likes.some((like) => like.postId === post.id && like.userId === user.id),
      saves.some((save) => save.postId === post.id && save.userId === user.id),
      channel ? { id: channel.id, slug: channel.slug, name: channel.name } : null,
    );
  });
}

async function channelsOut(channels: StoredChannel[], user: ApiUser): Promise<Channel[]> {
  const [posts, follows] = await Promise.all([
    dbList<StoredPost>('posts'),
    dbList<StoredReaction>('follows'),
  ]);
  return channels.map((channel) => ({
    id: channel.id,
    slug: channel.slug,
    name: channel.name,
    description: channel.description ?? '',
    posts: posts.filter((post) => post.channelId === channel.id).length,
    followers: follows.filter((follow) => follow.channelId === channel.id).length,
    following: follows.some((follow) => follow.channelId === channel.id && follow.userId === user.id),
  }));
}

function requireExternalBackend(feature: string) {
  if (EXTERNAL_API_BASE) return;
  throw new ApiError(501, `${feature} needs NEXT_PUBLIC_API_URL pointing at the FastAPI backend`);
}

const aisitesApi: ApiClient = {
  me: flashMe,

  async updateMe(body) {
    const user = { ...(await flashMe()), ...body };
    return dbPut('profiles', user);
  },

  async profile(userId) {
    const [posts, channels, follows] = await Promise.all([
      dbList<StoredPost>('posts'),
      dbList<StoredChannel>('channels'),
      dbList<StoredReaction>('follows'),
    ]);
    const subject = posts.find((post) => post.author.id === userId)?.author
      ?? (await dbGet<Partial<ApiUser>>('profiles', userId))
      ?? { id: userId, email: userId, name: userId, picture: null, bio: '' };
    const followed = channels.filter((channel) =>
      follows.some((follow) => follow.userId === userId && follow.channelId === channel.id),
    );
    return {
      user: {
        id: subject.id,
        email: subject.email ?? subject.id,
        name: subject.name ?? subject.email ?? subject.id,
        picture: subject.picture ?? null,
        bio: subject.bio ?? '',
      },
      posts: posts.filter((post) => post.authorId === userId).length,
      channels: await channelsOut(followed, await flashMe()),
    };
  },

  async feed(cursor, filter = {}, limit = 10) {
    const user = await flashMe();
    const [posts, channels, follows] = await Promise.all([
      dbList<StoredPost>('posts'),
      dbList<StoredChannel>('channels'),
      dbList<StoredReaction>('follows'),
    ]);
    const channelId = filter.channel
      ? channels.find((channel) => channel.slug === filter.channel)?.id ?? '__missing__'
      : null;
    const followed = new Set(
      follows.filter((follow) => follow.userId === user.id).map((follow) => follow.channelId),
    );

    let rows = posts;
    if (channelId) rows = rows.filter((post) => post.channelId === channelId);
    if (filter.author) rows = rows.filter((post) => post.authorId === filter.author);
    if (filter.scope === 'following') rows = rows.filter((post) => post.channelId && followed.has(post.channelId));

    rows = rows.sort(
      (a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt) || b.id.localeCompare(a.id),
    );
    if (cursor) {
      const [rawTs, cursorId] = cursor.split('|');
      const cursorTs = Date.parse(rawTs);
      rows = rows.filter((post) => {
        const ts = Date.parse(post.createdAt);
        return ts < cursorTs || (ts === cursorTs && post.id < cursorId);
      });
    }

    const page = rows.slice(0, limit + 1);
    const items = page.slice(0, limit);
    return {
      items: await hydratePosts(items, user),
      nextCursor:
        page.length > limit && items.length
          ? `${items[items.length - 1].createdAt}|${items[items.length - 1].id}`
          : null,
    };
  },

  async channels(following = false) {
    const user = await flashMe();
    const [channels, follows] = await Promise.all([
      dbList<StoredChannel>('channels'),
      dbList<StoredReaction>('follows'),
    ]);
    const rows = following
      ? channels.filter((channel) =>
          follows.some((follow) => follow.userId === user.id && follow.channelId === channel.id),
        )
      : channels;
    return channelsOut(rows.sort((a, b) => a.name.localeCompare(b.name)), user);
  },

  async createChannel(body) {
    const user = await flashMe();
    const slug = slugify(body.name);
    if (!slug) throw new ApiError(422, 'the name needs at least one letter or digit');
    const channels = await dbList<StoredChannel>('channels');
    if (channels.some((channel) => channel.slug === slug)) {
      throw new ApiError(409, `channel ${slug} already exists`);
    }
    const channel = await dbPut<StoredChannel>('channels', {
      id: newId('chn'),
      slug,
      name: body.name.trim(),
      description: body.description?.trim() ?? '',
      createdBy: user.id,
      createdAt: new Date().toISOString(),
    });
    await dbPut<StoredReaction>('follows', {
      id: safeKey(user.id, channel.id),
      userId: user.id,
      channelId: channel.id,
      createdAt: new Date().toISOString(),
    });
    return (await channelsOut([channel], user))[0];
  },

  async toggleFollow(slug) {
    const user = await flashMe();
    const channel = (await dbList<StoredChannel>('channels')).find((item) => item.slug === slug);
    if (!channel) throw new ApiError(404, 'channel not found');
    const id = safeKey(user.id, channel.id);
    const existing = await dbGet<StoredReaction>('follows', id);
    if (existing) await dbDelete('follows', id);
    else {
      await dbPut<StoredReaction>('follows', {
        id,
        userId: user.id,
        channelId: channel.id,
        createdAt: new Date().toISOString(),
      });
    }
    const count = (await dbList<StoredReaction>('follows')).filter((follow) => follow.channelId === channel.id).length;
    return { active: !existing, count };
  },

  async post(id) {
    const user = await flashMe();
    const post = await dbGet<StoredPost>('posts', id);
    if (!post) throw new ApiError(404, 'post not found');
    return (await hydratePosts([post], user))[0];
  },

  async createPost(body) {
    if (body.kind === 'generated' && !body.storyboard) throw new ApiError(422, 'generated posts need a storyboard');
    if (body.kind === 'clip' && !body.mediaUrl) throw new ApiError(422, 'clip posts need a mediaUrl');
    const user = await flashMe();
    const post = await dbPut<StoredPost>('posts', {
      ...body,
      id: newId('post'),
      authorId: user.id,
      author: user,
      views: 0,
      createdAt: new Date().toISOString(),
    });
    return (await hydratePosts([post], user))[0];
  },

  async deletePost(id) {
    await dbDelete('posts', id);
  },

  async toggleLike(id) {
    const user = await flashMe();
    const key = safeKey(user.id, id);
    const existing = await dbGet<StoredReaction>('likes', key);
    if (existing) await dbDelete('likes', key);
    else await dbPut<StoredReaction>('likes', { id: key, userId: user.id, postId: id, createdAt: new Date().toISOString() });
    const count = (await dbList<StoredReaction>('likes')).filter((like) => like.postId === id).length;
    return { active: !existing, count };
  },

  async toggleSave(id) {
    const user = await flashMe();
    const key = safeKey(user.id, id);
    const existing = await dbGet<StoredReaction>('saves', key);
    if (existing) await dbDelete('saves', key);
    else await dbPut<StoredReaction>('saves', { id: key, userId: user.id, postId: id, createdAt: new Date().toISOString() });
    const count = (await dbList<StoredReaction>('saves')).filter((save) => save.postId === id).length;
    return { active: !existing, count };
  },

  async registerView(id) {
    const post = await dbGet<StoredPost>('posts', id);
    if (!post) throw new ApiError(404, 'post not found');
    post.views = (post.views ?? 0) + 1;
    await dbPut('posts', post);
    return { views: post.views };
  },

  async comments(id) {
    return (await dbList<StoredComment>('comments'))
      .filter((comment) => comment.postId === id)
      .sort((a, b) => Date.parse(a.createdAt) - Date.parse(b.createdAt))
      .map(({ id, text, author, createdAt }) => ({ id, text, author, createdAt }));
  },

  async addComment(id, text) {
    const user = await flashMe();
    const comment = await dbPut<StoredComment>('comments', {
      id: newId('cmt'),
      postId: id,
      authorId: user.id,
      author: user,
      text,
      createdAt: new Date().toISOString(),
    });
    return { id: comment.id, text: comment.text, author: comment.author, createdAt: comment.createdAt };
  },

  async deleteComment(id) {
    await dbDelete('comments', id);
  },

  upload(file) {
    requireExternalBackend('video upload');
    return pythonApi.upload(file);
  },

  generate(body) {
    requireExternalBackend('storyboard generation');
    return pythonApi.generate(body);
  },

  job(id) {
    requireExternalBackend('job polling');
    return pythonApi.job(id);
  },
};

export const api: ApiClient = BACKEND_MODE === 'aisites' ? aisitesApi : pythonApi;

// ------------------------------------------------------------------ derived view helpers

/**
 * Split narration into caption lines and allocate scene time by character count.
 *
 * The voice stage would give exact per-sentence durations, but on the browser-reel
 * path narration is spoken by the Web Speech API and no measured audio exists. This
 * is the documented approximation, not an oversight.
 */
export function captionsFor(scene: Scene): string[] {
  return scene.narration
    .split(/(?<=[.!?])\s+/)
    .map((line) => line.trim())
    .filter(Boolean);
}

/** Scene display time. Uses the measured duration when the voice stage has run. */
export function sceneDurationMs(scene: Scene): number {
  if (scene.durationMs) return scene.durationMs;
  const words = scene.narration.trim().split(/\s+/).length;
  return Math.max(2600, Math.round((words / (160 / 60)) * 1000));
}

const AIDOCS_BASE = 'https://aidocs.razorpay.com/app/d';

/**
 * Where to send someone who wants the source document.
 *
 * Derived from `docId` rather than requiring `source.url`, because the contract
 * guarantees a `docId` for every aidoc source but `url` is only populated when the
 * ingest stage happened to resolve one. Requiring `url` meant the feed's "Spec"
 * action silently did not render for any post created outside that path.
 */
export function docHref(storyboard: Storyboard | null): string | null {
  const source = storyboard?.source;
  if (!source || source.kind !== 'aidoc') return null;
  if (source.url) return source.url;
  return source.docId ? `${AIDOCS_BASE}/${source.docId}` : null;
}

/**
 * Public URL for a cached Veo background clip, or null when none is resolved.
 *
 * Keyed on `clipId`, which the visual resolver assigns — NOT on `mood`. Falling back
 * to the mood name guessed at a filename, so every scene fired a request for a clip
 * we had never generated and logged a 404 before showing the gradient. The gradient is
 * the correct state until the Veo library exists; it should not cost a failed request
 * to reach it.
 */
export function brollSrc(scene: Scene): string | null {
  const clipId = scene.broll?.clipId;
  return clipId ? `/broll/${clipId}.mp4` : null;
}

export function initialsOf(user: Pick<ApiUser, 'name' | 'email'>): string {
  const source = user.name || user.email;
  const parts = source.split(/[.\s@_-]+/).filter(Boolean);
  return (parts[0]?.[0] ?? '?').concat(parts[1]?.[0] ?? '').toUpperCase();
}

export function compactCount(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;
  return `${(n / 1_000_000).toFixed(1)}m`;
}
