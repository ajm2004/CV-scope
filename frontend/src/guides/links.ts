/* How a link written in a guide behaves in the app. Guides link to each other
 * with relative file names (01-tour.md), which GitHub also understands. */

export type LinkTarget =
  | { kind: "external"; href: string }
  | { kind: "anchor"; id: string }
  | { kind: "guide"; slug: string; id: string }
  | { kind: "index" }
  | { kind: "app"; to: string }
  | { kind: "none" };

export function classifyLink(href: string): LinkTarget {
  const h = href.trim();
  if (/^(https?:|mailto:)/i.test(h)) return { kind: "external", href: h };
  if (h.startsWith("#")) return { kind: "anchor", id: decodeURIComponent(h.slice(1)) };
  const guide = /^(?:\.\/)?(\d{2}-[\w-]+)\.md(?:#(.*))?$/.exec(h);
  if (guide) return { kind: "guide", slug: guide[1], id: guide[2] ? decodeURIComponent(guide[2]) : "" };
  if (/^(?:\.\/)?README\.md$/i.test(h)) return { kind: "index" };
  if (/^\/(projects|live|experiments|data|analysis|cameras|models|hardware|settings|guides|recognition|anomalies)(\/|$)/.test(h)) return { kind: "app", to: h };
  return { kind: "none" };
}
