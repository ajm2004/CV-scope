/* A small Markdown parser for the guides in docs/guides.
 *
 * It covers the GitHub-flavoured subset the guides use, so the same files read
 * the same on GitHub and in the app: front matter, ATX headings with GitHub
 * anchor ids, paragraphs, nested ordered and bullet lists, fenced code, pipe
 * tables, block quotes with GitHub alerts (> [!TIP]), rules, and inline code,
 * bold, italic, links and bare URLs. Raw HTML is shown as text. */

export type Align = "left" | "center" | "right" | null;
export type CalloutKind = "note" | "tip" | "important" | "warning" | "caution" | "quote";

export type Block =
  | { type: "heading"; level: number; text: string; id: string }
  | { type: "paragraph"; text: string }
  | { type: "code"; lang: string; text: string }
  | { type: "list"; ordered: boolean; start: number; items: Block[][]; stepGroup?: number }
  | { type: "table"; header: string[]; align: Align[]; rows: string[][] }
  | { type: "callout"; kind: CalloutKind; blocks: Block[] }
  | { type: "hr" };

export type Inline =
  | { t: "text"; v: string }
  | { t: "code"; v: string }
  | { t: "strong"; c: Inline[] }
  | { t: "em"; c: Inline[] }
  | { t: "link"; href: string; c: Inline[] };

export interface Heading {
  level: number;
  text: string;
  id: string;
}

export interface ParsedDocument {
  meta: Record<string, string | string[]>;
  blocks: Block[];
  headings: Heading[];
  stepGroups: number;
}

// ---------------------------------------------------------------- front matter

/** Split a leading YAML front matter block (a small subset: scalars, [a, b] and "- item" lists). */
export function splitFrontMatter(src: string): { meta: Record<string, string | string[]>; body: string } {
  const text = src.replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n");
  if (!text.startsWith("---\n")) return { meta: {}, body: text };
  const end = text.indexOf("\n---", 4);
  if (end < 0) return { meta: {}, body: text };
  const head = text.slice(4, end);
  const after = text.indexOf("\n", end + 4);
  const body = after < 0 ? "" : text.slice(after + 1);
  const meta: Record<string, string | string[]> = {};
  let listKey: string | null = null;
  for (const raw of head.split("\n")) {
    if (!raw.trim() || raw.trim().startsWith("#")) continue;
    const item = /^\s*-\s+(.*)$/.exec(raw);
    if (item && listKey) {
      (meta[listKey] as string[]).push(unquote(item[1]));
      continue;
    }
    const kv = /^([A-Za-z_][\w-]*)\s*:\s*(.*)$/.exec(raw);
    if (!kv) continue;
    const [, key, value] = kv;
    if (value === "") {
      meta[key] = [];
      listKey = key;
    } else if (value.startsWith("[") && value.endsWith("]")) {
      meta[key] = splitInlineList(value.slice(1, -1));
      listKey = null;
    } else {
      meta[key] = unquote(value);
      listKey = null;
    }
  }
  return { meta, body };
}

function unquote(v: string): string {
  const s = v.trim();
  if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) return s.slice(1, -1);
  return s;
}

function splitInlineList(v: string): string[] {
  const out: string[] = [];
  let cur = "";
  let quote: string | null = null;
  for (const ch of v) {
    if (quote) {
      if (ch === quote) quote = null;
      else cur += ch;
    } else if (ch === '"' || ch === "'") quote = ch;
    else if (ch === ",") {
      if (cur.trim()) out.push(cur.trim());
      cur = "";
    } else cur += ch;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}

// ---------------------------------------------------------------- slugs

/** GitHub's heading anchor: lower case, punctuation removed, spaces to hyphens, duplicates numbered. */
export function createSlugger() {
  const seen = new Map<string, number>();
  return (text: string): string => {
    const base = text
      .trim()
      .toLowerCase()
      .replace(/[^\p{L}\p{N}\p{M}\s_-]/gu, "")
      .replace(/\s/g, "-");
    const n = seen.get(base);
    seen.set(base, (n ?? 0) + 1);
    return n === undefined ? base : `${base}-${n}`;
  };
}

// ---------------------------------------------------------------- blocks

const FENCE = /^(\s*)(`{3,}|~{3,})\s*([\w+#.-]*)\s*$/;
const HEADING = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const HR = /^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/;
const LIST_ITEM = /^(\s*)([*+-]|\d{1,9}[.)])(\s+)(.*)$/;
const QUOTE = /^\s{0,3}>\s?(.*)$/;
const TABLE_SEP = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;
const ALERT = /^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$/i;

function indentOf(line: string): number {
  let n = 0;
  for (const ch of line) {
    if (ch === " ") n += 1;
    else if (ch === "\t") n += 4 - (n % 4);
    else break;
  }
  return n;
}

function dedent(line: string, n: number): string {
  let i = 0;
  let col = 0;
  while (i < line.length && col < n && (line[i] === " " || line[i] === "\t")) {
    col += line[i] === "\t" ? 4 - (col % 4) : 1;
    i++;
  }
  return line.slice(i);
}

function isTableStart(lines: string[], i: number): boolean {
  return lines[i].includes("|") && i + 1 < lines.length && lines[i + 1].includes("-") && TABLE_SEP.test(lines[i + 1]);
}

function startsBlock(lines: string[], i: number): boolean {
  const l = lines[i];
  return FENCE.test(l) || HEADING.test(l) || HR.test(l) || QUOTE.test(l) || LIST_ITEM.test(l) || isTableStart(lines, i);
}

function splitRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|") && !s.endsWith("\\|")) s = s.slice(0, -1);
  const cells: string[] = [];
  let cur = "";
  let inCode = false;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (ch === "\\" && s[i + 1] === "|") {
      cur += "|";
      i++;
    } else if (ch === "`") {
      inCode = !inCode;
      cur += ch;
    } else if (ch === "|" && !inCode) {
      cells.push(cur.trim());
      cur = "";
    } else cur += ch;
  }
  cells.push(cur.trim());
  return cells;
}

type Slugger = (text: string) => string;

function parseBlocks(lines: string[], slug: Slugger, headings: Heading[]): Block[] {
  const out: Block[] = [];
  let i = 0;
  const n = lines.length;
  while (i < n) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    // fenced code
    const fence = FENCE.exec(line);
    if (fence) {
      const indent = fence[1].length;
      const marker = fence[2];
      const body: string[] = [];
      i++;
      while (i < n) {
        const close = /^(\s*)(`{3,}|~{3,})\s*$/.exec(lines[i]);
        if (close && close[2][0] === marker[0] && close[2].length >= marker.length) {
          i++;
          break;
        }
        body.push(dedent(lines[i], indent));
        i++;
      }
      out.push({ type: "code", lang: fence[3] || "", text: body.join("\n") });
      continue;
    }
    // heading
    const h = HEADING.exec(line);
    if (h) {
      const text = h[2];
      const id = slug(plainText(parseInline(text)));
      const level = h[1].length;
      out.push({ type: "heading", level, text, id });
      headings.push({ level, text: plainText(parseInline(text)), id });
      i++;
      continue;
    }
    // thematic break
    if (HR.test(line)) {
      out.push({ type: "hr" });
      i++;
      continue;
    }
    // block quote / GitHub alert
    if (QUOTE.test(line)) {
      const inner: string[] = [];
      while (i < n && QUOTE.test(lines[i])) {
        inner.push(QUOTE.exec(lines[i])![1]);
        i++;
      }
      let kind: CalloutKind = "quote";
      const alert = inner.length ? ALERT.exec(inner[0].trim()) : null;
      if (alert) {
        kind = alert[1].toLowerCase() as CalloutKind;
        inner.shift();
      }
      out.push({ type: "callout", kind, blocks: parseBlocks(inner, slug, []) });
      continue;
    }
    // table
    if (isTableStart(lines, i)) {
      const header = splitRow(lines[i]);
      const align: Align[] = splitRow(lines[i + 1]).map((c) => {
        const l = c.startsWith(":");
        const r = c.endsWith(":");
        return l && r ? "center" : r ? "right" : l ? "left" : null;
      });
      const rows: string[][] = [];
      i += 2;
      while (i < n && lines[i].trim() && lines[i].includes("|")) {
        const cells = splitRow(lines[i]);
        while (cells.length < header.length) cells.push("");
        rows.push(cells.slice(0, header.length));
        i++;
      }
      out.push({ type: "table", header, align, rows });
      continue;
    }
    // list
    if (LIST_ITEM.test(line)) {
      const [block, next] = parseList(lines, i, slug, headings);
      out.push(block);
      i = next;
      continue;
    }
    // paragraph
    const para: string[] = [line.trim()];
    i++;
    while (i < n && lines[i].trim() && !startsBlock(lines, i)) {
      para.push(lines[i].trim());
      i++;
    }
    out.push({ type: "paragraph", text: para.join(" ") });
  }
  return out;
}

function isOrderedMarker(marker: string): boolean {
  return /^\d/.test(marker);
}

function parseList(lines: string[], start: number, slug: Slugger, headings: Heading[]): [Block, number] {
  const n = lines.length;
  const first = LIST_ITEM.exec(lines[start])!;
  const baseIndent = indentOf(first[1]);
  const ordered = isOrderedMarker(first[2]);
  const startNum = ordered ? parseInt(first[2], 10) : 1;
  const items: Block[][] = [];
  let i = start;
  while (i < n) {
    const m = LIST_ITEM.exec(lines[i]);
    if (!m || indentOf(m[1]) !== baseIndent || isOrderedMarker(m[2]) !== ordered) break;
    const gap = m[3].length > 4 ? 1 : m[3].length;
    const contentIndent = baseIndent + m[2].length + gap;
    const itemLines: string[] = [m[4]];
    i++;
    while (i < n) {
      const l = lines[i];
      if (!l.trim()) {
        let j = i + 1;
        while (j < n && !lines[j].trim()) j++;
        if (j < n && indentOf(lines[j]) >= contentIndent) {
          itemLines.push("");
          i++;
          continue;
        }
        break;
      }
      if (indentOf(l) >= contentIndent) {
        itemLines.push(dedent(l, contentIndent));
        i++;
        continue;
      }
      // lazy continuation of the item's last paragraph line
      const prev = itemLines[itemLines.length - 1];
      if (prev.trim() && !startsBlock(lines, i) && !FENCE.test(prev) && !LIST_ITEM.test(prev)) {
        itemLines.push(l.trim());
        i++;
        continue;
      }
      break;
    }
    items.push(parseBlocks(itemLines, slug, headings));
    let j = i;
    while (j < n && !lines[j].trim()) j++;
    const nm = j < n ? LIST_ITEM.exec(lines[j]) : null;
    if (nm && indentOf(nm[1]) === baseIndent && isOrderedMarker(nm[2]) === ordered) {
      i = j;
      continue;
    }
    break;
  }
  return [{ type: "list", ordered, start: startNum, items }, i];
}

/** Parse a whole document: front matter, blocks, the heading outline and step groups.
 *  Every top-level ordered list is a group of steps the reader can tick off. */
export function parseDocument(src: string): ParsedDocument {
  const { meta, body } = splitFrontMatter(src);
  const headings: Heading[] = [];
  const blocks = parseBlocks(body.split("\n"), createSlugger(), headings);
  let group = 0;
  for (const b of blocks) {
    if (b.type === "list" && b.ordered) b.stepGroup = group++;
  }
  return { meta, blocks, headings, stepGroups: group };
}

// ---------------------------------------------------------------- inline

const URL_RE = /^https?:\/\/[^\s<>()[\]]*[^\s<>()[\].,;:!?'"]/;

/** Inline Markdown: `code`, **strong**, *em*, [text](href), <url>, bare http(s) URLs and \-escapes. */
export function parseInline(src: string): Inline[] {
  const out: Inline[] = [];
  let text = "";
  const flush = () => {
    if (text) out.push({ t: "text", v: text });
    text = "";
  };
  let i = 0;
  while (i < src.length) {
    const ch = src[i];
    if (ch === "\\" && i + 1 < src.length && /[\\`*_{}[\]()#+\-.!|<>~]/.test(src[i + 1])) {
      text += src[i + 1];
      i += 2;
      continue;
    }
    if (ch === "`") {
      let ticks = 1;
      while (src[i + ticks] === "`") ticks++;
      const fence = "`".repeat(ticks);
      const end = src.indexOf(fence, i + ticks);
      if (end > 0) {
        flush();
        let v = src.slice(i + ticks, end);
        if (v.startsWith(" ") && v.endsWith(" ") && v.trim()) v = v.slice(1, -1);
        out.push({ t: "code", v });
        i = end + ticks;
        continue;
      }
    }
    if (ch === "*" && src[i + 1] === "*") {
      const end = findClosing(src, i + 2, "**");
      if (end > 0) {
        flush();
        out.push({ t: "strong", c: parseInline(src.slice(i + 2, end)) });
        i = end + 2;
        continue;
      }
    }
    if (ch === "*" && src[i + 1] !== "*" && src[i + 1] && src[i + 1] !== " ") {
      const end = findClosing(src, i + 1, "*");
      if (end > 0) {
        flush();
        out.push({ t: "em", c: parseInline(src.slice(i + 1, end)) });
        i = end + 1;
        continue;
      }
    }
    if (ch === "[") {
      const close = matchBracket(src, i);
      if (close > 0 && src[close + 1] === "(") {
        const paren = src.indexOf(")", close + 2);
        if (paren > 0) {
          flush();
          const href = src.slice(close + 2, paren).trim().split(/\s+/)[0];
          out.push({ t: "link", href, c: parseInline(src.slice(i + 1, close)) });
          i = paren + 1;
          continue;
        }
      }
    }
    if (ch === "<") {
      const m = /^<(https?:\/\/[^>\s]+)>/.exec(src.slice(i));
      if (m) {
        flush();
        out.push({ t: "link", href: m[1], c: [{ t: "text", v: m[1] }] });
        i += m[0].length;
        continue;
      }
    }
    if ((ch === "h" || ch === "H") && (i === 0 || /[\s(]/.test(src[i - 1]))) {
      const m = URL_RE.exec(src.slice(i));
      if (m) {
        flush();
        out.push({ t: "link", href: m[0], c: [{ t: "text", v: m[0] }] });
        i += m[0].length;
        continue;
      }
    }
    text += ch;
    i++;
  }
  flush();
  return out;
}

function findClosing(src: string, from: number, marker: string): number {
  let i = from;
  while (i < src.length) {
    if (src[i] === "\\") {
      i += 2;
      continue;
    }
    if (src[i] === "`") {
      const end = src.indexOf("`", i + 1);
      if (end < 0) return -1;
      i = end + 1;
      continue;
    }
    if (src.startsWith(marker, i) && i > from && src[i - 1] !== " ") {
      if (marker === "*" && src[i + 1] === "*") {
        i += 2;
        continue;
      }
      return i;
    }
    i++;
  }
  return -1;
}

function matchBracket(src: string, open: number): number {
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === "\\") {
      i++;
      continue;
    }
    if (src[i] === "[") depth++;
    else if (src[i] === "]") {
      depth--;
      if (depth === 0) return i;
    }
  }
  return -1;
}

export function plainText(nodes: Inline[]): string {
  return nodes.map((n) => (n.t === "text" || n.t === "code" ? n.v : plainText(n.c))).join("");
}
