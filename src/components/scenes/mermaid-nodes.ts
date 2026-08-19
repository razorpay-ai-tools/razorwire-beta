/**
 * Node labels lifted out of a mermaid source, in source order.
 *
 * Two callers, both in DiagramScene: the screen-reader alternative for a rendered
 * diagram, and the visible fallback when mermaid fails to render. A viewer must
 * never see a broken diagram or an error string, so the fallback has to be able to
 * say what the graph contained without mermaid's help.
 *
 * ponytail: a regex over the declaration shapes the contract's graphs actually use
 * (`A[x]`, `A(x)`, `A{x}`, `A[(x)]`, `A((x))`, `A{{x}}`), not a grammar. Upgrade to
 * mermaid's own parser only if the generator starts emitting shapes this misses.
 * Kept dependency-free so the self-check can import it under bare node.
 */

const NODE = /\b([A-Za-z]\w*)\s*(?:\[\(|\(\(|\{\{|\[|\(|\{)\s*"?([^\]})">|]+)/g;

export function parseMermaidNodes(mermaid: string): string[] {
  const byId = new Map<string, string>();

  for (const [, id, rawLabel] of mermaid.matchAll(NODE)) {
    const label = rawLabel
      .replace(/<br\s*\/?>/gi, ' ')
      .replace(/\s+/g, ' ')
      .replace(/"+$/, '')
      .trim();

    if (label && !byId.has(id)) byId.set(id, label);
  }

  return [...byId.values()];
}
