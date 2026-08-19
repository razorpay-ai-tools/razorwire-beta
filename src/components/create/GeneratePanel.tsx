'use client';

/**
 * Generate an explainer from a document.
 *
 * The source is **aidocs** — Razorpay's internal doc platform and the only ingestion
 * source this product has. The previous design pass offered "Notion, Confluence or
 * GitHub", none of which exist here; the aidocs integration is the differentiator.
 *
 * A plain-text topic is the secondary path, deliberately smaller: it produces a
 * storyboard with no `cite` anywhere, which is exactly what the trust feature exists to
 * avoid. There is no "Target Audience" field — the API has no such parameter.
 */

import { useState } from 'react';
import type { FormEvent } from 'react';
import { api, type GenerateRequest, type Job } from '@/lib/api';
import { sampleAidoc, sampleAidocTitle } from '@/lib/sample-doc';
import { ChannelSelect } from '@/components/channels/ChannelSelect';
import { Icon } from '@/components/ui';
import { PipelineStepper } from './PipelineStepper';

/** The backend's floor for a TOPIC. The aidoc path needs no text at all — it fetches. */
const MIN_INPUT = 10;

/** aidocs ids are `doc_` + alphanumerics, e.g. `doc_r523noskel555f7f`. Stopping at the
 *  first non-alphanumeric keeps a trailing URL slug out of the id. */
const DOC_ID_PATTERN = /\bdoc_[A-Za-z0-9]+/;

/** Pull the doc id out of a pasted aidocs URL, or accept a bare `doc_...` id. */
export function parseDocId(raw: string): string | null {
  return raw.trim().match(DOC_ID_PATTERN)?.[0] ?? null;
}

function messageOf(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

type SourceKind = GenerateRequest['kind'];

export function GeneratePanel({ onPublished }: { onPublished: (postId: string) => void }) {
  const [kind, setKind] = useState<SourceKind>('aidoc');
  const [docRef, setDocRef] = useState('');
  const [docTitle, setDocTitle] = useState('');
  const [docText, setDocText] = useState('');
  const [topic, setTopic] = useState('');
  // Chosen before generation, applied when the finished storyboard becomes a post.
  const [channelId, setChannelId] = useState('');

  const [request, setRequest] = useState<GenerateRequest | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const docId = parseDocId(docRef);

  function buildRequest(): GenerateRequest | string {
    if (kind === 'topic') {
      const input = topic.trim();
      if (input.length < MIN_INPUT) {
        return 'Describe the topic in a sentence or more — at least 10 characters.';
      }
      return { kind: 'topic', input };
    }

    if (!docId) {
      return 'No doc id found. Paste an aidocs link like https://aidocs.razorpay.com/app/d/doc_… or the doc_… id on its own.';
    }
    const input = docText.trim();
    if (input.length < MIN_INPUT) {
      return 'Production cannot read private aidocs directly yet. Paste the document body too, keeping headings for citation chips.';
    }
    const trimmedRef = docRef.trim();
    const trimmedTitle = docTitle.trim();
    return {
      kind: 'aidoc',
      input,
      docId,
      ...(trimmedTitle ? { docTitle: trimmedTitle } : {}),
      ...(trimmedRef.startsWith('http') ? { docUrl: trimmedRef } : {}),
    };
  }

  async function start(body: GenerateRequest) {
    setSubmitting(true);
    setError(null);
    try {
      const job = await api.generate(body);
      setRequest(body);
      setJobId(job.id);
    } catch (err: unknown) {
      setError(messageOf(err, 'Could not queue the generation.'));
    } finally {
      setSubmitting(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const built = buildRequest();
    if (typeof built === 'string') {
      setError(built);
      return;
    }
    void start(built);
  }

  function handleDone(job: Job) {
    if (job.state === 'published' && job.postId) onPublished(job.postId);
  }

  function handleRetry() {
    if (request) void start(request);
  }

  function loadSample() {
    setDocText(sampleAidoc);
    setDocTitle(sampleAidocTitle);
    setError(null);
  }

  if (jobId) {
    return (
      <div className="space-y-3">
        <PipelineStepper
          key={jobId}
          jobId={jobId}
          onDone={handleDone}
          onRetry={handleRetry}
          {...(channelId ? { channelId } : {})}
        />
        <button
          type="button"
          onClick={() => {
            setJobId(null);
            setRequest(null);
          }}
          className="text-xs font-semibold text-neutral-400 underline decoration-neutral-700 underline-offset-4 transition hover:text-neutral-100"
        >
          Edit the source and start over
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="panel space-y-5 p-5 sm:p-6" noValidate>
      <div>
        <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-brand-300">
          Generate
        </p>
        <h2 className="mt-1.5 text-lg font-semibold tracking-tight text-neutral-50">
          Turn an aidoc into a 60-second explainer
        </h2>
        <p className="mt-1.5 text-xs leading-relaxed text-neutral-400">
          Every factual scene comes back with the section it came from, so anyone watching can
          check a claim against the spec.
        </p>
      </div>

      <fieldset className="space-y-2">
        <legend className="text-xs font-semibold text-neutral-300">Source</legend>
        <div className="flex flex-col gap-2 sm:flex-row">
          <SourceOption
            value="aidoc"
            checked={kind === 'aidoc'}
            onSelect={setKind}
            label="aidocs document"
            hint="Cited, checkable"
          />
          <SourceOption
            value="topic"
            checked={kind === 'topic'}
            onSelect={setKind}
            label="Topic"
            hint="No source, no citations"
          />
        </div>
      </fieldset>

      {kind === 'aidoc' ? (
        <div className="space-y-4">
          <div>
            <label htmlFor="doc-ref" className="block text-xs font-semibold text-neutral-300">
              aidocs link or doc id
            </label>
            <input
              id="doc-ref"
              name="doc-ref"
              type="text"
              className="input mt-1.5 font-mono text-xs"
              placeholder="https://aidocs.razorpay.com/app/d/doc_r523noskel555f7f"
              value={docRef}
              onChange={(event) => setDocRef(event.target.value)}
              aria-describedby="doc-ref-hint"
              autoComplete="off"
              spellCheck={false}
            />
            <p id="doc-ref-hint" className="mt-1.5 flex items-center gap-1.5 text-[11px] text-neutral-500">
              {docId ? (
                <>
                  <Icon name="check" label={null} className="size-3.5 shrink-0 text-success" />
                  <span>
                    Reading <span className="font-mono text-neutral-300">{docId}</span>
                  </span>
                </>
              ) : (
                <span>Paste the full URL or just the doc_… id.</span>
              )}
            </p>
          </div>

          <div>
            <label htmlFor="doc-title" className="block text-xs font-semibold text-neutral-300">
              Document title <span className="font-normal text-neutral-500">(optional)</span>
            </label>
            <input
              id="doc-title"
              name="doc-title"
              type="text"
              className="input mt-1.5"
              placeholder="UPI One-Time Mandates — rearchitecture"
              value={docTitle}
              onChange={(event) => setDocTitle(event.target.value)}
            />
          </div>

          <div>
            <div className="flex items-baseline justify-between gap-3">
              <label htmlFor="doc-text" className="block text-xs font-semibold text-neutral-300">
                Document body <span className="font-normal text-neutral-500">(required on production)</span>
              </label>
              <button
                type="button"
                onClick={loadSample}
                className="text-[11px] font-semibold text-brand-300 underline decoration-brand-500/40 underline-offset-4 transition hover:text-brand-200"
              >
                Load sample doc
              </button>
            </div>
            <textarea
              id="doc-text"
              name="doc-text"
              className="input mt-1.5 min-h-48 resize-y leading-relaxed"
              placeholder="Paste the aidoc contents here. Keep headings so citation chips point to real sections."
              value={docText}
              onChange={(event) => setDocText(event.target.value)}
              aria-describedby="doc-text-hint"
            />
            <p id="doc-text-hint" className="mt-1.5 text-[11px] text-neutral-500">
              {docText.trim().length
                ? `${docText.trim().length} characters. Keep the headings in — they are what the citation chips point at.`
                : 'Railway cannot run the local aidocs CLI, so production needs the body pasted here.'}
            </p>
          </div>
        </div>
      ) : (
        <div>
          <label htmlFor="topic" className="block text-xs font-semibold text-neutral-300">
            Topic
          </label>
          <textarea
            id="topic"
            name="topic"
            className="input mt-1.5 min-h-28 resize-y leading-relaxed"
            placeholder="How UPI autopay mandates are debited"
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            aria-describedby="topic-hint"
          />
          <p id="topic-hint" className="mt-1.5 flex items-start gap-1.5 text-[11px] leading-relaxed text-neutral-500">
            <Icon name="alert" label={null} className="mt-px size-3.5 shrink-0 text-warning" />
            <span>
              Without a document there is nothing to cite, so this reel carries no citation chips
              and nobody can check it. Use an aidoc where one exists.
            </span>
          </p>
        </div>
      )}

      <ChannelSelect
        id="generate-channel"
        value={channelId}
        onChange={setChannelId}
        disabled={submitting}
      />

      {error ? (
        <p
          role="alert"
          className="flex items-start gap-2 rounded-xl border border-danger/40 bg-danger/10 p-3 text-sm text-neutral-100"
        >
          <Icon name="alert" label="Error" className="mt-0.5 size-4 shrink-0 text-danger" />
          <span>{error}</span>
        </p>
      ) : null}

      <button
        type="submit"
        disabled={submitting}
        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-brand-500 px-4 py-3 text-sm font-semibold text-white transition hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto"
      >
        <Icon name="sparkle" label={null} className="size-4" />
        {submitting ? 'Queueing…' : 'Generate explainer'}
      </button>
    </form>
  );
}

/** Radio, styled as a segment. Native radios already do arrow-key navigation. */
function SourceOption({
  value,
  checked,
  onSelect,
  label,
  hint,
}: {
  value: SourceKind;
  checked: boolean;
  onSelect: (kind: SourceKind) => void;
  label: string;
  hint: string;
}) {
  const primary = value === 'aidoc';
  return (
    <label
      className={`flex flex-1 cursor-pointer items-start gap-2.5 rounded-xl border px-3 py-2.5 transition ${
        checked
          ? 'border-brand-500 bg-brand-500/10'
          : 'border-neutral-800 bg-neutral-900/60 hover:border-neutral-700'
      } ${primary ? '' : 'sm:max-w-52'}`}
    >
      <input
        type="radio"
        name="source-kind"
        value={value}
        checked={checked}
        onChange={() => onSelect(value)}
        className="mt-0.5 size-4 shrink-0 accent-brand-500"
      />
      <span className="min-w-0">
        <span
          className={`block font-semibold ${primary ? 'text-sm text-neutral-50' : 'text-xs text-neutral-200'}`}
        >
          {label}
        </span>
        <span className="mt-0.5 block text-[11px] text-neutral-400">{hint}</span>
      </span>
    </label>
  );
}
