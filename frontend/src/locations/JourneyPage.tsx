/* Journey across cameras: one entity's sightings in time order, shown three
 * ways that stay in step:
 *
 *   Timeline          - each sighting (camera, places entered and left) and the
 *                       transitions between them, with their provenance
 *   Location view     - the path over the site plan (numbered steps)
 *   Relationship graph- the entity and what it is related to
 *
 * Selecting a step, a move, a plan marker or a graph edge highlights the same
 * thing in the other two. */

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Empty, ErrorNotice, Field, Panel, Pill } from "../components/ui";
import { dateTime, timeOnly } from "../lib/format";
import { useRecognitionAuth } from "../lib/recognitionToken";
import type { EntityOut } from "../relationships/api";
import { EntityLink, IdentityNotice, mediaClock, useMeta, VideoLink } from "../relationships/bits";
import EntityPicker from "../relationships/EntityPicker";
import Evidence from "../relationships/Evidence";
import "../relationships/relationships.css";
import { FLAG_LABEL, loc, type Journey, type LocGraph, type Transition, type VEdge } from "./api";
import GraphCanvas, { GraphLegend } from "./GraphCanvas";
import { visible, NATURES } from "./graphModel";
import "./locations.css";
import SitePlan, { nodePoint, type PlanPathPoint } from "./SitePlan";
import TransitionCard, { range } from "./TransitionCard";
import { useGraph } from "./useGraph";

type Sel = { kind: "sighting"; index: number } | { kind: "transition"; id: number } | null;

const RANGES = [
  { id: "24", label: "Last 24 hours", hours: 24 },
  { id: "168", label: "Last 7 days", hours: 168 },
  { id: "720", label: "Last 30 days", hours: 720 },
];

export default function JourneyPage() {
  const [search, setSearch] = useSearchParams();
  const key = search.get("key");
  const token = useRecognitionAuth((s) => s.token);
  const meta = useMeta();
  const [picked, setPicked] = useState<EntityOut | null>(null);
  const [rangeId, setRangeId] = useState("168");
  const [sel, setSel] = useState<Sel>(null);
  const [evidence, setEvidence] = useState<number | null>(null);
  const hours = RANGES.find((r) => r.id === rangeId)?.hours ?? 168;
  const timeFrom = useMemo(() => new Date(Date.now() - hours * 3600_000).toISOString(), [hours]);

  const journey = useQuery({ queryKey: ["journey", key, timeFrom, token], queryFn: () => loc.journey(key!, { time_from: timeFrom }), enabled: !!key, retry: 0 });
  const locGraph = useQuery({ queryKey: ["locations-graph", token], queryFn: () => loc.graph() });
  const visual = useQuery({ queryKey: ["journey-graph", key, timeFrom, token], queryFn: () => loc.visual({ key: key!, depth: 1, project: true, context: true, time_from: timeFrom, min_state: "possible" }), enabled: !!key && journey.isSuccess, retry: 0 });
  const g = useGraph();
  const { reset } = g;
  useEffect(() => {
    if (visual.data) reset(visual.data);
  }, [visual.data, reset]);
  useEffect(() => setSel(null), [key]);

  const j = journey.data;
  const transitionById = useMemo(() => new Map((j?.transitions ?? []).map((t) => [t.id, t])), [j]);

  // ---- what the selection means in each view
  const hl = useMemo(() => {
    const nodes = new Set<string>();
    const edges = new Set<string>();
    const locNodes = new Set<number>();
    let step: string | null = null;
    if (!j || !sel) return { nodes, edges, locNodes, step };
    const graph = g.model?.graph;
    if (sel.kind === "sighting") {
      const s = j.sightings[sel.index];
      step = `s${sel.index}`;
      if (s?.camera.node) locNodes.add(s.camera.node.id);
      if (s?.node) locNodes.add(s.node.id);
      if (s?.camera.id != null) nodes.add(`camera:${s.camera.id}`);
      if (graph && s) {
        const t0 = Date.parse(s.first_at) - 2000;
        const t1 = Date.parse(s.last_at) + 2000;
        for (const e of graph.edges) {
          if (e.intervals.some((i) => i.camera_id === s.camera.id && i.start && Date.parse(i.start) >= t0 && Date.parse(i.start) <= t1)) {
            edges.add(e.id);
            nodes.add(e.source);
            nodes.add(e.target);
          }
        }
      }
    } else {
      const t = transitionById.get(sel.id);
      if (t) {
        for (const x of [t.from, t.to]) {
          if (x.camera.node) locNodes.add(x.camera.node.id);
          if (x.node) locNodes.add(x.node.id);
          if (x.camera.id != null) nodes.add(`camera:${x.camera.id}`);
        }
        const ids = [t.relationships.moved_to, t.relationships.moved_from].filter(Boolean) as number[];
        for (const e of graph?.edges ?? []) {
          if (e.ids.some((i) => ids.includes(i))) {
            edges.add(e.id);
            nodes.add(e.source);
            nodes.add(e.target);
          }
        }
        if (t.to_index != null) step = `s${t.to_index}`;
      }
    }
    return { nodes, edges, locNodes, step };
  }, [j, sel, g.model, transitionById]);

  const selectEdge = (e: VEdge | null) => {
    if (!e || !j) return;
    const t = j.transitions.find((x) => e.ids.some((id) => id === x.relationships.moved_to || id === x.relationships.moved_from));
    if (t) {
      setSel({ kind: "transition", id: t.id });
      return;
    }
    const i = e.intervals[0];
    if (i?.start) {
      const at = Date.parse(i.start);
      const idx = j.sightings.findIndex((s) => s.camera.id === i.camera_id && at >= Date.parse(s.first_at) - 2000 && at <= Date.parse(s.last_at) + 2000);
      if (idx >= 0) setSel({ kind: "sighting", index: idx });
    }
    if (e.ids.length) setEvidence(e.ids[e.ids.length - 1]);
  };

  const shown = useMemo(() => {
    const graph = g.model?.graph;
    if (!graph) return { nodes: [], edges: [] };
    return visible(graph, { natures: new Set(NATURES), types: null, minState: "possible", cameraIds: null, time: { kind: "all" } });
  }, [g.model]);

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Journeys across cameras</h1>
          <div className="sub">Where a person, a vehicle or a track was observed, camera by camera, and how the moves between cameras were correlated — with the evidence and confidence of each move. No continuous tracking between cameras is assumed.</div>
        </div>
        <div className="row wrap">
          <Link className="btn" to="/locations/site">
            Site view
          </Link>
          <Link className="btn" to="/locations/topology">
            Topology
          </Link>
        </div>
      </div>
      <IdentityNotice sees={meta.data?.viewer.sees_identities} />
      <Panel>
        <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
          <Field label="Entity">
            <EntityPicker value={picked ?? j?.entity ?? null} types="recognized_person,registered_vehicle,license_plate,person_track,vehicle_track,object_track" onChange={(e) => { setPicked(e); if (e?.key) setSearch({ key: e.key }); }} />
          </Field>
          <Field label="Time">
            <select value={rangeId} onChange={(e) => setRangeId(e.target.value)}>
              {RANGES.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
          </Field>
          {j && (
            <span className="hint">
              {j.sightings.length} sighting{j.sightings.length === 1 ? "" : "s"} on {j.cameras.length} camera{j.cameras.length === 1 ? "" : "s"} · {j.transitions.length} correlated move{j.transitions.length === 1 ? "" : "s"}
            </span>
          )}
          {key && <Link className="btn sm ghost" to={`/relationships/graph?key=${encodeURIComponent(key)}`}>Open in the graph</Link>}
        </div>
      </Panel>
      {!key && <Empty>Choose a recognized person, a vehicle, a plate or a track.</Empty>}
      {journey.isError && <ErrorNotice error={journey.error} />}
      {j && j.sightings.length === 0 && <Empty>No sightings in this time range.</Empty>}
      {j && j.sightings.length > 0 && (
        <>
          <div className="j-layout">
            <Panel title="Timeline">
              <JourneyTimeline j={j} sel={sel} onSelect={setSel} />
            </Panel>
            <div className="stack">
              <Panel title="Location path">
                {locGraph.data ? <LocationPath graph={locGraph.data} j={j} highlight={hl.locNodes} step={hl.step} onStep={(k) => setSel({ kind: "sighting", index: Number(k.slice(1)) })} /> : <div className="hint">Loading…</div>}
              </Panel>
              {sel?.kind === "transition" && transitionById.get(sel.id) && (
                <Panel title="Move">
                  <TransitionCard t={transitionById.get(sel.id)!} onEvidence={setEvidence} />
                </Panel>
              )}
              {sel?.kind === "sighting" && j.sightings[sel.index] && <SightingPanel j={j} index={sel.index} onEvidence={setEvidence} />}
              {evidence != null && <Evidence target={{ kind: "relationship", id: evidence }} onClose={() => setEvidence(null)} onOpen={(r) => r.kind === "relationship" && setEvidence(r.id)} />}
            </div>
          </div>
          <Panel title="Relationship graph">
            {visual.isError && <ErrorNotice error={visual.error} />}
            {g.model && (
              <>
                <GraphCanvas nodes={shown.nodes} edges={shown.edges} positions={g.positions} center={g.model.graph.center} height={440} highlightNodes={hl.nodes} highlightEdges={hl.edges}
                  onSelectEdge={selectEdge} onMoveNode={g.move} onSelectNode={(k) => { const cam = k?.startsWith("camera:") ? Number(k.slice(7)) : null; if (cam != null) { const idx = j.sightings.findIndex((s) => s.camera.id === cam); if (idx >= 0) setSel({ kind: "sighting", index: idx }); } }} />
                <div style={{ marginTop: 6 }}>
                  <GraphLegend />
                </div>
              </>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}

function JourneyTimeline({ j, sel, onSelect }: { j: Journey; sel: Sel; onSelect: (s: Sel) => void }) {
  const into = new Map<number, Transition>();
  for (const t of j.transitions) if (t.to_index != null) into.set(t.to_index, t);
  let lastDay = "";
  return (
    <ol className="j-steps">
      {j.sightings.map((s, i) => {
        const t = into.get(i);
        const day = new Date(s.first_at).toDateString();
        const showDay = day !== lastDay;
        lastDay = day;
        return (
          <li key={s.track.key ?? i}>
            {showDay && <div className="section-title" style={{ marginTop: 6 }}>{new Date(s.first_at).toLocaleDateString()}</div>}
            {t && (
              <div className={`j-move${sel?.kind === "transition" && sel.id === t.id ? " sel" : ""}${t.flags.some((f) => f !== "slower_than_expected" && f !== "faster_than_expected") ? " flagged" : ""}`} onClick={() => onSelect({ kind: "transition", id: t.id })}>
                → moved from {t.from.camera.name} in <strong>{Math.round(t.gap_s)} s</strong> (expected {range(t.expected.min_s, t.expected.max_s)}) · {t.state_label.toLowerCase()} {Math.round(t.confidence * 100)}%
                {t.flags.filter((f) => f !== "slower_than_expected").map((f) => (
                  <Pill key={f} tone="err">{FLAG_LABEL[f] ?? f}</Pill>
                ))}
              </div>
            )}
            <div className={`j-step${sel?.kind === "sighting" && sel.index === i ? " sel" : ""}`} onClick={() => onSelect({ kind: "sighting", index: i })}>
              <span className="j-num">{i + 1}</span>
              <div>
                <div>
                  <strong>{timeOnly(s.first_at)}</strong> · {s.camera.name}
                  {s.node && <span className="hint"> / {s.node.name}</span>}
                </div>
                <ul className="j-events">
                  {s.events.length === 0 && <li>Observed ({timeOnly(s.first_at)} – {timeOnly(s.last_at)})</li>}
                  {s.events.slice(0, 6).map((e) => (
                    <li key={e.relationship_id}>
                      {timeOnly(e.at)} {e.verb} {e.node?.name ?? e.place}
                    </li>
                  ))}
                  {s.events.length > 6 && <li className="hint">+{s.events.length - 6} more</li>}
                </ul>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function LocationPath({ graph, j, highlight, step, onStep }: { graph: LocGraph; j: Journey; highlight: Set<number>; step: string | null; onStep: (k: string) => void }) {
  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph]);
  // the frames the path touches, most used first
  const frames = useMemo(() => {
    const c = new Map<number, number>();
    for (const s of j.sightings) {
      const n = s.node ?? s.camera.node;
      if (n?.frame_id != null) c.set(n.frame_id, (c.get(n.frame_id) ?? 0) + 1);
    }
    return [...c.entries()].sort((a, b) => b[1] - a[1]).map(([id]) => id);
  }, [j]);
  const [frameId, setFrameId] = useState<number | null>(null);
  const fid = frameId ?? frames[0] ?? null;
  const frame = fid != null ? byId.get(fid) : undefined;
  const points: PlanPathPoint[] = [];
  if (frame) {
    j.sightings.forEach((s, i) => {
      const ref = s.node ?? s.camera.node;
      const n = ref ? byId.get(ref.id) : undefined;
      if (!n || n.frame_id !== frame.id) return;
      const p = nodePoint(n, frame);
      if (p) points.push({ ...p, key: `s${i}`, label: `${i + 1}. ${s.camera.name}${s.node ? ` / ${s.node.name}` : ""} · ${dateTime(s.first_at)}` });
    });
  }
  if (fid == null) return <Empty>The cameras of this journey are not placed in the location model yet (Locations › Topology).</Empty>;
  return (
    <div className="stack" style={{ gap: 6 }}>
      {frames.length > 1 && (
        <select value={fid} onChange={(e) => setFrameId(Number(e.target.value))} aria-label="Plan">
          {frames.map((f) => (
            <option key={f} value={f}>
              {byId.get(f)?.path}
            </option>
          ))}
        </select>
      )}
      <SitePlan graph={graph} frameId={fid} height={360} overlays={{ path: points, selectedStep: step, onStep, highlight }} />
      <div className="hint">
        {j.path.map((p) => p.node.name).join(" → ")}
      </div>
    </div>
  );
}

function SightingPanel({ j, index, onEvidence }: { j: Journey; index: number; onEvidence: (id: number) => void }) {
  const s = j.sightings[index];
  return (
    <Panel title={`Step ${index + 1}: ${s.camera.name}`}>
      <div className="stack" style={{ gap: 6 }}>
        <div className="hint">
          {s.camera.node?.path}
          <div>
            {dateTime(s.first_at)} – {timeOnly(s.last_at)}
            {s.run_id && <> · run #{s.run_id}{s.first_media_s != null && ` at ${mediaClock(s.first_media_s)}`}</>}
          </div>
        </div>
        <div>
          Track: <EntityLink e={s.track} showType withIdentity={false} />
          {s.identity_confidence != null && <span className="hint"> · identity link {Math.round(s.identity_confidence * 100)}%</span>}
        </div>
        <ul className="list-plain">
          {s.events.map((e) => (
            <li key={e.relationship_id}>
              <button className="linklike" onClick={() => onEvidence(e.relationship_id)}>
                {timeOnly(e.at)} {e.verb} {e.node?.name ?? e.place}
              </button>{" "}
              <VideoLink runId={s.run_id} t={e.media_s} label="" />
            </li>
          ))}
        </ul>
        <div className="row" style={{ gap: 4 }}>
          <VideoLink runId={s.run_id} t={s.first_media_s} label="Video of this step" />
          {s.run_id && <Link className="btn sm ghost" to={`/analysis/runs/${s.run_id}`}>Run #{s.run_id}</Link>}
        </div>
      </div>
    </Panel>
  );
}
