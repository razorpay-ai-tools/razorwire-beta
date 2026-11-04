/**
 * How each video theme shows up in the app chrome. The accents mirror `THEMES` in
 * backend/app/render/hyperframes.py, so a post's badge, progress rail and controls wear
 * the same colour as the reel they frame. Update the two together.
 */

import type { CSSProperties } from 'react';
import type { Post } from './api';
import type { Theme } from './storyboard.types';

export const THEME_STYLE: Record<Theme, { label: string; accent: string }> = {
  explainer: { label: 'Explainer', accent: '#60a5fa' },
  launch: { label: 'Launch', accent: '#c6ff3d' },
  incident: { label: 'Incident', accent: '#f59e0b' },
  blueprint: { label: 'Blueprint', accent: '#22d3ee' },
};

/** A generated post's theme. Storyboards that predate themes render as `explainer`,
 *  exactly as the backend defaults them; a clip has none. */
export function postTheme(post: Post): Theme | null {
  if (post.kind !== 'generated') return null;
  return post.storyboard?.meta.theme ?? 'explainer';
}

/** `--post-accent` for a post's root, read by the badge, rail and avatar. */
export function accentStyle(post: Post): CSSProperties | undefined {
  const theme = postTheme(post);
  return theme ? ({ '--post-accent': THEME_STYLE[theme].accent } as CSSProperties) : undefined;
}
