import type { VideoItem } from "@/lib/types";
import { VideoCard } from "./VideoCard";

type VideoFeedProps = {
  items: VideoItem[];
  activeId: string;
  onSelect: (id: string) => void;
  onToggleLike: (id: string) => void;
  onToggleSave: (id: string) => void;
  onAddComment: (id: string, text: string) => void;
};

export function VideoFeed({
  items,
  activeId,
  onSelect,
  onToggleLike,
  onToggleSave,
  onAddComment,
}: VideoFeedProps) {
  return (
    <section className="space-y-5" id="feed">
      <div className="flex items-end justify-between px-1">
        <div>
          <p className="text-sm font-bold uppercase tracking-[0.22em] text-blue-600">
            For you
          </p>
          <h2 className="mt-1 text-3xl font-black tracking-[-0.04em] text-slate-950">
            Razorwire feed
          </h2>
        </div>
        <p className="hidden max-w-xs text-right text-sm leading-6 text-slate-500 sm:block">
          Clips from teams. Explainers from AIDocs. One scrollable feed.
        </p>
      </div>

      <div className="max-h-[calc(100vh-9rem)] space-y-7 overflow-y-auto rounded-[2.2rem] bg-slate-100/80 px-3 py-5 shadow-inner snap-y snap-mandatory sm:px-5">
        {items.map((item) => (
          <VideoCard
            key={item.id}
            item={item}
            isActive={item.id === activeId}
            onSelect={onSelect}
            onToggleLike={onToggleLike}
            onToggleSave={onToggleSave}
            onAddComment={onAddComment}
          />
        ))}
      </div>
    </section>
  );
}
