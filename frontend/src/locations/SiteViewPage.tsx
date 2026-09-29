/* Site view: a floor plan, schematic or map of a site with what is happening
 * now: cameras (active runs, objects in view, recent alerts), recent events,
 * recent moves between cameras, who is in view (names only for viewers with
 * recognition access) and where an entity was last observed. */

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "../api/client";
import { Empty, ErrorNotice, Panel, Pill } from "../components/ui";
import { classLabel, eventLabel, timeOnly } from "../lib/format";
import { useRecognitionAuth } from "../lib/recognitionToken";
import type { EntityOut } from "../relationships/api";
import { EntityLink, IdentityNotice, useMeta } from "../relationships/bits";
import EntityPicker from "../relationships/EntityPicker";
import "../relationships/relationships.css";
import { loc, type LiveCamera } from "./api";
import "./locations.css";
import SitePlan, { layoutFrames } from "./SitePlan";

export default function SiteViewPage() {
  const [search, setSearch] = useSearchParams();
  const token = useRecognitionAuth((s) => s.token);
  const meta = useMeta();
  const graph = useQuery({ queryKey: ["locations-graph", token], queryFn: () => loc.graph() });
  const frames = layoutFrames(graph.data);
  const frameParam = search.get("frame") ? Number(search.get("frame")) : null;
  const frameId = frameParam ?? frames[0]?.id ?? null;
  const [minutes, setMinutes] = useState(15);
  const live = useQuery({ queryKey: ["locations-live", frameId, minutes, token], queryFn: () => loc.live(frameId ?? undefined, minutes), enabled: frameId != null, refetchInterval: 5000 });
  const [selected, setSelected] = useState<number | null>(null);
  const [entity, setEntity] = useState<EntityOut | null>(null);
  const last = useQuery({ queryKey: ["last-seen", entity?.key, token], queryFn: () => loc.lastSeen(entity!.key!), enabled: !!entity?.key, retry: 0 });

  const g = graph.data;
  const nodeOfCamera = useMemo(() => new Map((g?.nodes ?? []).filter((n) => n.camera_id != null).map((n) => [n.camera_id!, n])), [g]);
  const L = live.data;
  const overlays = useMemo(() => {
    const counts: Record<number, number> = {};
    const alerts: Record<number, number> = {};
    const active = new Set<number>();
    for (const c of L?.cameras ?? []) {
      if (c.run_id) active.add(c.camera_id);
      if (c.active_tracks) counts[c.camera_id] = c.active_tracks;
    }
    for (const a of L?.alerts ?? []) if (a.camera_id != null) alerts[a.camera_id] = (alerts[a.camera_id] ?? 0) + 1;
    const moves = (L?.transitions ?? [])
      .map((t) => ({ from: t.from.camera.node?.id ?? -1, to: t.to.camera.node?.id ?? -1, flagged: t.flags.some((f) => f !== "slower_than_expected" && f !== "faster_than_expected") }))
      .filter((m) => m.from > 0 && m.to > 0);
    const lastNode = last.data?.last?.node?.id ?? last.data?.last?.camera.node?.id ?? null;
    return { counts, alerts, active, moves, lastSeen: lastNode };
  }, [L, last.data]);

  useEffect(() => setSelected(null), [frameId]);
  const selNode = g?.nodes.find((n) => n.id === selected);
  const selCam: LiveCamera | undefined = selNode?.camera_id != null ? L?.cameras.find((c) => c.camera_id === selNode.camera_id) : undefined;

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Site view</h1>
          <div className="sub">Cameras, places and what is happening now: objects in view, recent events and alerts, moves between cameras. Click a camera for its feed and experiment; find an entity to see where it was last observed.</div>
        </div>
        <div className="row wrap">
          <Link className="btn" to="/locations/topology">
            Edit topology
          </Link>
          <Link className="btn" to="/relationships/journeys">
            Journeys
          </Link>
        </div>
      </div>
      <IdentityNotice sees={meta.data?.viewer.sees_identities} />
      {graph.isError && <ErrorNotice error={graph.error} />}
      {g && frames.length === 0 && (
        <Empty action={<Link className="btn primary" to="/locations/topology">Open the topology editor</Link>}>
          No site has a layout yet. Create a site in the topology editor, give it a layout (a floor plan, a schematic or a map) and place the cameras.
        </Empty>
      )}
      {g && frameId != null && (
        <div className="g-layout" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(280px, 360px)" }}>
          <div className="stack" style={{ minWidth: 0 }}>
            <Panel
              title={
                <select value={frameId} onChange={(e) => setSearch({ frame: e.target.value })} aria-label="Site or floor">
                  {frames.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.path}
                    </option>
                  ))}
                </select>
              }
              actions={
                <span className="row small" style={{ gap: 6 }}>
                  {live.isFetching ? <span className="hint">updating…</span> : L && <span className="hint">as of {timeOnly(L.at)}</span>}
                  <select value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} aria-label="Recent">
                    <option value={5}>last 5 min</option>
                    <option value={15}>last 15 min</option>
                    <option value={60}>last hour</option>
                    <option value={1440}>last 24 h</option>
                  </select>
                </span>
              }
            >
              <div style={{ position: "relative" }}>
                <SitePlan graph={g} frameId={frameId} height={560} selected={selected} onSelect={setSelected} overlays={overlays} />
                {selNode && selNode.kind === "camera" && (
                  <div className="site-popover" style={{ right: 12, top: 44 }}>
                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <strong>{selNode.name}</strong>
                      <button className="btn sm ghost" onClick={() => setSelected(null)} aria-label="Close">
                        ×
                      </button>
                    </div>
                    <div className="hint">{selNode.path}</div>
                    {selCam?.run_id ? (
                      <div className="stack" style={{ gap: 4, marginTop: 6 }}>
                        <div>
                          <Pill tone="ok" dot>
                            {selCam.state ?? "running"}
                          </Pill>{" "}
                          run #{selCam.run_id} · {selCam.active_tracks} in view
                        </div>
                        {Object.keys(selCam.classes).length > 0 && <div className="small">{Object.entries(selCam.classes).map(([c, n]) => `${n} ${classLabel(c).toLowerCase()}`).join(", ")}</div>}
                        {Object.keys(selCam.zones).length > 0 && <div className="small hint">Zones: {Object.entries(selCam.zones).map(([z, n]) => `${z} ${n}`).join(", ")}</div>}
                        <div className="row wrap" style={{ gap: 4 }}>
                          {selCam.experiment_id && <Link className="btn sm primary" to={`/experiments/${selCam.experiment_id}`}>Live feed</Link>}
                          <Link className="btn sm" to={`/analysis/runs/${selCam.run_id}`}>Run</Link>
                        </div>
                      </div>
                    ) : (
                      <div className="hint" style={{ marginTop: 6 }}>No active run.</div>
                    )}
                    <div className="row wrap" style={{ gap: 4, marginTop: 6 }}>
                      {selNode.camera_id != null && <Link className="btn sm ghost" to={`/cameras/${selNode.camera_id}`}>Camera</Link>}
                      {selNode.camera_id != null && <Link className="btn sm ghost" to={`/relationships/graph?location_id=${selNode.parent_id ?? ""}`}>Graph here</Link>}
                    </div>
                    <CameraExperiments cameraId={selNode.camera_id} />
                    <CameraEvents cameraId={selNode.camera_id} events={L?.events ?? []} />
                  </div>
                )}
                {selNode && selNode.kind !== "camera" && (
                  <div className="site-popover" style={{ right: 12, top: 44 }}>
                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <strong>{selNode.name}</strong>
                      <button className="btn sm ghost" onClick={() => setSelected(null)} aria-label="Close">
                        ×
                      </button>
                    </div>
                    <div className="hint">
                      {selNode.kind_label} · {selNode.path}
                    </div>
                    {selNode.restricted && <Pill tone="err">restricted</Pill>} {selNode.is_entry && <Pill>entry point</Pill>}
                    <div className="row wrap" style={{ gap: 4, marginTop: 6 }}>
                      <Link className="btn sm ghost" to={`/relationships/graph?location_id=${selNode.id}`}>Relationships here</Link>
                    </div>
                  </div>
                )}
              </div>
              <div className="hint" style={{ marginTop: 6 }}>
                Blue badge: objects in view · red dot: alerts in the last 24 h · highlighted camera: active run · orange lines: recent moves between cameras (red when flagged) · dashed ring: where the chosen entity was last seen.
              </div>
            </Panel>
          </div>
          <div className="site-side">
            <Panel title="Where was it last seen?">
              <div className="stack" style={{ gap: 6 }}>
                <EntityPicker value={entity} onChange={setEntity} types="recognized_person,registered_vehicle,license_plate,person_track,vehicle_track" />
                {last.isError && <ErrorNotice error={last.error} />}
                {last.data && !last.data.last && <div className="hint">No sighting.</div>}
                {last.data?.last && (
                  <div className="small">
                    <strong>{last.data.last.camera.name}</strong>
                    {last.data.last.node && ` / ${last.data.last.node.name}`}
                    <div className="hint">
                      {new Date(last.data.last.at).toLocaleString()}
                      {last.data.last.node?.frame_id != null && last.data.last.node.frame_id !== frameId && (
                        <>
                          {" "}
                          · <button className="linklike" onClick={() => setSearch({ frame: String(last.data!.last!.node!.frame_id) })}>show that plan</button>
                        </>
                      )}
                    </div>
                    {entity?.key && <Link className="btn sm ghost" to={`/relationships/journeys?key=${encodeURIComponent(entity.key)}`}>Journey</Link>}
                  </div>
                )}
              </div>
            </Panel>
            <Panel title={`Alerts (24 h) · ${L?.alerts.length ?? 0}`} flush>
              <ul className="site-list">
                {(L?.alerts ?? []).slice(0, 30).map((a) => (
                  <li key={`${a.source}${a.id}`}>
                    <div>
                      <strong>{a.label}</strong> <span className="hint">{timeOnly(a.at)}</span>
                    </div>
                    <div className="hint">{a.text}</div>
                  </li>
                ))}
                {L && L.alerts.length === 0 && <li className="hint">None.</li>}
              </ul>
            </Panel>
            <Panel title="Moves between cameras" flush>
              <ul className="site-list">
                {(L?.transitions ?? []).slice(0, 20).map((t) => (
                  <li key={t.id} className="clickable" onClick={() => t.subject?.key && setEntity(t.subject)}>
                    {timeOnly(t.arrived_at)} {t.subject ? <EntityLink e={t.subject} /> : "?"} {t.from.camera.name} → {t.to.camera.name} <span className="hint">{Math.round(t.gap_s)} s · {t.state_label.toLowerCase()}</span>
                  </li>
                ))}
                {L && L.transitions.length === 0 && <li className="hint">None recently.</li>}
              </ul>
            </Panel>
            <Panel title="In view now" flush>
              <ul className="site-list">
                {(L?.present ?? []).slice(0, 40).map((p) => (
                  <li key={p.track.key ?? p.track.label}>
                    {p.identity ? <EntityLink e={p.identity} /> : <EntityLink e={p.track} />} <span className="hint">· {nodeOfCamera.get(p.camera_id)?.name ?? `camera ${p.camera_id}`}</span>
                  </li>
                ))}
                {L && L.present.length === 0 && <li className="hint">Nobody tracked in the last 30 s.</li>}
              </ul>
            </Panel>
            <Panel title="Recent events" flush>
              <ul className="site-list">
                {(L?.events ?? []).slice(0, 30).map((e) => (
                  <li key={e.id}>
                    {timeOnly(e.at)} <strong>{eventLabel(e.event_type)}</strong> {e.label !== e.event_type ? e.label : ""} <span className="hint">{nodeOfCamera.get(e.camera_id)?.name}</span>
                  </li>
                ))}
                {L && L.events.length === 0 && <li className="hint">None in this period.</li>}
              </ul>
            </Panel>
          </div>
        </div>
      )}
    </div>
  );
}

function CameraExperiments({ cameraId }: { cameraId: number | null }) {
  const q = useQuery({ queryKey: ["experiments-of-camera", cameraId], queryFn: () => api.experiments.list({ camera_id: cameraId ?? undefined }), enabled: cameraId != null });
  if (!q.data?.length) return null;
  return (
    <div className="small" style={{ marginTop: 6 }}>
      Experiments:{" "}
      {q.data.slice(0, 4).map((x, i) => (
        <span key={x.id}>
          {i > 0 && ", "}
          <Link to={`/experiments/${x.id}`}>{x.name}</Link>
        </span>
      ))}
    </div>
  );
}

function CameraEvents({ cameraId, events }: { cameraId: number | null; events: { id: number; camera_id: number; event_type: string; label: string; at: string }[] }) {
  const mine = events.filter((e) => e.camera_id === cameraId).slice(0, 5);
  if (!mine.length) return null;
  return (
    <ul className="list-plain small" style={{ marginTop: 6 }}>
      {mine.map((e) => (
        <li key={e.id}>
          {timeOnly(e.at)} {eventLabel(e.event_type)} <span className="hint">{e.label !== e.event_type ? e.label : ""}</span>
        </li>
      ))}
    </ul>
  );
}


