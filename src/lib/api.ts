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

const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export interface ApiUser {
  id: string;
  email: string;
  name: string;
  picture: string | null;
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
  durationMs: number | null;
  storyboard: Storyboard | null;
  sourceDocId: string | null;
  views: number;
  createdAt: string;
  author: ApiUser;
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
  kind: PostKind;
  mediaUrl?: string;
  durationMs?: number;
  storyboard?: Storyboard;
  sourceDocId?: string;
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

export const api = {
  me: () => request<ApiUser>('/me'),

  feed: (cursor?: string | null, limit = 10) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (cursor) params.set('cursor', cursor);
    return request<FeedPage>(`/feed?${params}`);
  },

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
    return request<{ mediaUrl: string }>('/uploads', { method: 'POST', body: form });
  },

  generate: (body: GenerateRequest) =>
    request<Job>('/generate', { method: 'POST', body: JSON.stringify(body) }),

  job: (id: string) => request<Job>(`/jobs/${id}`),
};

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
