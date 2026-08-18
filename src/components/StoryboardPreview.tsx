import { ReelPlayer } from "./ReelPlayer";
import type { GeneratedExplainer } from "@/lib/types";

type StoryboardPreviewProps = {
  explainer: GeneratedExplainer;
  accent: string;
  onPublish: () => void;
};

export function StoryboardPreview({
  explainer,
  accent,
  onPublish,
}: StoryboardPreviewProps) {
  return (
    <div className="rounded-[1.7rem] border border-blue-100 bg-blue-50/70 p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-blue-700">
            Explainer draft
          </p>
          <h3 className="mt-2 text-2xl font-black tracking-[-0.04em] text-slate-950">
            {explainer.title}
          </h3>
          <p className="mt-2 text-sm leading-6 text-slate-700">
            {explainer.summary}
          </p>
        </div>
        <span className="rounded-full bg-white px-3 py-1 text-xs font-bold text-blue-700 shadow-sm">
          {explainer.duration}
        </span>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {explainer.tags.map((tag) => (
          <span
            key={tag}
            className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-700 shadow-sm"
          >
            #{tag}
          </span>
        ))}
      </div>

      <div className="mt-5">
        <ReelPlayer title={explainer.title} scenes={explainer.scenes} accent={accent} />
      </div>

      <details className="mt-5 rounded-2xl bg-white p-4 shadow-sm">
        <summary className="cursor-pointer text-sm font-bold text-slate-950">
          Scenes and narration script
        </summary>
        <div className="mt-4 grid gap-3">
          {explainer.scenes.map((scene) => (
            <div key={scene.title} className="rounded-2xl bg-slate-50 p-4">
              <div className="flex flex-col gap-2 sm:flex-row sm:justify-between">
                <h4 className="font-bold text-slate-950">{scene.title}</h4>
                <span className="text-xs font-semibold text-slate-500">
                  {scene.caption}
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-600">Visual: {scene.visual}</p>
              <p className="mt-2 text-sm leading-6 text-slate-700">
                {scene.narration}
              </p>
            </div>
          ))}
        </div>
        <div className="mt-4 rounded-2xl bg-slate-950 p-4 text-slate-100">
          <p className="text-sm font-bold text-cyan-300">Narration script</p>
          <p className="mt-3 whitespace-pre-line text-sm leading-6 text-slate-300">
            {explainer.script}
          </p>
        </div>
      </details>

      <button
        type="button"
        onClick={onPublish}
        className="mt-5 w-full rounded-2xl bg-blue-600 px-5 py-4 text-sm font-bold text-white transition hover:-translate-y-0.5 hover:bg-blue-700"
      >
        Post reel to feed
      </button>
    </div>
  );
}
