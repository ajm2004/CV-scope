/* The graph view's model: merging expansions, collapsing them again, what is
 * visible for the chosen filters and time, a stable force layout, and paths.
 * Pure functions (tested without a browser). The graph is a view of the
 * stored relationships: nothing here creates or changes one. */

import type { StateName } from "../relationships/api";
import type { EdgeNature, VEdge, VGraph, VInterval, VNode } from "./api";

export const STATE_RANK: Record<StateName, number> = { insufficient: 0, possible: 1, likely: 2, confirmed: 3 };
export const NATURES: EdgeNature[] = ["observed", "identity", "inferred", "cross_camera", "external", "context"];

export type TimeMode =
  | { kind: "all" }
  | { kind: "snapshot"; t: number; afterglow: number }
  | { kind: "range"; from: number; to: number }
  | { kind: "evolution"; t: number };

export interface ViewFilters {
  natures: Set<EdgeNature>;
  types: Set<string> | null; // null = every type
  minState: StateName;
  cameraIds: Set<number> | null;
  time: TimeMode;
  sensorOnly?: boolean;
}

export interface Model {
  graph: VGraph;
  addedBy: Record<string, string>; // node -> the node whose expansion brought it
}

function ms(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const v = Date.parse(iso);
  return Number.isNaN(v) ? null : v;
}

// ---------------------------------------------------------------- merge / collapse
function mergeEdge(a: VEdge, b: VEdge): VEdge {
  const ids = [...new Set([...a.ids, ...b.ids])];
  // one interval per stored relationship: a newer answer replaces the older (an open relationship grows)
  const byKey = new Map<string, VInterval>();
  for (const i of [...a.intervals, ...b.intervals]) byKey.set(i.id != null ? `r${i.id}` : `t${i.start}`, i);
  const intervals = [...byKey.values()];
  const best = b.best_confidence > a.best_confidence ? b : a;
  const first = [a.first_at, b.first_at].filter(Boolean).sort()[0] ?? null;
  const last = [a.last_at, b.last_at].filter(Boolean).sort().reverse()[0] ?? null;
  return { ...a, ids, intervals, count: Math.max(a.count, b.count, ids.length || 0), best_confidence: best.best_confidence, state: best.state, first_at: first, last_at: last, sensor: a.sensor || b.sensor };
}

export function merge(model: Model | null, add: VGraph, expander?: string): Model {
  if (!model) return { graph: add, addedBy: {} };
  const nodes = new Map(model.graph.nodes.map((n) => [n.node, n]));
  const addedBy = { ...model.addedBy };
  for (const n of add.nodes) {
    if (!nodes.has(n.node)) {
      nodes.set(n.node, n);
      if (expander) addedBy[n.node] = expander;
    }
  }
  const edges = new Map(model.graph.edges.map((e) => [e.id, e]));
  for (const e of add.edges) {
    const cur = edges.get(e.id);
    edges.set(e.id, cur ? mergeEdge(cur, e) : e);
  }
  const starts = [model.graph.time_range.start, add.time_range.start].filter(Boolean).sort();
  const ends = [model.graph.time_range.end, add.time_range.end].filter(Boolean).sort();
  return {
    graph: { ...model.graph, nodes: [...nodes.values()], edges: [...edges.values()], time_range: { start: starts[0] ?? null, end: ends[ends.length - 1] ?? null }, truncated: model.graph.truncated || add.truncated },
    addedBy,
  };
}

/** Remove what expanding ``origin`` added (and what expanding those added). */
export function collapse(model: Model, origin: string): Model {
  const remove = new Set<string>();
  let frontier = [origin];
  while (frontier.length) {
    const next: string[] = [];
    for (const [n, by] of Object.entries(model.addedBy)) {
      if (frontier.includes(by) && !remove.has(n) && n !== model.graph.center) {
        remove.add(n);
        next.push(n);
      }
    }
    frontier = next;
  }
  const addedBy = Object.fromEntries(Object.entries(model.addedBy).filter(([n]) => !remove.has(n)));
  return {
    graph: { ...model.graph, nodes: model.graph.nodes.filter((n) => !remove.has(n.node)), edges: model.graph.edges.filter((e) => !remove.has(e.source) && !remove.has(e.target)) },
    addedBy,
  };
}

export function expandedBy(model: Model, origin: string): boolean {
  return Object.values(model.addedBy).includes(origin);
}

// ---------------------------------------------------------------- visibility
export function intervalActive(i: VInterval, time: TimeMode): boolean {
  if (time.kind === "all") return true;
  const s = ms(i.start);
  if (s == null) return true; // timeless (derived context)
  const e = ms(i.end) ?? s;
  if (time.kind === "evolution") return s <= time.t;
  if (time.kind === "range") return s <= time.to && Math.max(e, s) >= time.from;
  return s <= time.t && Math.max(e, s + time.afterglow) >= time.t;
}

function intervalPasses(i: VInterval, f: ViewFilters): boolean {
  if (STATE_RANK[i.state] < STATE_RANK[f.minState]) return false;
  if (f.cameraIds && i.camera_id != null && !f.cameraIds.has(i.camera_id)) return false;
  return intervalActive(i, f.time);
}

export function edgeVisible(e: VEdge, f: ViewFilters): boolean {
  if (!f.natures.has(e.nature)) return false;
  if (f.types && !f.types.has(e.type)) return false;
  if (f.sensorOnly && !e.sensor) return false;
  if (!e.intervals.length) return STATE_RANK[e.state] >= STATE_RANK[f.minState];
  return e.intervals.some((i) => intervalPasses(i, f));
}

/** The nodes and edges to draw. Context edges only where both ends are otherwise shown. */
export function visible(g: VGraph, f: ViewFilters, keep: Set<string> = new Set()): { nodes: VNode[]; edges: VEdge[] } {
  const primary = g.edges.filter((e) => e.nature !== "context" && edgeVisible(e, f));
  const shown = new Set<string>(keep);
  if (g.center) shown.add(g.center);
  for (const e of primary) {
    shown.add(e.source);
    shown.add(e.target);
  }
  // context: SEEN_AT / INSIDE hang off shown nodes, and may add the camera or location they point to
  const context = f.natures.has("context") ? g.edges.filter((e) => e.nature === "context" && shown.has(e.source) && edgeVisible(e, f)) : [];
  for (const e of context) shown.add(e.target);
  // a second hop of INSIDE (camera -> its area) once the camera is shown
  const more = f.natures.has("context") ? g.edges.filter((e) => e.nature === "context" && !context.includes(e) && shown.has(e.source) && e.type === "INSIDE") : [];
  for (const e of more) shown.add(e.target);
  return { nodes: g.nodes.filter((n) => shown.has(n.node)), edges: [...primary, ...context, ...more] };
}

/** Times at which the graph changes (for stepping through a replay). */
export function changeTimes(g: VGraph): number[] {
  const out = new Set<number>();
  for (const e of g.edges) {
    for (const i of e.intervals) {
      const s = ms(i.start);
      if (s != null) out.add(s);
      const en = ms(i.end);
      if (en != null) out.add(en);
    }
  }
  return [...out].sort((a, b) => a - b);
}

export function timeBounds(g: VGraph): [number, number] | null {
  const t = changeTimes(g);
  if (!t.length) return null;
  return [t[0], t[t.length - 1]];
}

/** What happened at (or just before) a moment, newest first (the replay's caption). */
export function eventsNear(g: VGraph, t: number, windowMs = 60_000): { edge: VEdge; interval: VInterval; at: number }[] {
  const out: { edge: VEdge; interval: VInterval; at: number }[] = [];
  for (const e of g.edges) {
    if (e.nature === "context") continue;
    for (const i of e.intervals) {
      const s = ms(i.start);
      if (s != null && s <= t && s > t - windowMs) out.push({ edge: e, interval: i, at: s });
    }
  }
  return out.sort((a, b) => b.at - a.at);
}

// ---------------------------------------------------------------- paths
export function bfsPath(nodes: { node: string }[], edges: VEdge[], from: string, to: string): { nodes: string[]; edges: string[] } | null {
  if (from === to) return { nodes: [from], edges: [] };
  const adj = new Map<string, { n: string; e: string }[]>();
  for (const e of edges) {
    if (!adj.has(e.source)) adj.set(e.source, []);
    if (!adj.has(e.target)) adj.set(e.target, []);
    adj.get(e.source)!.push({ n: e.target, e: e.id });
    adj.get(e.target)!.push({ n: e.source, e: e.id });
  }
  const known = new Set(nodes.map((n) => n.node));
  if (!known.has(from) || !known.has(to)) return null;
  const prev = new Map<string, { n: string; e: string } | null>([[from, null]]);
  const q = [from];
  while (q.length) {
    const cur = q.shift()!;
    if (cur === to) break;
    for (const nx of adj.get(cur) ?? []) {
      if (!prev.has(nx.n)) {
        prev.set(nx.n, { n: cur, e: nx.e });
        q.push(nx.n);
      }
    }
  }
  if (!prev.has(to)) return null;
  const outN: string[] = [];
  const outE: string[] = [];
  let cur: string | undefined = to;
  while (cur) {
    outN.push(cur);
    const p = prev.get(cur);
    if (!p) break;
    outE.push(p.e);
    cur = p.n;
  }
  return { nodes: outN.reverse(), edges: outE.reverse() };
}

// ---------------------------------------------------------------- layout
export type Pos = { x: number; y: number };

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967295;
}

/** A deterministic force layout. Nodes placed before move little, so expanding
 * a node does not rearrange the picture; ``pinned`` nodes (dragged by the user) never move. */
export function layout(nodes: { node: string }[], edges: { source: string; target: string }[], prev: Record<string, Pos>, pinned: Set<string> = new Set(), center?: string | null): Record<string, Pos> {
  const n = nodes.length;
  const pos: Record<string, Pos> = {};
  const nb = new Map<string, string[]>();
  for (const e of edges) {
    if (!nb.has(e.source)) nb.set(e.source, []);
    if (!nb.has(e.target)) nb.set(e.target, []);
    nb.get(e.source)!.push(e.target);
    nb.get(e.target)!.push(e.source);
  }
  const k = 90;
  for (const v of nodes) {
    if (prev[v.node]) {
      pos[v.node] = { ...prev[v.node] };
      continue;
    }
    const anchor = (nb.get(v.node) ?? []).map((m) => prev[m]).find(Boolean);
    const a = hash(v.node) * Math.PI * 2;
    if (anchor) pos[v.node] = { x: anchor.x + Math.cos(a) * k, y: anchor.y + Math.sin(a) * k };
    else if (center && v.node === center) pos[v.node] = { x: 0, y: 0 };
    else {
      const r = k * (1.5 + hash(v.node + "r") * Math.sqrt(n));
      pos[v.node] = { x: Math.cos(a) * r, y: Math.sin(a) * r };
    }
  }
  const ids = nodes.map((v) => v.node);
  const iters = n > 250 ? 90 : n > 120 ? 160 : 260;
  let temp = k * 1.5;
  for (let it = 0; it < iters; it++) {
    const disp: Record<string, Pos> = {};
    for (const a of ids) disp[a] = { x: 0, y: 0 };
    for (let i = 0; i < ids.length; i++) {
      const pa = pos[ids[i]];
      for (let j = i + 1; j < ids.length; j++) {
        const pb = pos[ids[j]];
        let dx = pa.x - pb.x;
        let dy = pa.y - pb.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 0.01) {
          dx = (hash(ids[i] + ids[j]) - 0.5) * 2;
          dy = (hash(ids[j] + ids[i]) - 0.5) * 2;
          d2 = dx * dx + dy * dy + 0.01;
        }
        if (d2 > 9 * k * k * 16) continue;
        const f = (k * k) / d2;
        disp[ids[i]].x += dx * f;
        disp[ids[i]].y += dy * f;
        disp[ids[j]].x -= dx * f;
        disp[ids[j]].y -= dy * f;
      }
    }
    for (const e of edges) {
      const pa = pos[e.source];
      const pb = pos[e.target];
      if (!pa || !pb) continue;
      const dx = pa.x - pb.x;
      const dy = pa.y - pb.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const f = d / k;
      disp[e.source].x -= dx * f * 0.5;
      disp[e.source].y -= dy * f * 0.5;
      disp[e.target].x += dx * f * 0.5;
      disp[e.target].y += dy * f * 0.5;
    }
    for (const a of ids) {
      if (pinned.has(a) || (center && a === center && !prev[a])) continue;
      const damp = prev[a] ? 0.12 : 1;
      const d = disp[a];
      const len = Math.sqrt(d.x * d.x + d.y * d.y) || 1;
      const step = Math.min(len, temp) * damp;
      pos[a].x += (d.x / len) * step;
      pos[a].y += (d.y / len) * step;
      // mild gravity keeps separate components on screen
      pos[a].x *= 0.998;
      pos[a].y *= 0.998;
    }
    temp = Math.max(2, temp * 0.97);
  }
  return pos;
}
