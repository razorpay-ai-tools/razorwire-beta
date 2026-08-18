import { useEffect, useMemo, useState } from "react";
import type { StoryboardScene } from "@/lib/types";

type ReelPlayerProps = {
  title: string;
  scenes: StoryboardScene[];
  accent: string;
  compact?: boolean;
};

export function ReelPlayer({ title, scenes, accent, compact = false }: ReelPlayerProps) {
  const [currentSceneIndex, setCurrentSceneIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const currentScene = scenes[currentSceneIndex];
  const progress = useMemo(
    () => ((currentSceneIndex + 1) / Math.max(scenes.length, 1)) * 100,
    [currentSceneIndex, scenes.length]
  );

  useEffect(() => {
    if (!isPlaying || scenes.length <= 1) {
      return;
    }

    const timer = window.setInterval(() => {
      setCurrentSceneIndex((current) => {
        if (current >= scenes.length - 1) {
          setIsPlaying(false);
          return current;
        }

        return current + 1;
      });
    }, 4200);

    return () => window.clearInterval(timer);
  }, [isPlaying, scenes.length]);

  useEffect(() => {
    return () => window.speechSynthesis?.cancel();
  }, []);

  function goToPreviousScene() {
    setCurrentSceneIndex((current) => Math.max(0, current - 1));
  }

  function goToNextScene() {
    setCurrentSceneIndex((current) => Math.min(scenes.length - 1, current + 1));
  }

  function speakScene() {
    if (!currentScene || !("speechSynthesis" in window)) {
      return;
    }

    window.speechSynthesis.cancel();

    if (isSpeaking) {
      setIsSpeaking(false);
      return;
    }

    const utterance = new SpeechSynthesisUtterance(currentScene.narration);
    utterance.rate = 1;
    utterance.pitch = 1;
    utterance.onend = () => setIsSpeaking(false);
    utterance.onerror = () => setIsSpeaking(false);
    setIsSpeaking(true);
    window.speechSynthesis.speak(utterance);
  }

  if (!currentScene) {
    return null;
  }

  return (
    <div className="overflow-hidden rounded-[1.7rem] border border-slate-200 bg-white shadow-sm">
      <div
        className={`relative aspect-[9/14] min-h-[360px] overflow-hidden bg-gradient-to-br text-white ${accent}`}
      >
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(255,255,255,0.36),transparent_28%),linear-gradient(180deg,rgba(15,23,42,0.05)_0%,rgba(15,23,42,0.82)_100%)]" />
        <div className="absolute inset-x-4 top-4 flex gap-1">
          {scenes.map((scene, index) => (
            <button
              key={scene.title}
              type="button"
              onClick={() => setCurrentSceneIndex(index)}
              className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/30"
              aria-label={`Jump to scene ${index + 1}`}
            >
              <span
                className={`block h-full rounded-full bg-white transition-all ${
                  index < currentSceneIndex
                    ? "w-full"
                    : index === currentSceneIndex
                      ? "w-full"
                      : "w-0"
                }`}
              />
            </button>
          ))}
        </div>

        <div className="absolute left-5 top-10 rounded-full bg-black/25 px-3 py-1 text-xs font-bold backdrop-blur">
          Scene {currentSceneIndex + 1} of {scenes.length}
        </div>

        <div className="absolute inset-x-6 top-24 rounded-[1.6rem] border border-white/20 bg-white/15 p-5 backdrop-blur-md">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-white/70">
            Visual direction
          </p>
          <p className="mt-3 text-xl font-black leading-tight tracking-[-0.04em]">
            {currentScene.visual}
          </p>
        </div>

        <div className="absolute inset-x-5 bottom-5 space-y-4">
          <h3 className="text-3xl font-black leading-tight tracking-[-0.05em]">
            {compact ? currentScene.title : title}
          </h3>
          <p className="rounded-2xl bg-black/30 px-4 py-3 text-sm font-semibold leading-6 text-white/90 backdrop-blur">
            {currentScene.caption}
          </p>
        </div>
      </div>

      <div className="space-y-4 p-4">
        <div className="h-2 overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full rounded-full bg-blue-600 transition-all"
            style={{ width: `${progress}%` }}
          />
        </div>
        <p className="text-sm leading-6 text-slate-700">{currentScene.narration}</p>
        <div className="grid grid-cols-4 gap-2">
          <button type="button" className="player-button" onClick={goToPreviousScene}>
            Prev
          </button>
          <button
            type="button"
            className="player-button bg-slate-950 text-white hover:bg-blue-700"
            onClick={() => setIsPlaying((current) => !current)}
          >
            {isPlaying ? "Pause" : "Play"}
          </button>
          <button type="button" className="player-button" onClick={goToNextScene}>
            Next
          </button>
          <button type="button" className="player-button" onClick={speakScene}>
            {isSpeaking ? "Stop" : "Voice"}
          </button>
        </div>
      </div>
    </div>
  );
}
