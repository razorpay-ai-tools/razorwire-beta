'use client';

/**
 * One post, one viewport. Dispatches on `kind` — the two variants share chrome but
 * not structure, so this is a switch, not a component with a dozen flags.
 *
 * At `lg:` and wider the same post becomes a split card instead: player left, audit
 * panel right. The choice is made by media query rather than by rendering both trees
 * and hiding one, because both mounted at once means two mermaid renders, two b-roll
 * videos and two speech utterances per post.
 */

import type { Post } from '@/lib/api';
import { ClipPost } from './ClipPost';
import { DesktopCard, useIsDesktop } from './DesktopCard';
import { GeneratedPost } from './GeneratedPost';

export function FeedPost({ post, active }: { post: Post; active: boolean }) {
  const desktop = useIsDesktop();

  if (desktop) return <DesktopCard post={post} active={active} />;
  if (post.kind === 'clip') return <ClipPost post={post} active={active} />;
  return <GeneratedPost post={post} active={active} />;
}
