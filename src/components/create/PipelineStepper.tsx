'use client';

/**
 * The live wait, ~10 seconds of it.
 *
 * Two things the previous design pass got wrong, both fixed here:
 *
 *  1. `voicing` and `rendering` only run on the MP4 export path. The default
 *     browser-reel path is `queued -> scripting -> published`. So those two steps are
 *     rendered only once the job has actually been in them; two permanently dead rows
 *     read as a broken stepper, not as an unused branch.
 *  2. `failed` is a real outcome. The script stage retries three times, feeding
 *     validation errors back to the model, and gives up if the contract still is not
 *     satisfied. That is designed here, not omitted.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type Job, type JobState } from '@/lib/api';
import { MAX_MERMAID_NODES } from '@/lib/storyboard.types';
import { Icon } from '@/components/ui';

const POLL_MS = 900;

type StepKey = Exclude<JobState, 'failed'>;

/** Pipeline order. `failed` is not a step; it is what happens to the step in flight. */
const ORDER: readonly StepKey[] = ['queued', 'scripting', 'voicing', 'rendering', 'published'];

/** Always drawn. Everything else appears only once the job has entered it. */
const ALWAYS: readonly StepKey[] = ['queued', 'scripting', 'published'];

const COPY: Record<StepKey, { title: string; subtitle: string }> = {
  queued: {
    title: 'Queued',
    subtitle: 'Job accepted. Waiting for a pipeline slot.',
  },
  scripting: {
    title: 'Scripting',
    subtitle: 'Claude is writing the scenes and tying every claim to a section of the doc.',
  },
  voicing: {
    title: 'Voicing',
    subtitle: 'Narration going to text-to-speech, which gives each scene a measured length.',
  },
  rendering: {
    title: 'Rendering',
    subtitle: 'Compositing scenes, captions and b-roll into an MP4.',
  },
  published: {
    title: 'Published',
    subtitle: 'Storyboard passed validation. Adding it to the feed.',
  },
};

type StepStatus = 'done' | 'active' | 'pending' | 'failed';

const STATUS_WORD: Record<StepStatus, string> = {
  done: 'Done',
  active: 'In progress',
  pending: 'Waiting',
  failed: 'Failed',
};

function isTerminal(state: JobState): boolean {
  return state === 'published' || state === 'failed';
}

function messageOf(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

/** The backend joins validation errors with "; ". Split them back into readable lines. */
function errorLines(error: string): string[] {
  return error
    .split(/;\s+/)
    .map((line) => line.trim())
    .filter(Boolean);
}

/**
 * When the failure came from a contract guardrail rather than a crash, say so —
 * a rejected storyboard is the anti-hallucination machinery doing its job.
 */
function guardrailNote(error: string): string | null {
  const text = error.toLowerCase();
  if (text.includes('mermaid') || text.includes('node')) {
    return `A diagram went over the ${MAX_MERMAID_NODES}-node cap, which is the most that stays legible in a phone-sized frame.`;
  }
  if (text.includes('cite') || text.includes('citation')) {
    return 'A scene stated a fact without citing the section it came from, so it could not be checked against the source.';
  }
  return null;
}

interface PipelineStepperProps {
  jobId: string;
  /**
   * Fires once, on the terminal state. On `published` the post has already been
   * created and its id is carried on `job.postId`.
   */
  onDone: (job: Job) => void;
  /** Rendered as Retry on failure. Only the caller knows the request to re-send. */
  onRetry?: () => void;
}

export function PipelineStepper({ jobId, onDone, onRetry }: PipelineStepperProps) {
  const [job, setJob] = useState<Job | null>(null);
  const [seen, setSeen] = useState<readonly StepKey[]>(['queued']);
  const [pollError, setPollError] = useState<string | null>(null);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);

  const onDoneRef = useRef(onDone);
  const postedRef = useRef(false);

  // A new job id means everything on screen belongs to the previous run. Reset during
  // render rather than in an effect, which would paint the old job's steps once first.
  const [trackedId, setTrackedId] = useState(jobId);
  if (trackedId !== jobId) {
    setTrackedId(jobId);
    setJob(null);
    setSeen(['queued']);
    setPollError(null);
    setPublishError(null);
    setPublishing(false);
  }

  useEffect(() => {
    onDoneRef.current = onDone;
  }, [onDone]);

  /** Turn the finished job into a feed post, then hand the post id back up. */
  const publish = useCallback(async (finished: Job) => {
    if (postedRef.current) return;
    const storyboard = finished.storyboard;
    if (!storyboard) {
      setPublishError('The job finished but returned no storyboard, so there is nothing to publish.');
      return;
    }

    postedRef.current = true;
    setPublishing(true);
    setPublishError(null);
    try {
      const post = await api.createPost({
        kind: 'generated',
        storyboard,
        title: storyboard.meta.title,
        tags: storyboard.meta.tags,
        ...(storyboard.source.docId ? { sourceDocId: storyboard.source.docId } : {}),
      });
      onDoneRef.current({ ...finished, postId: post.id });
    } catch (err: unknown) {
      postedRef.current = false;
      setPublishError(messageOf(err, 'Could not add the reel to the feed.'));
    } finally {
      setPublishing(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    postedRef.current = false;

    const interval = window.setInterval(() => void tick(), POLL_MS);

    async function tick(): Promise<void> {
      try {
        const next = await api.job(jobId);
        if (cancelled) return;

        setJob(next);
        if (next.state !== 'failed') {
          const reached: StepKey = next.state;
          setSeen((prev) => (prev.includes(reached) ? prev : [...prev, reached]));
        }

        if (!isTerminal(next.state)) return;

        window.clearInterval(interval);
        if (next.state === 'published') await publish(next);
        else onDoneRef.current(next);
      } catch (err: unknown) {
        if (cancelled) return;
        window.clearInterval(interval);
        setPollError(messageOf(err, 'Lost contact with the pipeline.'));
      }
    }

    void tick();
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [jobId, publish]);

  const failed = job?.state === 'failed';
  /** On failure the marker sits on the step that was in flight, which is the last one seen. */
  const activeKey: StepKey = job && job.state !== 'failed' ? job.state : (seen[seen.length - 1] ?? 'queued');
  const activeIndex = ORDER.indexOf(activeKey);
  const settled = activeKey === 'published' && !publishing && !publishError;
  /** Nothing is in flight any more: the job failed, or the publish did. */
  const stalled = failed || publishError !== null;

  const steps = ORDER.filter((key) => ALWAYS.includes(key) || seen.includes(key));
  const exportPath = seen.includes('voicing') || seen.includes('rendering');

  function statusOf(key: StepKey): StepStatus {
    const index = ORDER.indexOf(key);
    if (index < activeIndex) return 'done';
    if (index > activeIndex) return 'pending';
    if (stalled) return 'failed';
    return settled ? 'done' : 'active';
  }

  const progress = stalled ? (job?.progress ?? 0) : settled ? 100 : (job?.progress ?? 5);

  return (
    <section className="panel p-5 sm:p-6" aria-labelledby="pipeline-heading">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-brand-300">
            {stalled ? 'Generation stopped' : 'Building your explainer'}
          </p>
          <h2 id="pipeline-heading" className="mt-1.5 text-lg font-semibold tracking-tight text-neutral-50">
            {failed
              ? 'The pipeline rejected this draft'
              : publishError
                ? 'Could not add it to the feed'
                : settled
                  ? 'Ready'
                  : 'Working through the pipeline'}
          </h2>
        </div>
        <span className="shrink-0 font-mono text-xs text-neutral-500">{progress}%</span>
      </div>

      <div
        className="mt-4 h-1 overflow-hidden rounded-full bg-neutral-800"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress}
        aria-label="Generation progress"
      >
        <div
          className={`h-full rounded-full transition-[width] duration-500 ${stalled ? 'bg-danger' : 'bg-brand-500'}`}
          style={{ width: `${Math.max(progress, 4)}%` }}
        />
      </div>

      {/* One announcement per state change, rather than a chattering list. */}
      <p aria-live="polite" className="sr-only">
        {stalled
          ? `Stopped during ${COPY[activeKey].title}.`
          : `${COPY[activeKey].title}. ${COPY[activeKey].subtitle}`}
      </p>

      <ol className="mt-5 space-y-1">
        {steps.map((key, position) => {
          const status = statusOf(key);
          return (
            <li key={key} className="flex gap-3.5 rounded-xl px-1 py-2">
              <span className="relative flex flex-col items-center">
                <StepMarker status={status} position={position + 1} />
                {position < steps.length - 1 ? (
                  <span
                    aria-hidden="true"
                    className={`mt-1 w-0.5 flex-1 rounded-full ${
                      status === 'done' ? 'bg-brand-500/60' : 'bg-neutral-800'
                    }`}
                  />
                ) : null}
              </span>

              <div className="min-w-0 flex-1 pb-1">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <p
                    className={`text-sm font-semibold ${
                      status === 'pending' ? 'text-neutral-500' : 'text-neutral-100'
                    }`}
                  >
                    {COPY[key].title}
                  </p>
                  <span
                    className={`font-mono text-[10px] uppercase tracking-[0.14em] ${
                      status === 'failed'
                        ? 'text-danger'
                        : status === 'done'
                          ? 'text-success'
                          : status === 'active'
                            ? 'text-brand-300'
                            : 'text-neutral-600'
                    }`}
                  >
                    {STATUS_WORD[status]}
                  </span>
                </div>
                <p
                  className={`mt-0.5 text-xs leading-relaxed ${
                    status === 'pending' ? 'text-neutral-600' : 'text-neutral-400'
                  }`}
                >
                  {key === 'published' && settled
                    ? 'Storyboard passed validation. It is in the feed.'
                    : COPY[key].subtitle}
                </p>
              </div>
            </li>
          );
        })}
      </ol>

      {!exportPath && !stalled ? (
        <p className="mt-2 border-t border-neutral-800 pt-3 text-[11px] leading-relaxed text-neutral-500">
          Voicing and rendering are not in this run. They belong to the MP4 export path — the
          browser reel narrates live and takes its scene timing from the narration.
        </p>
      ) : null}

      {failed && job?.error ? <FailureReport error={job.error} onRetry={onRetry} /> : null}

      {publishError ? (
        <div role="alert" className="mt-4 rounded-xl border border-danger/40 bg-danger/10 p-3">
          <p className="flex items-start gap-2 text-sm text-neutral-100">
            <Icon name="alert" label="Error" className="mt-0.5 size-4 shrink-0 text-danger" />
            <span>{publishError}</span>
          </p>
          {/* The storyboard already exists, so this retries the post, not the generation. */}
          {job && job.storyboard ? (
            <button
              type="button"
              onClick={() => void publish(job)}
              disabled={publishing}
              className="mt-2.5 rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-xs font-semibold text-neutral-100 transition hover:border-brand-500/50 disabled:opacity-60"
            >
              Try publishing again
            </button>
          ) : null}
        </div>
      ) : null}

      {pollError ? (
        <p
          role="alert"
          className="mt-4 flex items-start gap-2 rounded-xl border border-danger/40 bg-danger/10 p-3 text-sm text-neutral-100"
        >
          <Icon name="alert" label="Error" className="mt-0.5 size-4 shrink-0 text-danger" />
          <span>
            {pollError} The job may still be running — reload to pick it back up.
          </span>
        </p>
      ) : null}
    </section>
  );
}

function StepMarker({ status, position }: { status: StepStatus; position: number }) {
  const base = 'flex size-7 shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold';

  if (status === 'done') {
    return (
      <span className={`${base} border-brand-500 bg-brand-500 text-white`}>
        <Icon name="check" label={null} className="size-4" />
      </span>
    );
  }
  if (status === 'failed') {
    return (
      <span className={`${base} border-danger bg-danger/20 text-danger`}>
        <Icon name="alert" label={null} className="size-4" />
      </span>
    );
  }
  if (status === 'active') {
    return (
      <span
        className={`${base} animate-pulse-ring border-brand-400 bg-brand-500/20 font-mono text-brand-200`}
      >
        {position}
      </span>
    );
  }
  return (
    <span className={`${base} border-neutral-800 bg-neutral-900 font-mono text-neutral-600`}>
      {position}
    </span>
  );
}

function FailureReport({ error, onRetry }: { error: string; onRetry?: () => void }) {
  const note = guardrailNote(error);
  const lines = errorLines(error);

  return (
    <div
      role="alert"
      className="mt-4 rounded-2xl border border-danger/40 bg-danger/10 p-4"
    >
      <div className="flex items-start gap-2.5">
        <Icon name="alert" label="Failed" className="mt-0.5 size-4 shrink-0 text-danger" />
        <div className="min-w-0">
          <p className="text-sm font-semibold text-neutral-50">
            {note ? 'A guardrail rejected the output' : 'Generation failed'}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-neutral-300">
            {note
              ? `${note} The pipeline retried three times, handing the validation errors back to the model each time, and it still could not satisfy the contract — so it published nothing rather than something unverifiable.`
              : 'The script stage could not finish. Nothing was published.'}
          </p>
        </div>
      </div>

      <div className="mt-3 rounded-xl border border-neutral-800 bg-neutral-950/70 p-3">
        <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-neutral-500">
          What the validator said
        </p>
        <ul className="mt-1.5 space-y-1">
          {lines.map((line) => (
            <li key={line} className="flex gap-2 font-mono text-[11px] leading-relaxed text-neutral-300">
              <span aria-hidden="true" className="text-neutral-600">
                &gt;
              </span>
              <span className="min-w-0 break-words">{line}</span>
            </li>
          ))}
        </ul>
      </div>

      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 inline-flex items-center gap-2 rounded-xl bg-brand-500 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-600"
        >
          <Icon name="sparkle" label={null} className="size-4" />
          Retry generation
        </button>
      ) : null}
    </div>
  );
}
