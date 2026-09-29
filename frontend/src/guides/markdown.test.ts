import { describe, expect, it } from "vitest";
import { classifyLink } from "./links";
import { createSlugger, parseDocument, parseInline, plainText, splitFrontMatter, type Block } from "./markdown";

describe("front matter", () => {
  it("reads scalars, inline lists and block lists", () => {
    const { meta, body } = splitFrontMatter("---\ntitle: Count a line\npages: [Cameras, \"Scene Builder\"]\nlearn:\n  - Draw a line\n  - Read counts\n---\n\n# Hello\n");
    expect(meta.title).toBe("Count a line");
    expect(meta.pages).toEqual(["Cameras", "Scene Builder"]);
    expect(meta.learn).toEqual(["Draw a line", "Read counts"]);
    expect(body.trim()).toBe("# Hello");
  });

  it("leaves documents without front matter alone", () => {
    expect(splitFrontMatter("# Title\ntext").meta).toEqual({});
  });
});

describe("headings", () => {
  it("use GitHub anchor ids, numbering duplicates", () => {
    const slug = createSlugger();
    expect(slug("Step 1. Add the corridor video")).toBe("step-1-add-the-corridor-video");
    expect(slug("Routes or sequence rules")).toBe("routes-or-sequence-rules");
    expect(slug("Routes or sequence rules")).toBe("routes-or-sequence-rules-1");
    expect(slug("What `wall_time` means?")).toBe("what-wall_time-means");
  });
});

describe("blocks", () => {
  const doc = parseDocument(
    [
      "# Title",
      "",
      "Intro text that wraps",
      "over two lines.",
      "",
      "## Step 1. Do it",
      "",
      "1. First step:",
      "",
      "   ```",
      "   run this",
      "   ```",
      "",
      "2. Second step with fields:",
      "   * **Name:** `Desk`.",
      "   * **Time:** 5 seconds. A long bullet",
      "     that wraps.",
      "",
      "   Double-click to finish.",
      "3. Third step",
      "",
      "| Column | Meaning |",
      "| --- | ---: |",
      "| **Total** | All crossings |",
      "",
      "> [!TIP]",
      "> A tip with **bold** text.",
      "",
      "* Bullet",
      "",
      "1. Another numbered list",
    ].join("\n"),
  );

  it("parses paragraphs, headings and the outline", () => {
    expect(doc.blocks[0]).toMatchObject({ type: "heading", level: 1, id: "title" });
    expect(doc.blocks[1]).toEqual({ type: "paragraph", text: "Intro text that wraps over two lines." });
    expect(doc.headings.map((h) => h.id)).toEqual(["title", "step-1-do-it"]);
  });

  it("keeps code, nested lists and later paragraphs inside list items", () => {
    const list = doc.blocks[3] as Extract<Block, { type: "list" }>;
    expect(list.type).toBe("list");
    expect(list.ordered).toBe(true);
    expect(list.items).toHaveLength(3);
    expect(list.items[0][1]).toEqual({ type: "code", lang: "", text: "run this" });
    const second = list.items[1];
    expect(second[0]).toEqual({ type: "paragraph", text: "Second step with fields:" });
    const nested = second[1] as Extract<Block, { type: "list" }>;
    expect(nested.ordered).toBe(false);
    expect(nested.items[1][0]).toEqual({ type: "paragraph", text: "**Time:** 5 seconds. A long bullet that wraps." });
    expect(second[2]).toEqual({ type: "paragraph", text: "Double-click to finish." });
  });

  it("parses tables with alignment and GitHub alerts", () => {
    expect(doc.blocks[4]).toEqual({ type: "table", header: ["Column", "Meaning"], align: [null, "right"], rows: [["**Total**", "All crossings"]] });
    expect(doc.blocks[5]).toMatchObject({ type: "callout", kind: "tip" });
  });

  it("numbers the top-level numbered lists as step groups", () => {
    const ordered = doc.blocks.filter((b) => b.type === "list" && b.ordered) as Extract<Block, { type: "list" }>[];
    expect(ordered.map((l) => l.stepGroup)).toEqual([0, 1]);
    expect(doc.stepGroups).toBe(2);
  });

  it("continues numbering after a table inside a procedure", () => {
    const d = parseDocument("1. One\n2. Two\n\n| a | b |\n| - | - |\n| 1 | 2 |\n\n3. Three\n");
    const lists = d.blocks.filter((b) => b.type === "list") as Extract<Block, { type: "list" }>[];
    expect(lists.map((l) => [l.start, l.items.length])).toEqual([
      [1, 2],
      [3, 1],
    ]);
  });
});

describe("inline", () => {
  it("parses code, strong, emphasis, links and bare URLs", () => {
    const nodes = parseInline("Open **Cameras**, type `C:\\videos` and see [guide 02](02-count-a-line.md) or http://127.0.0.1:8420. *Done*");
    expect(nodes.map((n) => n.t)).toEqual(["text", "strong", "text", "code", "text", "link", "text", "link", "text", "em"]);
    const url = nodes[7] as { t: "link"; href: string };
    expect(url.href).toBe("http://127.0.0.1:8420");
    expect(plainText(nodes)).toContain("guide 02");
  });

  it("keeps a lone asterisk and escapes as text", () => {
    expect(plainText(parseInline("5 * 3 and \\*not em\\*"))).toBe("5 * 3 and *not em*");
  });
});

describe("links", () => {
  it("routes guide links, anchors and outside links", () => {
    expect(classifyLink("02-count-a-line.md#step-1-add-the-corridor-video")).toEqual({ kind: "guide", slug: "02-count-a-line", id: "step-1-add-the-corridor-video" });
    expect(classifyLink("#troubleshooting")).toEqual({ kind: "anchor", id: "troubleshooting" });
    expect(classifyLink("README.md")).toEqual({ kind: "index" });
    expect(classifyLink("https://example.org")).toEqual({ kind: "external", href: "https://example.org" });
    expect(classifyLink("/cameras")).toEqual({ kind: "app", to: "/cameras" });
    expect(classifyLink("../privacy.md")).toEqual({ kind: "none" });
  });
});
