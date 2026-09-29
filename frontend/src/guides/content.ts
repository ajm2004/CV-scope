/* The guides are the Markdown files in docs/guides, bundled at build time so
 * the app shows exactly what the repository contains. */

import { parseDocument, type Block, type Heading } from "./markdown";

export type Level = "Beginner" | "Intermediate" | "Advanced";
export const LEVELS: { id: Level; blurb: string }[] = [
  { id: "Beginner", blurb: "One camera or clip, one kind of drawing, results in minutes." },
  { id: "Intermediate", blurb: "Several scene objects, rules, routes and comparisons." },
  { id: "Advanced", blurb: "Accuracy, calibration, network cameras, integrations and deployment." },
];

export interface Guide {
  slug: string;
  number: number;
  title: string;
  level: Level;
  time: string;
  needs: string;
  summary: string;
  learn: string[];
  pages: string[];
  blocks: Block[];
  headings: Heading[];
  stepGroups: number;
  source: string;
}

const files = import.meta.glob("../../../docs/guides/*.md", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

function asString(v: string | string[] | undefined, fallback = ""): string {
  if (v === undefined) return fallback;
  return Array.isArray(v) ? v.join(", ") : v;
}

function asList(v: string | string[] | undefined): string[] {
  if (v === undefined) return [];
  return Array.isArray(v) ? v : v.split(",").map((s) => s.trim()).filter(Boolean);
}

export function buildGuide(path: string, source: string): Guide | null {
  const file = path.split("/").pop() ?? path;
  const m = /^(\d{2})-([\w-]+)\.md$/.exec(file);
  if (!m) return null; // README.md and other notes are not guides
  const doc = parseDocument(source);
  const level = asString(doc.meta.level, "Beginner") as Level;
  return {
    slug: file.replace(/\.md$/, ""),
    number: Number(m[1]),
    title: asString(doc.meta.title, file),
    level: LEVELS.some((l) => l.id === level) ? level : "Beginner",
    time: asString(doc.meta.time),
    needs: asString(doc.meta.needs),
    summary: asString(doc.meta.summary),
    learn: asList(doc.meta.learn),
    pages: asList(doc.meta.pages),
    blocks: doc.blocks,
    headings: doc.headings,
    stepGroups: doc.stepGroups,
    source,
  };
}

export const GUIDES: Guide[] = Object.entries(files)
  .map(([path, src]) => buildGuide(path, src))
  .filter((g): g is Guide => g !== null)
  .sort((a, b) => a.number - b.number);

export function guideBySlug(slug: string | undefined | null): Guide | undefined {
  return GUIDES.find((g) => g.slug === slug);
}

/** App pages a guide can link to by name (bold page names in the text become links). */
export const PAGE_ROUTES: Record<string, string> = {
  Projects: "/projects",
  Live: "/live",
  Experiments: "/experiments",
  Data: "/data",
  Analysis: "/analysis",
  Cameras: "/cameras",
  Models: "/models",
  Hardware: "/hardware",
  Settings: "/settings",
  Guides: "/guides",
  Anomalies: "/anomalies",
  "Anomaly Assistant": "/anomalies/assistant",
  // Relationship & Event Correlation Engine
  Relationships: "/relationships",
  "Relationship timeline": "/relationships/timeline",
  "Relationship search": "/relationships/search",
  "Relationship rules": "/relationships/rules",
  "Relationship settings": "/relationships/settings",
  "Relationship graph": "/relationships/graph",
  Journeys: "/relationships/journeys",
  // Location Engine
  "Site view": "/locations/site",
  Topology: "/locations/topology",
  // Licensed recognition modules
  Recognition: "/recognition/settings",
  People: "/recognition/people",
  Vehicles: "/recognition/vehicles",
  "Recognition events": "/recognition/events",
  "Test recognition": "/recognition/test",
};

/** Count of steps in a guide: items of its top-level numbered lists. */
export function stepCount(g: Guide): number {
  return g.blocks.reduce((n, b) => n + (b.type === "list" && b.ordered ? b.items.length : 0), 0);
}
