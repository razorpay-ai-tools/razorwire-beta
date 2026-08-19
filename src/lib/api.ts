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

/** Public URL for a cached Veo background clip, or null when the scene has no footage. */
export function brollSrc(scene: Scene): string | null {
  if (!scene.broll) return null;
  return `/broll/${scene.broll.clipId ?? scene.broll.mood}.mp4`;
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
