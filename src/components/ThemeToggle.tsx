'use client';

/**
 * Light / dark switch.
 *
 * Holds NO React state, deliberately. `data-theme` on <html> is the single source of
 * truth, set before first paint by the inline script in `layout.tsx`, so:
 *   - no `setState` in an effect (which cascades renders, and the linter rejects)
 *   - no hydration mismatch, since the server never has to guess the preference
 *   - no flash of the wrong theme
 *
 * Both icons are rendered and CSS shows the right one (see `globals.css`), which is why
 * the current theme never needs to reach JavaScript.
 *
 * The 9:16 video stage does NOT follow this — it is wrapped in `stage-dark`, because
 * captions and scene text sit over arbitrary footage and a light scrim cannot keep them
 * legible. Only the surrounding chrome flips.
 */

import { Icon } from './ui';

const STORAGE_KEY = 'razorwire-theme';

function toggleTheme() {
  const root = document.documentElement;
  const next = root.dataset.theme === 'light' ? 'dark' : 'light';
  root.dataset.theme = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // Private mode or a full quota. The theme still applies for this session.
  }
}

export function ThemeToggle({ className = '' }: { className?: string }) {
  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label="Switch between light and dark theme"
      title="Switch theme"
      className={`grid size-8 place-items-center rounded-full border border-white/10 text-neutral-300 transition-colors hover:text-white ${className}`}
    >
      <span className="theme-icon-sun contents">
        <Icon name="sun" label={null} className="size-3.5" />
      </span>
      <span className="theme-icon-moon contents">
        <Icon name="moon" label={null} className="size-3.5" />
      </span>
    </button>
  );
}
