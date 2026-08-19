/**
 * Up to twelve lines of code, over video.
 *
 * Scrolls horizontally rather than wrapping: a wrapped line of Go reads as a
 * different program. No highlighting dependency — a 12-line snippet does not justify
 * shipping a grammar for six languages, so this is one regex pass that tints strings,
 * comments, numbers and keywords. Keywords also get weight and comments also get
 * italics, so the tint is never the only signal.
 */

import type { ReactNode } from 'react';
import type { CodeScene as CodeSceneData } from '@/lib/storyboard.types';
import { SceneShell, TEXT_SHADOW } from './SceneShell';

const MAX_LINES = 12;

const KEYWORDS = [
  // go
  'func', 'return', 'if', 'else', 'for', 'range', 'type', 'struct', 'interface',
  'const', 'var', 'import', 'package', 'map', 'chan', 'go', 'defer', 'nil',
  // ts
  'function', 'class', 'async', 'await', 'let', 'export', 'default', 'new', 'null',
  'undefined', 'true', 'false',
  // sql
  'select', 'from', 'where', 'join', 'on', 'group', 'order', 'by', 'limit',
  'insert', 'update', 'set', 'and', 'or', 'not',
].join('|');

/**
 * One capture group so `String.split` hands back [plain, token, plain, token, …].
 * Order matters: string literals first, so a `#` or `//` inside a string is not
 * mistaken for a comment.
 */
const TOKEN = new RegExp(
  [
    '(',
    '"(?:[^"\\\\]|\\\\.)*"',
    "|'(?:[^'\\\\]|\\\\.)*'",
    '|`(?:[^`\\\\]|\\\\.)*`',
    '|(?:^|\\s)(?://|#|--)[^\\n]*',
    `|\\b(?:${KEYWORDS})\\b`,
    '|\\b\\d+(?:\\.\\d+)?\\b',
    ')',
  ].join(''),
  'gim',
);

function tokenClass(token: string): string {
  const t = token.trimStart();
  if (/^["'`]/.test(t)) return 'text-brand-300';
  if (t.startsWith('//') || t.startsWith('#') || t.startsWith('--')) {
    return 'italic text-neutral-500';
  }
  if (/^\d/.test(t)) return 'text-neutral-300';
  return 'font-semibold text-brand-400';
}

function tint(code: string): ReactNode[] {
  return code.split(TOKEN).map((part, i) =>
    i % 2 === 0 ? (
      part
    ) : (
      <span key={i} className={tokenClass(part)}>
        {part}
      </span>
    ),
  );
}

export function CodeScene({ scene, active }: { scene: CodeSceneData; active: boolean }) {
  const code = scene.code
    .replace(/\t/g, '  ')
    .replace(/\s+$/, '')
    .split('\n')
    .slice(0, MAX_LINES)
    .join('\n');

  return (
    <SceneShell cite={scene.cite} active={active}>
      {scene.heading || scene.lang ? (
        <div className="flex items-baseline justify-between gap-2">
          {scene.heading ? (
            <h2
              className={`text-balance text-lg font-bold leading-tight tracking-[-0.02em] text-white ${TEXT_SHADOW}`}
            >
              {scene.heading}
            </h2>
          ) : null}
          {scene.lang ? (
            <span className="shrink-0 rounded-md border border-white/15 bg-neutral-950/70 px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-neutral-300 backdrop-blur-md">
              {scene.lang}
            </span>
          ) : null}
        </div>
      ) : null}

      <div className="panel min-h-0 overflow-hidden">
        {/* Focusable so the snippet can be scrolled from a keyboard, not just a thumb. */}
        <pre
          role="region"
          aria-label={scene.lang ? `${scene.lang} code sample` : 'Code sample'}
          tabIndex={0}
          className="max-h-full overflow-auto p-3 font-mono text-[11.5px] leading-[1.6] text-neutral-100"
        >
          <code>{tint(code)}</code>
        </pre>
      </div>
    </SceneShell>
  );
}
