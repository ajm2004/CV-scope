import { describe, expect, it } from "vitest";
import type { VEdge, VGraph, VNode } from "./api";
import { bfsPath, changeTimes, collapse, edgeVisible, eventsNear, layout, merge, NATURES, visible, type ViewFilters } from "./graphModel";

function node(key: string, klass: VNode["klass"] = "track"): VNode {
  return { id: 1, key, node: key, type: "person_track", type_label: "Person track", category: "track", sensitive: false, label: key, redacted: false, klass, expandable: true };
}

function edge(source: string, target: string, type: string, start: string, end: string | null, nature: VEdge["nature"] = "inferred", state: VEdge["state"] = "likely", camera = 1): VEdge {
  return {
    id: `${source}>${target}>${type}`, source, target, type, label: type.toLowerCase(), nature, sensor: false, derived: nature === "context", count: 1, best_confidence: 0.8, state, ids: [1], merged: false,
    intervals: [{ id: 1, start, end, start_media_s: null, end_media_s: null, state, confidence: 0.8, run_id: 1, camera_id: camera }], first_at: start, last_at: end ?? start,
  };
}

const T = (m: number) => new Date(Date.UTC(2026, 8, 23, 14, m)).toISOString();

const G: VGraph = {
  center: "p",
  nodes: [node("p", "identity"), node("v"), node("z", "place"), node("cam", "camera")],
  edges: [
    edge("v", "z", "APPEARED_IN", T(20), T(20), "observed"),
    edge("p", "v", "APPROACHED", T(22), T(22)),
    edge("p", "z", "ENTERED", T(21), T(21), "observed", "confirmed"),
    edge("p", "cam", "SEEN_AT", T(21), T(23), "context", "confirmed"),
  ],
  time_range: { start: T(20), end: T(23) },
  counts: {},
  projected: true,
  truncated: false,
};

const ALL: ViewFilters = { natures: new Set(NATURES), types: null, minState: "insufficient", cameraIds: null, time: { kind: "all" } };

describe("graph model", () => {
  it("shows a snapshot and a replay of how the graph grew", () => {
    const at = (m: number, kind: "snapshot" | "evolution") =>
      visible(G, { ...ALL, time: kind === "snapshot" ? { kind, t: Date.parse(T(m)), afterglow: 30_000 } : { kind, t: Date.parse(T(m)) } }).edges.map((e) => e.type).sort();
    expect(at(21, "evolution")).toEqual(["APPEARED_IN", "ENTERED", "SEEN_AT"]);
    expect(at(22, "snapshot")).toEqual(["APPROACHED", "SEEN_AT"]);
    expect(at(19, "evolution")).toEqual([]);
    expect(changeTimes(G).length).toBe(4);
    expect(eventsNear(G, Date.parse(T(22)), 45_000).map((x) => x.edge.type)).toEqual(["APPROACHED"]);
  });

  it("filters by nature, confidence and camera", () => {
    expect(edgeVisible(G.edges[1], { ...ALL, natures: new Set(["observed"]) })).toBe(false);
    expect(visible(G, { ...ALL, minState: "confirmed" }).edges.map((e) => e.type).sort()).toEqual(["ENTERED", "SEEN_AT"]);
    expect(visible(G, { ...ALL, cameraIds: new Set([2]) }).edges).toEqual([]);
    // context edges only hang off nodes shown for another reason
    expect(visible(G, { ...ALL, natures: new Set(["context"]) }).edges.map((e) => e.type)).toEqual(["SEEN_AT"]);
  });

  it("merges an expansion and collapses it again", () => {
    const more: VGraph = { ...G, center: "v", nodes: [node("v"), node("w")], edges: [edge("v", "w", "NEAR", T(25), T(26))], time_range: { start: T(25), end: T(26) } };
    let m = merge({ graph: G, addedBy: {} }, more, "v");
    expect(m.graph.nodes.map((n) => n.node)).toContain("w");
    expect(m.graph.time_range.end).toBe(T(26));
    m = merge(m, { ...more, edges: [edge("v", "w", "NEAR", T(27), T(28))] }, "v");
    expect(m.graph.edges.find((e) => e.type === "NEAR")!.intervals.length).toBe(1); // same relationship id, not duplicated
    const c = collapse(m, "v");
    expect(c.graph.nodes.map((n) => n.node)).not.toContain("w");
    expect(c.graph.edges.some((e) => e.type === "NEAR")).toBe(false);
  });

  it("finds a path and lays out deterministically, keeping placed nodes still", () => {
    expect(bfsPath(G.nodes, G.edges, "v", "cam")!.nodes).toEqual(["v", "p", "cam"]);
    expect(bfsPath(G.nodes, G.edges, "v", "nowhere")).toBeNull();
    const a = layout(G.nodes, G.edges, {}, new Set(), "p");
    const b = layout(G.nodes, G.edges, {}, new Set(), "p");
    expect(a).toEqual(b);
    const withNew = layout([...G.nodes, node("x")], [...G.edges, edge("x", "p", "NEAR", T(1), T(2))], a, new Set(["v"]), "p");
    expect(withNew.v).toEqual(a.v); // pinned
    expect(Math.hypot(withNew.z.x - a.z.x, withNew.z.y - a.z.y)).toBeLessThan(60);
  });
});
