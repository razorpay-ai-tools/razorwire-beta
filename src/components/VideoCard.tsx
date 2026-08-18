import { useState } from "react";
import type { FormEvent } from "react";
import { ReelPlayer } from "./ReelPlayer";
import type { VideoItem } from "@/lib/types";

type VideoCardProps = {
  item: VideoItem;
  isActive: boolean;
  onSelect: (id: string) => void;
  onToggleLike: (id: string) => void;
  onToggleSave: (id: string) => void;
  onAddComment: (id: string, text: string) => void;
};

export function VideoCard({
  item,
  isActive,
  onSelect,
  onToggleLike,
  onToggleSave,
  onAddComment,
}: VideoCardProps) {
  const [commentsOpen, setCommentsOpen] = useState(false);
  const [commentText, setCommentText] = useState("");
  const [shareStatus, setShareStatus] = useState("");
  const firstScene = item.scenes?.[0];
  const comments = item.comments ?? [];
  const isLiked = Boolean(item.viewerState?.liked);
  const isSaved = Boolean(item.viewerState?.saved);
  const initials = item.author
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  async function shareItem() {
    const shareText = `${item.title}\n\n${item.description}\n\nShared from Razorwire`;

    try {
      if (navigator.share) {
        await navigator.share({ title: item.title, text: shareText });
        setShareStatus("Shared");
      } else {
        await navigator.clipboard.writeText(shareText);
        setShareStatus("Copied");
      }
    } catch {
      setShareStatus("Share cancelled");
    }

    window.setTimeout(() => setShareStatus(""), 1800);
  }

  function submitComment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = commentText.trim();

    if (!text) {
      return;
    }

    onAddComment(item.id, text);
    setCommentText("");
    setCommentsOpen(true);
  }

  return (
    <article
      className={`mx-auto w-full max-w-[520px] snap-center overflow-hidden rounded-[2rem] border bg-white shadow-xl shadow-slate-950/8 transition duration-300 ${
        isActive
          ? "border-blue-400 ring-4 ring-blue-100"
          : "border-slate-200 hover:-translate-y-1 hover:border-slate-300"
      }`}
    >
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <div
            className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-gradient-to-br text-sm font-black text-white ${item.accent}`}
          >
            {initials || "RZ"}
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-bold text-slate-950">
              {item.team}
            </p>
            <p className="truncate text-xs text-slate-500">
              {item.author} · {item.createdAt}
            </p>
          </div>
        </div>
        <div className="rounded-full bg-slate-100 px-3 py-1 text-xs font-bold text-slate-700">
          {item.duration}
        </div>
      </div>

      <button
        type="button"
        onClick={() => onSelect(item.id)}
        className={`relative block aspect-[9/14] w-full overflow-hidden bg-gradient-to-br text-left text-white ${item.accent}`}
        aria-label={`Focus ${item.title}`}
      >
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_35%_20%,rgba(255,255,255,0.35),transparent_30%),linear-gradient(180deg,rgba(15,23,42,0)_0%,rgba(15,23,42,0.78)_100%)]" />

        <div className="absolute left-5 top-5 flex items-center gap-2 rounded-full border border-white/25 bg-black/20 px-3 py-1.5 text-xs font-bold backdrop-blur">
          <span className="h-2 w-2 rounded-full bg-red-400" />
          {item.kind === "generated" ? "AIDoc Reel" : item.category}
        </div>

        <div className="absolute right-4 top-1/2 flex -translate-y-1/2 flex-col items-center gap-4">
          <ReactionIcon
            label="Useful"
            value={item.reactions.useful}
            icon={isLiked ? "♥" : "♡"}
            active={isLiked}
          />
          <ReactionIcon
            label="Saved"
            value={item.reactions.saved}
            icon={isSaved ? "▰" : "▱"}
            active={isSaved}
          />
          <ReactionIcon label="Comments" value={comments.length} icon="💬" />
        </div>

        <div className="absolute inset-x-6 top-28 rounded-[1.75rem] border border-white/20 bg-white/12 p-4 shadow-2xl backdrop-blur-md">
          <div className="mb-4 flex items-center justify-between text-xs font-semibold text-white/75">
            <span>{item.kind === "generated" ? "Playable reel" : "Clip preview"}</span>
            <span>{item.scenes?.length ?? 1} scenes</span>
          </div>
          <div className="space-y-3">
            <div className="h-2 w-4/5 rounded-full bg-white/55" />
            <div className="h-2 w-2/3 rounded-full bg-white/35" />
            <div className="grid grid-cols-3 gap-2 pt-2">
              <div className="h-20 rounded-2xl bg-white/25" />
              <div className="h-20 rounded-2xl bg-white/15" />
              <div className="h-20 rounded-2xl bg-white/25" />
            </div>
          </div>
        </div>

        <div className="absolute inset-x-5 bottom-5 space-y-4">
          <div className="inline-flex items-center gap-2 rounded-full bg-white px-3 py-1 text-xs font-black text-slate-950 shadow-lg">
            <span className="grid h-5 w-5 place-items-center rounded-full bg-slate-950 text-[9px] text-white">
              ▶
            </span>
            Tap to focus
          </div>
          <div>
            <h3 className="text-3xl font-black leading-tight tracking-[-0.04em] drop-shadow-sm">
              {item.title}
            </h3>
            {firstScene ? (
              <p className="mt-3 rounded-2xl bg-black/25 px-4 py-3 text-sm font-semibold leading-6 text-white/90 backdrop-blur">
                {firstScene.caption}
              </p>
            ) : null}
          </div>
        </div>
      </button>

      <div className="space-y-4 px-4 py-4">
        <div className="flex items-center justify-between text-sm">
          <div className="flex gap-4 text-2xl text-slate-950">
            <button
              type="button"
              onClick={() => onToggleLike(item.id)}
              className={isLiked ? "text-rose-600" : "hover:text-rose-600"}
              aria-label={isLiked ? "Unlike" : "Like"}
            >
              {isLiked ? "♥" : "♡"}
            </button>
            <button
              type="button"
              onClick={() => setCommentsOpen((current) => !current)}
              className="hover:text-blue-700"
              aria-label="Comment"
            >
              💬
            </button>
            <button
              type="button"
              onClick={shareItem}
              className="hover:text-blue-700"
              aria-label="Share"
            >
              ↗
            </button>
          </div>
          <button
            type="button"
            onClick={() => onToggleSave(item.id)}
            className={`text-2xl ${isSaved ? "text-blue-700" : "hover:text-blue-700"}`}
            aria-label={isSaved ? "Unsave" : "Save"}
          >
            {isSaved ? "▰" : "▱"}
          </button>
        </div>

        {shareStatus ? (
          <p className="rounded-full bg-slate-100 px-3 py-1 text-xs font-bold text-slate-600">
            {shareStatus}
          </p>
        ) : null}

        <p className="text-sm font-bold text-slate-950">
          {item.reactions.useful} useful · {item.reactions.saved} saved · {comments.length} comments
        </p>

        <div>
          <p className="text-sm leading-6 text-slate-800">
            <span className="font-black">{item.team}</span> {item.description}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {item.tags.map((tag) => (
              <span key={tag} className="text-sm font-semibold text-blue-700">
                #{tag}
              </span>
            ))}
          </div>
        </div>

        {item.scenes?.length ? (
          <details className="rounded-2xl bg-slate-50 p-4">
            <summary className="cursor-pointer text-sm font-bold text-slate-900">
              {item.kind === "generated" ? "Play reel draft" : "View storyboard"}
            </summary>
            <div className="mt-4">
              <ReelPlayer
                title={item.title}
                scenes={item.scenes}
                accent={item.accent}
                compact
              />
            </div>
            {item.script ? (
              <p className="mt-4 rounded-2xl bg-white p-4 text-sm leading-6 text-slate-600">
                {item.script}
              </p>
            ) : null}
          </details>
        ) : null}

        {commentsOpen ? (
          <div className="rounded-2xl border border-slate-200 bg-white p-4">
            <form className="flex gap-2" onSubmit={submitComment}>
              <input
                value={commentText}
                onChange={(event) => setCommentText(event.target.value)}
                className="input py-3"
                placeholder="Add a comment..."
              />
              <button
                type="submit"
                className="rounded-2xl bg-slate-950 px-4 text-sm font-bold text-white hover:bg-blue-700"
              >
                Post
              </button>
            </form>
            <div className="mt-4 space-y-3">
              {comments.length ? (
                comments.map((comment) => (
                  <div key={comment.id} className="text-sm leading-6">
                    <span className="font-black text-slate-950">{comment.author}</span>{" "}
                    <span className="text-slate-700">{comment.text}</span>
                    <p className="text-xs font-medium text-slate-400">{comment.createdAt}</p>
                  </div>
                ))
              ) : (
                <p className="text-sm text-slate-500">Start the conversation.</p>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </article>
  );
}

function ReactionIcon({
  label,
  value,
  icon,
  active = false,
}: {
  label: string;
  value: number;
  icon: string;
  active?: boolean;
}) {
  return (
    <div className="text-center drop-shadow-lg">
      <div
        className={`grid h-11 w-11 place-items-center rounded-full text-xl font-black backdrop-blur ${
          active ? "bg-white text-rose-600" : "bg-black/25 text-white"
        }`}
      >
        {icon}
      </div>
      <div className="mt-1 text-[11px] font-black text-white">{value}</div>
      <span className="sr-only">{label}</span>
    </div>
  );
}
