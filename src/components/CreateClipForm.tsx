import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { accentOptions, categoryOptions } from "@/lib/demo-data";
import type { VideoCategory, VideoItem } from "@/lib/types";

type CreateClipFormProps = {
  onCreate: (item: VideoItem) => void;
};

const initialState = {
  title: "",
  team: "",
  author: "",
  category: "Product" as VideoCategory,
  description: "",
  tags: "",
  duration: "1:30",
};

export function CreateClipForm({ onCreate }: CreateClipFormProps) {
  const [form, setForm] = useState(initialState);

  function updateField<Key extends keyof typeof form>(
    key: Key,
    value: (typeof form)[Key]
  ) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const title = form.title.trim();
    const description = form.description.trim();

    if (!title || !description) {
      return;
    }

    const item: VideoItem = {
      id: `clip-${Date.now()}`,
      title,
      team: form.team.trim() || "Razorpay Team",
      author: form.author.trim() || "Razorwire Creator",
      category: form.category,
      description,
      tags: form.tags
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean)
        .slice(0, 4),
      duration: form.duration.trim() || "1:30",
      createdAt: "Just now",
      kind: "clip",
      accent: accentOptions[Math.floor(Date.now() % accentOptions.length)],
      reactions: { useful: 0, saved: 0, questions: 0 },
      scenes: [
        {
          title: "1. Key takeaway",
          visual: "Creator-posted internal learning clip",
          narration: description,
          caption: title,
        },
      ],
    };

    onCreate(item);
    setForm(initialState);
  }

  return (
    <section
      className="rounded-[2rem] border border-slate-200 bg-white p-6 shadow-xl shadow-slate-950/5"
      id="create"
    >
      <p className="text-sm font-bold uppercase tracking-[0.22em] text-blue-600">
        Create
      </p>
      <h2 className="mt-2 text-2xl font-black tracking-[-0.04em] text-slate-950">
        Post a clip
      </h2>
      <p className="mt-3 text-sm leading-6 text-slate-600">
        Capture the title, owner, and key takeaway so teammates can discover it
        in the feed.
      </p>

      <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
        <Field label="Title">
          <input
            value={form.title}
            onChange={(event) => updateField("title", event.target.value)}
            placeholder="e.g. Refund states in 60 seconds"
            className="input"
            required
          />
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Team">
            <input
              value={form.team}
              onChange={(event) => updateField("team", event.target.value)}
              placeholder="Payments Platform"
              className="input"
            />
          </Field>
          <Field label="Author">
            <input
              value={form.author}
              onChange={(event) => updateField("author", event.target.value)}
              placeholder="Your name"
              className="input"
            />
          </Field>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Category">
            <select
              value={form.category}
              onChange={(event) =>
                updateField("category", event.target.value as VideoCategory)
              }
              className="input"
            >
              {categoryOptions.map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Duration">
            <input
              value={form.duration}
              onChange={(event) => updateField("duration", event.target.value)}
              placeholder="1:30"
              className="input"
            />
          </Field>
        </div>

        <Field label="What should viewers learn?">
          <textarea
            value={form.description}
            onChange={(event) => updateField("description", event.target.value)}
            placeholder="Summarize the clip in one or two lines."
            className="input min-h-28 resize-none"
            required
          />
        </Field>

        <Field label="Tags">
          <input
            value={form.tags}
            onChange={(event) => updateField("tags", event.target.value)}
            placeholder="refunds, onboarding, product"
            className="input"
          />
        </Field>

        <button
          type="submit"
          className="w-full rounded-2xl bg-slate-950 px-5 py-4 text-sm font-bold text-white transition hover:-translate-y-0.5 hover:bg-blue-700"
        >
          Post to feed
        </button>
      </form>
    </section>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-bold uppercase tracking-[0.18em] text-slate-500">
        {label}
      </span>
      {children}
    </label>
  );
}
