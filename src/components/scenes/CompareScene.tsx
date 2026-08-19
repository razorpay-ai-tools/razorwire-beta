/**
 * Before and after.
 *
 * Stacked, not side by side. Two columns of four items at 360px leaves ~150px per
 * column, which either truncates every item to uselessness or drops to a font size
 * nobody reads on a phone held at arm's length. Stacking costs vertical space we
 * have (the safe area is ~9:16 tall) and buys full-width lines.
 *
 * Direction of change is carried three ways, none of them colour alone: the
 * "Before"/"After" eyebrow, the arrow-plus-"becomes" divider between the panes, and
 * a cross/tick glyph per row.
 */

import type { ComparePane, CompareScene as CompareSceneData } from '@/lib/storyboard.types';
import { Icon } from '@/components/ui';
import { SceneShell, TEXT_SHADOW } from './SceneShell';

/** Contract allows 1–4 per pane. Slice defensively. */
const MAX_ITEMS = 4;

export function CompareScene({ scene, active }: { scene: CompareSceneData; active: boolean }) {
  return (
    <SceneShell cite={scene.cite} active={active}>
      <h2
        className={`text-balance text-[22px] font-bold leading-tight tracking-[-0.02em] text-white ${TEXT_SHADOW}`}
      >
        {scene.heading}
      </h2>

      <Pane pane={scene.left} side="before" />

      <div className="flex items-center justify-center gap-2 font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-brand-300">
        <span aria-hidden="true" className="h-3.5 w-px bg-brand-500/60" />
        <Icon name="play" label={null} filled className="size-2.5 rotate-90" />
        <span>becomes</span>
      </div>

      <Pane pane={scene.right} side="after" />
    </SceneShell>
  );
}

function Pane({ pane, side }: { pane: ComparePane; side: 'before' | 'after' }) {
  const isAfter = side === 'after';

  return (
    <section
      className={`panel px-3 py-2.5 ${isAfter ? 'border-brand-500/45 bg-brand-700/15' : ''}`}
    >
      <h3 className="flex items-baseline gap-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.14em]">
        <span className={isAfter ? 'text-brand-300' : 'text-neutral-400'}>{side}</span>
        <span aria-hidden="true" className="text-neutral-600">
          /
        </span>
        <span className="truncate text-neutral-100">{pane.label}</span>
      </h3>

      <ul className="mt-2 flex flex-col gap-1.5">
        {pane.items.slice(0, MAX_ITEMS).map((item, i) => (
          <li key={`${i}-${item}`} className="flex items-start gap-2">
            {/* Decorative: the eyebrow above already says which side this is. */}
            <Icon
              name={isAfter ? 'check' : 'close'}
              label={null}
              className={`mt-0.5 size-3.5 shrink-0 ${
                isAfter ? 'text-brand-300' : 'text-neutral-500'
              }`}
            />
            <span className="line-clamp-2 text-[13px] font-medium leading-snug text-neutral-50">
              {item}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
