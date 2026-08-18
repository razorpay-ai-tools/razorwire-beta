import { useMemo, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { accentOptions } from "@/lib/demo-data";
import { generateExplainer } from "@/lib/generator";
import { sampleAidoc, sampleAidocTitle } from "@/lib/sample-doc";
import type { GeneratedExplainer, VideoItem } from "@/lib/types";
import { StoryboardPreview } from "./StoryboardPreview";

type AIDocGeneratorProps = {
  onPublish: (item: VideoItem) => void;
};

export function AIDocGenerator({ onPublish }: AIDocGeneratorProps) {
  const [sourceText, setSourceText] = useState("");
  const [sourceName, setSourceName] = useState("No document selected");
  const [explainer, setExplainer] = useState<GeneratedExplainer | null>(null);
  const [accent, setAccent] = useState(accentOptions[0]);
  const characterCount = useMemo(() => sourceText.trim().length, [sourceText]);

  function handleGenerate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAccent(accentOptions[(Date.now() + 2) % accentOptions.length]);
    setExplainer(generateExplainer(sourceText));
  }

  function loadSample() {
    setSourceText(sampleAidoc);
    setSourceName(sampleAidocTitle);
    setExplainer(null);
  }

  function handleFileUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];

    if (!file) {
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      setSourceText(String(reader.result ?? ""));
      setSourceName(file.name);
      setExplainer(null);
    };
    reader.readAsText(file);
  }

  function publishExplainer() {
    if (!explainer) {
      return;
    }

    onPublish({
      id: `generated-${Date.now()}`,
      title: explainer.title,
      team: "AIDocs Studio",
      author: "Razorwire",
      category: "AI Generated",
      description: explainer.summary,
      tags: explainer.tags,
      duration: explainer.duration,
      createdAt: "Just now",
      kind: "generated",
      accent,
      reactions: { useful: 0, saved: 0, questions: 0 },
      comments: [],
      viewerState: {},
      script: explainer.script,
      sourceText,
      scenes: explainer.scenes,
    });
  }

  return (
    <section
      className="rounded-[2rem] border border-slate-200 bg-white p-6 shadow-xl shadow-slate-950/5"
      id="generate"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-bold uppercase tracking-[0.22em] text-blue-600">
            Generate
          </p>
          <h2 className="mt-2 text-2xl font-black tracking-[-0.04em] text-slate-950">
            Generate from AIDoc
          </h2>
        </div>
        <span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700">
          Reel draft
        </span>
      </div>

      <p className="mt-3 text-sm leading-6 text-slate-600">
        Paste or upload a spec. Razorwire creates a playable reel draft with
        scenes, captions, and narration.
      </p>

      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        <button
          type="button"
          onClick={loadSample}
          className="rounded-2xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm font-bold text-blue-700 transition hover:-translate-y-0.5 hover:bg-blue-100"
        >
          Load sample AIDoc
        </button>
        <label className="cursor-pointer rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-center text-sm font-bold text-slate-700 transition hover:-translate-y-0.5 hover:bg-white">
          Upload .txt / .md / .html
          <input
            type="file"
            accept=".txt,.md,.markdown,.html,text/plain,text/markdown,text/html"
            className="sr-only"
            onChange={handleFileUpload}
          />
        </label>
      </div>

      <div className="mt-4 rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-600">
        <span className="font-bold text-slate-950">Source:</span> {sourceName}
      </div>

      <form className="mt-5 space-y-4" onSubmit={handleGenerate}>
        <textarea
          value={sourceText}
          onChange={(event) => {
            setSourceText(event.target.value);
            setSourceName("Pasted text");
            setExplainer(null);
          }}
          className="input min-h-64 resize-y"
          placeholder="Paste a topic, AIDoc, or tech spec excerpt..."
          required
        />
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
            {characterCount} characters ready
          </p>
          <button
            type="submit"
            className="rounded-2xl bg-blue-600 px-5 py-3 text-sm font-bold text-white transition hover:-translate-y-0.5 hover:bg-blue-700"
          >
            Create reel draft
          </button>
        </div>
      </form>

      {explainer ? (
        <div className="mt-6">
          <StoryboardPreview
            explainer={explainer}
            accent={accent}
            onPublish={publishExplainer}
          />
        </div>
      ) : null}
    </section>
  );
}
