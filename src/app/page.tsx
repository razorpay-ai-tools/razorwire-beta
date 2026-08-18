"use client";

import { useMemo, useState } from "react";
import { AIDocGenerator } from "@/components/AIDocGenerator";
import { CreateClipForm } from "@/components/CreateClipForm";
import { VideoFeed } from "@/components/VideoFeed";
import { seedVideos } from "@/lib/demo-data";
import type { VideoItem } from "@/lib/types";

export default function Home() {
  const [items, setItems] = useState<VideoItem[]>(seedVideos);
  const [activeId, setActiveId] = useState(seedVideos[0]?.id ?? "");
  const generatedCount = useMemo(
    () => items.filter((item) => item.kind === "generated").length,
    [items]
  );

  function addItem(item: VideoItem) {
    setItems((current) => [item, ...current]);
    setActiveId(item.id);
  }

  function resetFeed() {
    setItems(seedVideos);
    setActiveId(seedVideos[0]?.id ?? "");
  }

  function updateItem(id: string, updater: (item: VideoItem) => VideoItem) {
    setItems((current) =>
      current.map((item) => (item.id === id ? updater(item) : item))
    );
  }

  function toggleLike(id: string) {
    updateItem(id, (item) => {
      const liked = Boolean(item.viewerState?.liked);

      return {
        ...item,
        reactions: {
          ...item.reactions,
          useful: Math.max(0, item.reactions.useful + (liked ? -1 : 1)),
        },
        viewerState: {
          ...item.viewerState,
          liked: !liked,
        },
      };
    });
  }

  function toggleSave(id: string) {
    updateItem(id, (item) => {
      const saved = Boolean(item.viewerState?.saved);

      return {
        ...item,
        reactions: {
          ...item.reactions,
          saved: Math.max(0, item.reactions.saved + (saved ? -1 : 1)),
        },
        viewerState: {
          ...item.viewerState,
          saved: !saved,
        },
      };
    });
  }

  function addComment(id: string, text: string) {
    updateItem(id, (item) => ({
      ...item,
      comments: [
        {
          id: `comment-${Date.now()}`,
          author: "You",
          text,
          createdAt: "Just now",
        },
        ...(item.comments ?? []),
      ],
      reactions: {
        ...item.reactions,
        questions: item.reactions.questions + 1,
      },
    }));
  }

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_left,#dbeafe,transparent_34%),linear-gradient(180deg,#f8fafc_0%,#eef2ff_100%)] text-slate-950">
      <TopNav />
      <section className="mx-auto grid w-full max-w-7xl gap-8 px-4 py-6 sm:px-8 lg:grid-cols-[minmax(0,1fr)_430px]">
        <div className="space-y-6">
          <IntroStrip
            clipCount={items.length}
            generatedCount={generatedCount}
            onReset={resetFeed}
          />
          <VideoFeed
            items={items}
            activeId={activeId}
            onSelect={setActiveId}
            onToggleLike={toggleLike}
            onToggleSave={toggleSave}
            onAddComment={addComment}
          />
        </div>

        <aside className="space-y-5 lg:sticky lg:top-24 lg:self-start">
          <AIDocGenerator onPublish={addItem} />
          <CreateClipForm onCreate={addItem} />
          <HowItWorks />
        </aside>
      </section>
    </main>
  );
}

function TopNav() {
  return (
    <header className="sticky top-0 z-30 border-b border-white/70 bg-white/85 backdrop-blur-xl">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-8">
        <div className="flex items-center gap-3">
          <div className="grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-blue-600 to-violet-600 text-lg font-black text-white shadow-lg shadow-blue-600/20">
            R
          </div>
          <div>
            <p className="text-xl font-black tracking-[-0.05em] text-slate-950">
              Razorwire
            </p>
            <p className="hidden text-xs font-medium text-slate-500 sm:block">
              Internal reels for products, systems, and culture
            </p>
          </div>
        </div>
        <nav className="flex items-center gap-2 text-sm font-bold">
          <a
            href="#feed"
            className="rounded-full bg-slate-950 px-4 py-2 text-white transition hover:bg-blue-700"
          >
            Feed
          </a>
          <a
            href="#create"
            className="rounded-full border border-slate-200 bg-white px-4 py-2 text-slate-700 transition hover:border-blue-200 hover:text-blue-700"
          >
            Create
          </a>
        </nav>
      </div>
    </header>
  );
}

function IntroStrip({
  clipCount,
  generatedCount,
  onReset,
}: {
  clipCount: number;
  generatedCount: number;
  onReset: () => void;
}) {
  return (
    <section className="rounded-[2rem] border border-white/80 bg-white/80 p-5 shadow-xl shadow-blue-950/8 backdrop-blur sm:p-6">
      <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-bold uppercase tracking-[0.22em] text-blue-600">
            Today on Razorwire
          </p>
          <h1 className="mt-2 max-w-2xl text-3xl font-black leading-tight tracking-[-0.05em] text-slate-950 sm:text-5xl">
            Learn a product, system, or spec in one scroll.
          </h1>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:min-w-56">
          <Stat label="Posts" value={clipCount} />
          <Stat label="AIDoc reels" value={generatedCount} />
        </div>
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <a
          href="#generate"
          className="rounded-full bg-blue-600 px-5 py-3 text-sm font-bold text-white transition hover:-translate-y-0.5 hover:bg-blue-700"
        >
          Generate from AIDoc
        </a>
        <a
          href="#create"
          className="rounded-full bg-slate-100 px-5 py-3 text-sm font-bold text-slate-700 transition hover:-translate-y-0.5 hover:bg-white"
        >
          Post a clip
        </a>
        <button
          type="button"
          onClick={onReset}
          className="ml-auto text-sm font-bold text-slate-500 transition hover:text-slate-950"
        >
          Reset feed
        </button>
      </div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-3xl bg-slate-50 px-4 py-4 text-center">
      <div className="text-2xl font-black tracking-[-0.04em] text-slate-950">
        {value}
      </div>
      <div className="mt-1 text-[11px] font-bold uppercase tracking-[0.18em] text-slate-500">
        {label}
      </div>
    </div>
  );
}

function HowItWorks() {
  const steps = [
    "Paste or upload a spec.",
    "Create a playable reel draft with captions and narration.",
    "Post the reel so teammates can like, save, comment, and share it.",
  ];

  return (
    <section className="rounded-[2rem] border border-slate-200 bg-white p-6 shadow-xl shadow-slate-950/5">
      <p className="text-sm font-bold uppercase tracking-[0.22em] text-blue-600">
        How it works
      </p>
      <h2 className="mt-2 text-2xl font-black tracking-[-0.04em] text-slate-950">
        Turn source-of-truth docs into watchable drafts.
      </h2>
      <ol className="mt-5 space-y-3">
        {steps.map((step, index) => (
          <li key={step} className="flex gap-3 text-sm leading-6 text-slate-600">
            <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-blue-50 text-xs font-black text-blue-700">
              {index + 1}
            </span>
            {step}
          </li>
        ))}
      </ol>
    </section>
  );
}
