'use client';

/**
 * One post, one viewport. Dispatches on `kind` — the two variants share chrome but
 * not structure, so this is a switch, not a component with a dozen flags.
 */

import type { Post } from '@/lib/api';
import { ClipPost } from './ClipPost';
import { GeneratedPost } from './GeneratedPost';

export function FeedPost({ post, active }: { post: Post; active: boolean }) {
  if (post.kind === 'clip') return <ClipPost post={post} active={active} />;
  return <GeneratedPost post={post} active={active} />;
}
