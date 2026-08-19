'use client';

/**
 * Post a team clip. Roughly half the feed is uploaded video with no scenes, no
 * citations and no captions — a clip is a first-class post, not a degraded reel.
 *
 * The extension allowlist mirrors `POST /uploads` in `backend/app/main.py`, which
 * answers 415 for anything else. Checking it here saves a pointless megabyte upload;
 * the server check is still the one that counts.
 */

import { useRef, useState } from 'react';
import type { ChangeEvent, DragEvent, FormEvent } from 'react';
import { api, ApiError } from '@/lib/api';
import { ChannelSelect } from '@/components/channels/ChannelSelect';
import { Icon } from '@/components/ui';

/** Same set the backend accepts. */
const ALLOWED_EXTENSIONS = ['.mp4', '.webm', '.mov', '.m4v'] as const;

/** ponytail: client-side only — the binary is proxied through the app onto local disk. */
const MAX_BYTES = 200 * 1024 * 1024;

const CATEGORIES = ['Product', 'Architecture', 'Culture', 'Onboarding', 'Incident'] as const;

type Phase = 'idle' | 'uploading' | 'publishing';

const PHASE_LABEL: Record<Exclude<Phase, 'idle'>, string> = {
  uploading: 'Uploading the clip…',
  publishing: 'Adding it to the feed…',
};

function formatSize(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return mb < 1 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${mb.toFixed(1)} MB`;
}

function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot === -1 ? '' : name.slice(dot).toLowerCase();
}

/** Returns a message when the file is not postable, or null when it is. */
export function checkClip(file: File): string | null {
  const extension = extensionOf(file.name);
  if (!(ALLOWED_EXTENSIONS as readonly string[]).includes(extension)) {
    return `${extension || 'That file'} is not a supported video format. Use ${ALLOWED_EXTENSIONS.join(', ')}.`;
  }
  if (file.size > MAX_BYTES) {
    return `That clip is ${formatSize(file.size)}. The limit is ${formatSize(MAX_BYTES)} — trim or compress it first.`;
  }
  return null;
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    return err.status === 415
      ? `The server rejected the file: ${err.message}. Allowed formats are ${ALLOWED_EXTENSIONS.join(', ')}.`
      : err.message;
  }
  return err instanceof Error ? err.message : 'The upload failed. Try again.';
}

export function UploadClipForm({ onPublished }: { onPublished: (postId: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [team, setTeam] = useState('');
  const [category, setCategory] = useState<string>(CATEGORIES[0]);
  const [channelId, setChannelId] = useState('');
  const [tags, setTags] = useState('');

  const [dragging, setDragging] = useState(false);
  const [phase, setPhase] = useState<Phase>('idle');
  const [fileError, setFileError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const busy = phase !== 'idle';

  function accept(candidate: File | undefined) {
    if (!candidate) return;
    const problem = checkClip(candidate);
    setFileError(problem);
    setError(null);
    setFile(problem ? null : candidate);
    if (!problem && !title.trim()) {
      setTitle(candidate.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' '));
    }
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (busy) return;
    accept(event.dataTransfer.files[0]);
  }

  function handlePick(event: ChangeEvent<HTMLInputElement>) {
    accept(event.target.files?.[0]);
  }

  function clearFile() {
    setFile(null);
    setFileError(null);
    if (inputRef.current) inputRef.current.value = '';
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;

    if (!file) {
      setFileError('Choose a clip to post.');
      return;
    }
    const problem = checkClip(file);
    if (problem) {
      setFileError(problem);
      return;
    }
    if (!title.trim()) {
      setError('Give the clip a title so people know what they are opening.');
      return;
    }

    setError(null);
    setPhase('uploading');
    try {
      const { mediaUrl } = await api.upload(file);
      setPhase('publishing');
      const post = await api.createPost({
        kind: 'clip',
        mediaUrl,
        title: title.trim(),
        team: team.trim(),
        category,
        ...(channelId ? { channelId } : {}),
        tags: tags
          .split(',')
          .map((tag) => tag.trim())
          .filter(Boolean),
      });
      onPublished(post.id);
    } catch (err: unknown) {
      setError(describeError(err));
    } finally {
      setPhase('idle');
    }
  }

  return (
    <form onSubmit={handleSubmit} className="panel space-y-5 p-5 sm:p-6" noValidate>
      <div>
        <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-brand-300">
          Upload
        </p>
        <h2 className="mt-1.5 text-lg font-semibold tracking-tight text-neutral-50">
          Post a team clip
        </h2>
      </div>

      {/* Drop target. The label + hidden input is the keyboard and screen-reader path;
          drag and drop is the shortcut on top of it. */}
      <div
        onDragOver={(event) => {
          event.preventDefault();
          if (!busy) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={`rounded-2xl border border-dashed p-5 text-center transition ${
          dragging ? 'border-brand-400 bg-brand-500/10' : 'border-neutral-700 bg-neutral-900/40'
        }`}
      >
        <Icon
          name="upload"
          label={null}
          className={`mx-auto size-6 ${dragging ? 'text-brand-300' : 'text-neutral-500'}`}
        />
        <p className="mt-2 text-sm text-neutral-300">
          Drop a video here, or{' '}
          <label
            htmlFor="clip-file"
            className="cursor-pointer font-semibold text-brand-300 underline decoration-brand-500/40 underline-offset-4"
          >
            choose a file
          </label>
        </p>
        <input
          ref={inputRef}
          id="clip-file"
          name="clip-file"
          type="file"
          accept={ALLOWED_EXTENSIONS.join(',')}
          className="sr-only"
          onChange={handlePick}
          disabled={busy}
          aria-describedby="clip-file-hint"
          aria-invalid={fileError ? true : undefined}
        />
        <p id="clip-file-hint" className="mt-1.5 text-[11px] text-neutral-500">
          {ALLOWED_EXTENSIONS.join(' · ')} — up to {formatSize(MAX_BYTES)}
        </p>

        {file ? (
          <p className="mt-3 inline-flex max-w-full items-center gap-2 rounded-full border border-neutral-700 bg-neutral-950/80 py-1 pl-3 pr-1.5 text-xs">
            <Icon name="play" label={null} className="size-3 shrink-0 text-brand-300" filled />
            <span className="truncate font-medium text-neutral-200">{file.name}</span>
            <span className="shrink-0 font-mono text-[10px] text-neutral-500">
              {formatSize(file.size)}
            </span>
            <button
              type="button"
              onClick={clearFile}
              disabled={busy}
              className="shrink-0 rounded-full p-1 text-neutral-400 transition hover:bg-neutral-800 hover:text-neutral-100 disabled:opacity-50"
            >
              <Icon name="close" label={`Remove ${file.name}`} className="size-3" />
            </button>
          </p>
        ) : null}
      </div>

      {fileError ? (
        <p
          role="alert"
          className="flex items-start gap-2 rounded-xl border border-danger/40 bg-danger/10 p-3 text-sm text-neutral-100"
        >
          <Icon name="alert" label="Error" className="mt-0.5 size-4 shrink-0 text-danger" />
          <span>{fileError}</span>
        </p>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <label htmlFor="clip-title" className="block text-xs font-semibold text-neutral-300">
            Title
          </label>
          <input
            id="clip-title"
            name="clip-title"
            type="text"
            className="input mt-1.5"
            placeholder="How we run design crit"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            disabled={busy}
          />
        </div>

        <div>
          <label htmlFor="clip-team" className="block text-xs font-semibold text-neutral-300">
            Team
          </label>
          <input
            id="clip-team"
            name="clip-team"
            type="text"
            className="input mt-1.5"
            placeholder="design-systems"
            value={team}
            onChange={(event) => setTeam(event.target.value)}
            disabled={busy}
          />
        </div>

        <div>
          <label htmlFor="clip-category" className="block text-xs font-semibold text-neutral-300">
            Category
          </label>
          <select
            id="clip-category"
            name="clip-category"
            className="input mt-1.5"
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            disabled={busy}
          >
            {CATEGORIES.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>

        <div className="sm:col-span-2">
          <ChannelSelect
            id="clip-channel"
            value={channelId}
            onChange={setChannelId}
            disabled={busy}
          />
        </div>

        <div className="sm:col-span-2">
          <label htmlFor="clip-tags" className="block text-xs font-semibold text-neutral-300">
            Tags
          </label>
          <input
            id="clip-tags"
            name="clip-tags"
            type="text"
            className="input mt-1.5"
            placeholder="design, process, crit"
            value={tags}
            onChange={(event) => setTags(event.target.value)}
            disabled={busy}
            aria-describedby="clip-tags-hint"
          />
          <p id="clip-tags-hint" className="mt-1.5 text-[11px] text-neutral-500">
            Comma separated.
          </p>
        </div>
      </div>

      {error ? (
        <p
          role="alert"
          className="flex items-start gap-2 rounded-xl border border-danger/40 bg-danger/10 p-3 text-sm text-neutral-100"
        >
          <Icon name="alert" label="Error" className="mt-0.5 size-4 shrink-0 text-danger" />
          <span>{error}</span>
        </p>
      ) : null}

      {/*
        Indeterminate, not fake. `api.upload` uses fetch, which reports no upload
        progress, and re-implementing the request over XHR to get a percentage would mean
        duplicating the base URL and error handling of the typed client.
      */}
      {busy ? (
        <div role="status" className="space-y-2">
          <p className="flex items-center gap-2 text-sm font-medium text-neutral-200">
            <Icon name="upload" label={null} className="size-4 shrink-0 text-brand-300" />
            {PHASE_LABEL[phase]}
          </p>
          <span className="block h-1 overflow-hidden rounded-full bg-neutral-800">
            <span className="block h-full w-1/3 animate-pulse rounded-full bg-brand-500" />
          </span>
          <p className="text-[11px] text-neutral-500">
            {phase === 'uploading'
              ? 'Large clips take a while — keep this tab open.'
              : 'Almost there.'}
          </p>
        </div>
      ) : null}

      <button
        type="submit"
        disabled={busy}
        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-brand-500 px-4 py-3 text-sm font-semibold text-white transition hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto"
      >
        <Icon name="send" label={null} className="size-4" />
        {busy ? 'Posting…' : 'Post clip'}
      </button>
    </form>
  );
}
