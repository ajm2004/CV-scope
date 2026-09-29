/* The graph investigation workbench: filters, the interactive canvas with its
 * time bar, and an inspector for the selected node or edge (expand/collapse,
 * paths, the evidence behind a relationship, a jump to the video). */

import { useMemo, useState } from "react";
import { Link } from "react-router";
import { Empty, ErrorNotice, Field, Panel, Pill } from "../components/ui";
import { dateTime } from "../lib/format";
import type { StateName } from "../relationships/api";
import { mediaClock, StatePill, VideoLink } from "../relationships/bits";
import Evidence from "../relationships/Evidence";
import { loc, type EdgeNature, type VEdge, type VGraph, type VNode } from "./api";
import GraphCanvas, { GraphLegend, NATURE_LABEL } from "./GraphCanvas";
import { changeTimes, eventsNear, expandedBy, NATURES, timeBounds, visible, type ViewFilters } from "./graphModel";
import TimeBar, { useTimeMode } from "./TimeBar";
import type { useGraph } from "./useGraph";

const NATURE_CSS: Record<EdgeNature, string> = { observed: "g-observed", identity: "g-identity", inferred: "g-inferred", cross_camera: "g-cross", external: "g-external", context: "g-context" };
const JOURNEY_TYPES = new Set(["person_track", "vehicle_track", "object_track", "recognized_person", "license_plate", "registered_vehicle"]);

export interface WorkbenchProps {
  g: ReturnType<typeof useGraph>;
  serverParams: Record<string, unknown>;
  onRecenter?: (key: string) => void;
  height?: number;
  highlight?: { nodes: Set<string>; edges: Set<string> };
  onSelectEdge?: (e: VEdge | null) => void;
  onSelectNode?: (n: VNode | null) => void;
}

export default function GraphWorkbench({ g, serverParams, onRecenter, height = 600, highlight, onSelectEdge, onSelectNode }: WorkbenchProps) {
  const graph = g.model?.graph ?? null;
  const [natures, setNatures] = useState<Set<EdgeNature>>(new Set(NATURES));
  const [types, setTypes] = useState<Set<string> | null>(null);
  const [minState, setMinState] = useState<StateName>("possible");
  const [cameras, setCameras] = useState<Set<number> | null>(null);
  const [sensorOnly, setSensorOnly] = useState(false);
  const [selNode, setSelNode] = useState<string | null>(null);
  const [selEdge, setSelEdge] = useState<string | null>(null);
  const [pathFrom, setPathFrom] = useState<string | null>(null);
  const [pathTo, setPathTo] = useState<string | null>(null);
  const [path, setPath] = useState<{ nodes: Set<string>; edges: Set<string>; found: boolean } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [evidenceId, setEvidenceId] = useState<number | null>(null);

  const bounds = useMemo(() => (graph ? timeBounds(graph) : null), [graph]);
  const steps = useMemo(() => (graph ? changeTimes(graph) : []), [graph]);
  const time = useTimeMode(bounds);
  const filters: ViewFilters = { natures, types, minState, cameraIds: cameras, time: time.mode, sensorOnly };
  const keep = useMemo(() => new Set([selNode, pathFrom, pathTo, ...(path?.nodes ?? [])].filter(Boolean) as string[]), [selNode, pathFrom, pathTo, path]);
  const shown = useMemo(() => (graph ? visible(graph, filters, keep) : { nodes: [], edges: [] }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [graph, natures, types, minState, cameras, sensorOnly, time.mode.kind, (time.mode as { t?: number }).t, (time.mode as { from?: number }).from, (time.mode as { to?: number }).to, keep]);

  const typeCounts = useMemo(() => {
    const out = new Map<string, number>();
    for (const e of graph?.edges ?? []) if (e.nature !== "context") out.set(e.type, (out.get(e.type) ?? 0) + e.count);
    return [...out.entries()].sort((a, b) => b[1] - a[1]);
  }, [graph]);
  const cameraNames = useMemo(() => {
    const ids = new Set<number>();
    for (const e of graph?.edges ?? []) for (const i of e.intervals) if (i.camera_id != null) ids.add(i.camera_id);
    const names = new Map<number, string>();
    for (const n of graph?.nodes ?? []) if (n.klass === "camera" && n.key) names.set(Number(n.key.split(":")[1]), n.label);
    return [...ids].sort((a, b) => a - b).map((id) => ({ id, name: names.get(id) ?? `Camera ${id}` }));
  }, [graph]);

  const node = graph?.nodes.find((n) => n.node === selNode) ?? null;
  const edge = graph?.edges.find((e) => e.id === selEdge) ?? null;
  const hlNodes = highlight?.nodes.size ? highlight.nodes : path?.nodes;
  const hlEdges = highlight?.edges.size ? highlight.edges : path?.edges;

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };
  const expand = (key: string) =>
    run("Expanding…", async () => {
      const add: VGraph = await loc.visual({ ...serverParams, key, depth: 1 });
      g.add({ ...add, center: graph?.center ?? add.center }, key);
    });
  const findPath = (a: string, b: string) =>
    run("Searching for a path…", async () => {
      const p = await loc.path({ ...serverParams, from_key: a, to_key: b, max_depth: 5 } as never);
      if (p.found) g.add({ ...p, center: graph?.center ?? null });
      setPath({ nodes: new Set(p.path_nodes), edges: new Set(p.path_edges), found: p.found });
    });

  const selectNode = (k: string | null) => {
    setSelNode(k);
    setSelEdge(null);
    setEvidenceId(null);
    onSelectNode?.(graph?.nodes.find((n) => n.node === k) ?? null);
  };
  const selectEdge = (e: VEdge | null) => {
    setSelEdge(e?.id ?? null);
    setSelNode(null);
    setEvidenceId(e?.ids[e.ids.length - 1] ?? null);
    onSelectEdge?.(e);
  };

  const t = time.mode.kind === "snapshot" || time.mode.kind === "evolution" ? time.mode.t : null;
  const caption = graph && t != null ? eventsNear(graph, t, 90_000).slice(0, 3).map((x) => {
    const a = graph.nodes.find((n) => n.node === x.edge.source)?.label;
    const b = graph.nodes.find((n) => n.node === x.edge.target)?.label;
    return `${a} ${x.edge.label} ${b}`;
  }).join(" · ") : null;

  return (
    <div className="g-layout">
      <div className="stack">
        <Panel title="Show">
          <div className="stack" style={{ gap: 10 }}>
            <div>
              <div className="section-title">Kinds of edge</div>
              <div className="g-filter-list">
                {NATURES.map((n) => (
                  <label key={n}>
                    <input type="checkbox" checked={natures.has(n)} onChange={(e) => { const s = new Set(natures); if (e.target.checked) s.add(n); else s.delete(n); setNatures(s); }} />
                    <span className={`g-swatch ${NATURE_CSS[n]}`} /> {NATURE_LABEL[n]} <span className="hint">{graph?.counts[n] ?? 0}</span>
                  </label>
                ))}
                <label>
                  <input type="checkbox" checked={sensorOnly} onChange={(e) => setSensorOnly(e.target.checked)} /> Only sensor-supported
                </label>
              </div>
            </div>
            <Field label="At least">
              <select value={minState} onChange={(e) => setMinState(e.target.value as StateName)}>
                <option value="confirmed">Confirmed</option>
                <option value="likely">Likely</option>
                <option value="possible">Possible</option>
                <option value="insufficient">Everything (incl. insufficient)</option>
              </select>
            </Field>
            {typeCounts.length > 0 && (
              <div>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <span className="section-title">Relationship types</span>
                  {types && <button className="linklike" onClick={() => setTypes(null)}>all</button>}
                </div>
                <div className="g-filter-list">
                  {typeCounts.map(([ty, n]) => (
                    <label key={ty}>
                      <input type="checkbox" checked={!types || types.has(ty)} onChange={(e) => { const s = new Set(types ?? typeCounts.map((x) => x[0])); if (e.target.checked) s.add(ty); else s.delete(ty); setTypes(s); }} />
                      <span className="mono small">{ty}</span> <span className="hint">{n}</span>
                    </label>
                  ))}
                </div>
              </div>
            )}
            {cameraNames.length > 1 && (
              <div>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <span className="section-title">Cameras</span>
                  {cameras && <button className="linklike" onClick={() => setCameras(null)}>all</button>}
                </div>
                <div className="g-filter-list">
                  {cameraNames.map((c) => (
                    <label key={c.id}>
                      <input type="checkbox" checked={!cameras || cameras.has(c.id)} onChange={(e) => { const s = new Set(cameras ?? cameraNames.map((x) => x.id)); if (e.target.checked) s.add(c.id); else s.delete(c.id); setCameras(s); }} />
                      {c.name}
                    </label>
                  ))}
                </div>
              </div>
            )}
          </div>
        </Panel>
        <Panel title="Path between two entities">
          <div className="stack" style={{ gap: 6 }}>
            <div className="small">From: {pathFrom ? <strong>{graph?.nodes.find((n) => n.node === pathFrom)?.label ?? pathFrom}</strong> : <span className="hint">select a node, then “Path from here”</span>}</div>
            <div className="small">To: {pathTo ? <strong>{graph?.nodes.find((n) => n.node === pathTo)?.label ?? pathTo}</strong> : <span className="hint">…and “Path to here”</span>}</div>
            {path && !path.found && <div className="hint">No chain of at most 5 relationships connects them (with these filters).</div>}
            {path?.found && <div className="hint">{path.edges.size} relationship{path.edges.size === 1 ? "" : "s"} on the path (highlighted).</div>}
            {(pathFrom || pathTo || path) && (
              <button className="btn sm ghost" onClick={() => { setPathFrom(null); setPathTo(null); setPath(null); }}>
                Clear path
              </button>
            )}
          </div>
        </Panel>
      </div>
      <div className="stack" style={{ minWidth: 0, gap: 0 }}>
        {busy && <div className="hint" style={{ padding: "0 0 4px" }}>{busy}</div>}
        <ErrorNotice error={error} />
        {graph && shown.nodes.length === 0 ? (
          <Empty>Nothing matches these filters{time.kind !== "all" ? " at this time" : ""}.</Empty>
        ) : (
          <GraphCanvas nodes={shown.nodes} edges={shown.edges} positions={g.positions} center={graph?.center} selectedNode={selNode} selectedEdge={selEdge}
            highlightNodes={hlNodes} highlightEdges={hlEdges} height={height} onSelectNode={selectNode} onSelectEdge={selectEdge} onMoveNode={g.move} onExpandNode={expand} />
        )}
        <TimeBar bounds={bounds} steps={steps} state={time} caption={caption} />
        <div style={{ padding: "8px 2px" }}>
          <GraphLegend />
          <div className="hint" style={{ marginTop: 4 }}>
            Drag the background to pan, the wheel to zoom, a node to pin it. Double-click a node to expand it. {graph?.truncated && <strong>The graph was cut at its edge limit: narrow the scope or filters.</strong>}{" "}
            <button className="linklike" onClick={g.relayout}>Re-arrange</button>
          </div>
        </div>
      </div>
      <div className="stack g-side-right">
        {!node && !edge && <Panel title="Inspector"><Empty>Select a node or an edge.</Empty></Panel>}
        {node && (
          <NodeInspector n={node} graph={graph!} visibleEdges={shown.edges} expanded={!!g.model && expandedBy(g.model, node.node)}
            onExpand={() => expand(node.node)} onCollapse={() => g.collapseNode(node.node)} onRecenter={onRecenter}
            onPathFrom={() => { setPathFrom(node.node); setPath(null); if (pathTo && pathTo !== node.node) void findPath(node.node, pathTo); }}
            onPathTo={() => { setPathTo(node.node); setPath(null); if (pathFrom && pathFrom !== node.node) void findPath(pathFrom, node.node); }}
            onSelectEdge={selectEdge} />
        )}
        {edge && <EdgeInspector e={edge} graph={graph!} onEvidence={setEvidenceId} evidenceId={evidenceId} />}
        {edge && evidenceId != null && <Evidence target={{ kind: "relationship", id: evidenceId }} onClose={() => setEvidenceId(null)} />}
      </div>
    </div>
  );
}

function NodeInspector({ n, graph, visibleEdges, expanded, onExpand, onCollapse, onRecenter, onPathFrom, onPathTo, onSelectEdge }: {
  n: VNode; graph: VGraph; visibleEdges: VEdge[]; expanded: boolean; onExpand: () => void; onCollapse: () => void; onRecenter?: (key: string) => void;
  onPathFrom: () => void; onPathTo: () => void; onSelectEdge: (e: VEdge) => void;
}) {
  const mine = visibleEdges.filter((e) => e.source === n.node || e.target === n.node);
  const label = (k: string) => graph.nodes.find((x) => x.node === k)?.label ?? k;
  return (
    <Panel title={n.label}>
      <div className="stack" style={{ gap: 8 }}>
        <div className="hint">
          {n.type_label}
          {n.redacted && " · identity hidden (needs recognition access)"}
          {n.location && <div>Location: {n.location.path}</div>}
          {n.run_id && <div>Run #{n.run_id}{n.camera_id ? ` · camera ${n.camera_id}` : ""}</div>}
          {n.first_seen && <div>Seen {dateTime(n.first_seen)}{n.last_seen ? ` – ${dateTime(n.last_seen)}` : ""}</div>}
        </div>
        <div className="row wrap" style={{ gap: 4 }}>
          {n.expandable && (expanded ? <button className="btn sm" onClick={onCollapse}>Collapse</button> : <button className="btn sm" onClick={onExpand}>Expand</button>)}
          {n.key && onRecenter && n.expandable && <button className="btn sm" onClick={() => onRecenter(n.key!)}>Center here</button>}
          <button className="btn sm" onClick={onPathFrom}>Path from here</button>
          <button className="btn sm" onClick={onPathTo}>Path to here</button>
        </div>
        <div className="row wrap" style={{ gap: 4 }}>
          {n.key && n.id != null && <Link className="btn sm ghost" to={`/relationships?key=${encodeURIComponent(n.key)}`}>Explorer</Link>}
          {n.key && JOURNEY_TYPES.has(n.type) && <Link className="btn sm ghost" to={`/relationships/journeys?key=${encodeURIComponent(n.key)}`}>Journey across cameras</Link>}
          {n.key && n.id != null && <Link className="btn sm ghost" to={`/relationships/timeline?key=${encodeURIComponent(n.key)}`}>Timeline</Link>}
          {n.run_id && <Link className="btn sm ghost" to={`/review/${n.run_id}${n.first_media_s != null ? `?t=${Math.max(0, n.first_media_s - 2).toFixed(1)}` : ""}`}>▶ Video</Link>}
        </div>
        <div>
          <div className="section-title">{mine.length} relationship{mine.length === 1 ? "" : "s"} shown</div>
          <ul className="g-interval-list">
            {mine.map((e) => (
              <li key={e.id}>
                <button className="linklike" onClick={() => onSelectEdge(e)}>
                  {e.source === n.node ? `${e.type} → ${label(e.target)}` : `← ${e.type} ${label(e.source)}`}
                </button>
                {e.count > 1 && <span className="hint"> ×{e.count}</span>} <StatePill state={e.state} confidence={e.nature === "context" ? null : e.best_confidence} />
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Panel>
  );
}

function EdgeInspector({ e, graph, onEvidence, evidenceId }: { e: VEdge; graph: VGraph; onEvidence: (id: number | null) => void; evidenceId: number | null }) {
  const a = graph.nodes.find((n) => n.node === e.source);
  const b = graph.nodes.find((n) => n.node === e.target);
  return (
    <Panel title={e.type}>
      <div className="stack" style={{ gap: 8 }}>
        <div>
          <strong>{a?.label}</strong> {e.label} <strong>{b?.label}</strong>
        </div>
        <div className="row wrap" style={{ gap: 4 }}>
          <Pill>{NATURE_LABEL[e.nature]}</Pill>
          {e.sensor && <Pill tone="warn">sensor-supported</Pill>}
          {e.merged && <Pill>through identified tracks</Pill>}
          {e.nature !== "context" && <StatePill state={e.state} confidence={e.best_confidence} />}
        </div>
        {e.nature === "context" && (
          <div className="hint">
            {e.type === "SEEN_AT" ? "Derived: the track was observed by this camera (its time span)." : "Derived from the location model: the place or camera lies inside this location."}
          </div>
        )}
        {e.intervals.length > 0 && e.nature !== "context" && (
          <div>
            <div className="section-title">{e.count} stored relationship{e.count === 1 ? "" : "s"}</div>
            <ul className="g-interval-list">
              {e.intervals.map((i, idx) => (
                <li key={`${i.id}-${idx}`} className={i.id === evidenceId ? "selected" : ""}>
                  <span className="nowrap">{i.start ? dateTime(i.start) : "–"}</span>
                  {i.end && i.end !== i.start && <span className="hint"> → {new Date(i.end).toLocaleTimeString()}</span>} <StatePill state={i.state} confidence={i.confidence} />
                  <div className="row" style={{ gap: 4 }}>
                    {i.id != null && <button className="btn sm ghost" onClick={() => onEvidence(i.id)}>Evidence</button>}
                    <VideoLink runId={i.run_id} t={i.start_media_s} label={i.start_media_s != null ? mediaClock(i.start_media_s) : "Video"} />
                    {i.run_id && <span className="hint">run #{i.run_id}</span>}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Panel>
  );
}
