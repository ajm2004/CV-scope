import { describe, expect, it } from "vitest";
import { GUIDES, LEVELS, PAGE_ROUTES, stepCount, type Guide } from "./content";
import { classifyLink } from "./links";
import { parseInline, type Block, type Inline } from "./markdown";

function walkBlocks(blocks: Block[], visit: (text: string) => void) {
  for (const b of blocks) {
    if (b.type === "paragraph" || b.type === "heading") visit(b.text);
    else if (b.type === "list") b.items.forEach((item) => walkBlocks(item, visit));
    else if (b.type === "callout") walkBlocks(b.blocks, visit);
    else if (b.type === "table") [b.header, ...b.rows].forEach((row) => row.forEach(visit));
  }
}

function inlineNodes(g: Guide): Inline[] {
  const out: Inline[] = [];
  const collect = (nodes: Inline[]) => {
    for (const n of nodes) {
      out.push(n);
      if (n.t === "strong" || n.t === "em" || n.t === "link") collect(n.c);
    }
  };
  walkBlocks(g.blocks, (text) => collect(parseInline(text)));
  return out;
}

describe("the guides in docs/guides", () => {
  it("are twenty-six, numbered 1 to 26", () => {
    expect(GUIDES.map((g) => g.number)).toEqual(Array.from({ length: 26 }, (_, i) => i + 1));
    expect(new Set(GUIDES.map((g) => g.slug)).size).toBe(GUIDES.length);
  });

  it("each have complete front matter and at least one list of steps", () => {
    for (const g of GUIDES) {
      expect(g.title, g.slug).not.toBe(`${g.slug}.md`);
      expect(LEVELS.map((l) => l.id), g.slug).toContain(g.level);
      expect(g.time, g.slug).not.toBe("");
      expect(g.needs, g.slug).not.toBe("");
      expect(g.summary.length, g.slug).toBeGreaterThan(40);
      expect(g.learn.length, g.slug).toBeGreaterThanOrEqual(3);
      expect(g.pages.length, g.slug).toBeGreaterThan(0);
      expect(stepCount(g), g.slug).toBeGreaterThan(0);
    }
  });

  it("go from beginner to advanced in order", () => {
    const rank = (g: Guide) => LEVELS.findIndex((l) => l.id === g.level);
    for (let i = 1; i < GUIDES.length; i++) expect(rank(GUIDES[i]), GUIDES[i].slug).toBeGreaterThanOrEqual(rank(GUIDES[i - 1]));
  });

  it("only link to guides and sections that exist", () => {
    for (const g of GUIDES) {
      for (const n of inlineNodes(g)) {
        if (n.t !== "link") continue;
        const target = classifyLink(n.href);
        expect(target.kind, `${g.slug}: ${n.href}`).not.toBe("none");
        if (target.kind === "guide") {
          const other = GUIDES.find((x) => x.slug === target.slug);
          expect(other, `${g.slug}: ${n.href}`).toBeDefined();
          if (target.id) expect(other!.headings.map((h) => h.id), `${g.slug}: ${n.href}`).toContain(target.id);
        }
        if (target.kind === "anchor") expect(g.headings.map((h) => h.id), `${g.slug}: ${n.href}`).toContain(target.id);
      }
    }
  });

  it("name only real pages in their page lists", () => {
    const known = new Set([...Object.keys(PAGE_ROUTES), "Scene Builder"]);
    for (const g of GUIDES) for (const p of g.pages) expect(known.has(p), `${g.slug}: ${p}`).toBe(true);
  });
});
