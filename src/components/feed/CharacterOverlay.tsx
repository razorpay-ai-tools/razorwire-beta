'use client';

import { useState } from 'react';
import type { Scene } from '@/lib/storyboard.types';

const sceneLabel: Record<Scene['type'], string> = {
  title: 'Let’s set the scene',
  bullets: 'Here are the key moves',
  diagram: 'Let’s follow the flow',
  compare: 'Here’s the trade-off',
  code: 'Here’s the working shape',
  outro: 'Ready for the next step?',
};

export function CharacterOverlay({
  scene,
  caption,
  index,
  active,
}: {
  scene: Scene;
  caption: string | null;
  index: number;
  active: boolean;
}) {
  const [open, setOpen] = useState(false);
  const guide = sceneLabel[scene.type];

  return (
    <div className="pointer-events-none absolute inset-x-4 top-[23%] z-25 flex items-end gap-2">
      <div
        className={`pointer-events-auto max-w-[min(72%,18rem)] transition-all duration-300 ${
          active ? 'translate-x-0 opacity-100' : '-translate-x-2 opacity-0'
        }`}
      >
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          className="panel group flex items-center gap-2 px-2.5 py-2 text-left shadow-xl shadow-black/20 backdrop-blur-md"
        >
          <span
            aria-hidden
            className="character character-ria grid size-9 shrink-0 place-items-center rounded-full border-2 border-white/70 bg-brand-500 font-bold text-white shadow-lg"
          >
            R
          </span>
          <span className="min-w-0">
            <span className="block font-mono text-[9px] font-bold uppercase tracking-[0.15em] text-brand-300">
              Ria · curious
            </span>
            <span className="mt-0.5 block text-xs font-semibold leading-snug text-white">
              {guide}
            </span>
          </span>
          <span aria-hidden className="ml-auto text-neutral-400 transition group-hover:text-white">
            {open ? '−' : '?'}
          </span>
        </button>

        {open ? (
          <div className="panel mt-2 max-w-[17rem] animate-fade-in px-3 py-2.5 text-xs leading-relaxed text-neutral-100 shadow-xl shadow-black/30 backdrop-blur-md">
            <div className="mb-1 flex items-center gap-2 font-mono text-[9px] font-bold uppercase tracking-[0.15em] text-warning">
              <span aria-hidden className="character character-byte grid size-5 place-items-center rounded-full bg-warning text-[10px] text-white">B</span>
              Byte · guide
            </div>
            {caption ?? 'Use the scene controls to keep exploring.'}
          </div>
        ) : null}
      </div>

      <span aria-hidden className="character-dots mb-1 flex gap-1">
        <i />
        <i />
        <i />
      </span>

      <span className="sr-only">Scene {index + 1}: {guide}</span>
    </div>
  );
}
