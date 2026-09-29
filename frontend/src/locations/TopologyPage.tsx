/* Location model and camera topology editor.
 *
 * Build the hierarchy (organization › site › building › floor › area › camera,
 * or site › road network › junction › camera), place nodes on a floor plan,
 * schematic or map, and connect them: adjacent cameras, the place between
 * them, expected travel time, direction, overlapping views, shared zones.
 * Map each camera's scene zones to locations so observations resolve to
 * places. Everything here is configuration the cross-camera correlation
 * reads; nothing is inferred from it on its own. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { ConfirmButton, Empty, ErrorNotice, Field, Notice, Panel, Pill, Tabs } from "../components/ui";
import { useRecognitionAuth } from "../lib/recognitionToken";
import "../relationships/relationships.css";
import { loc, uploadImage, type CrossCameraSettings, type LinkInput, type LinkKind, type LocGraph, type LocLink, type LocNode, type NodeKind, type TopologyCheck } from "./api";
import "./locations.css";
import SitePlan, { frameFor, layoutFrames } from "./SitePlan";

const LAYOUT_KINDS = new Set<NodeKind>(["organization", "site", "building", "floor", "area", "road_network", "parking"]);
const TRAVERSABLE = new Set<LinkKind>(["CONNECTED_TO", "ADJACENT_TO", "LEADS_TO"]);
const CHILD_HINT: Partial<Record<NodeKind, NodeKind[]>> = {
  organization: ["site"],
  site: ["building", "road_network", "gate", "parking", "area", "camera"],
  building: ["floor", "entrance", "camera"],
  floor: ["area", "room", "corridor", "entrance", "stairs", "camera", "sensor"],
  area: ["room", "zone", "camera", "sensor"],
  road_network: ["road", "junction", "gate", "camera"],
  road: ["junction", "camera"],
  junction: ["camera"],
  parking: ["zone", "camera"],
};

function blankNode(kind: NodeKind, parent: LocNode | null, graph: LocGraph): Partial<LocNode> {
  const frameId = parent ? (parent.layout ? parent.id : parent.frame_id) : null;
  const frame = graph.nodes.find((n) => n.id === frameId);
  const L = frame?.layout;
  const count = graph.nodes.filter((n) => n.parent_id === (parent?.id ?? null)).length;
  const at = L ? { x: Math.round(L.width * (0.2 + ((count * 0.17) % 0.6))), y: Math.round(L.height * (0.3 + ((count * 0.23) % 0.4))) } : { x: null, y: null };
  const layout = LAYOUT_KINDS.has(kind) && (kind === "site" || kind === "organization" || kind === "floor" || kind === "road_network") ? { mode: "schematic" as const, width: 100, height: 60, unit: "m" as const } : null;
  return { kind, name: "", parent_id: parent?.id ?? null, ...at, layout, is_entry: kind === "gate" || kind === "entrance", restricted: false, shape: [], meta: {}, description: "" };
}

function toInput(n: Partial<LocNode>): Record<string, unknown> {
  const keys = ["parent_id", "project_id", "kind", "name", "description", "camera_id", "sensor_id", "x", "y", "w", "h", "shape", "lat", "lon", "level", "orientation_deg", "fov_deg", "view_range", "layout", "is_entry", "restricted", "meta"];
  return Object.fromEntries(keys.map((k) => [k, (n as Record<string, unknown>)[k] ?? (k === "shape" ? [] : k === "meta" ? {} : k === "description" ? "" : k === "is_entry" || k === "restricted" ? false : null)]));
}

export default function TopologyPage() {
  const qc = useQueryClient();
  const token = useRecognitionAuth((s) => s.token);
  const graph = useQuery({ queryKey: ["locations-graph", token], queryFn: () => loc.graph() });
  const meta = useQuery({ queryKey: ["locations-meta", token], queryFn: loc.meta });
  const [selected, setSelected] = useState<number | null>(null);
  const [selLink, setSelLink] = useState<number | null>(null);
  const [frameId, setFrameId] = useState<number | null>(null);
  const [linkMode, setLinkMode] = useState(false);
  const [newLinkKind, setNewLinkKind] = useState<LinkKind>("CONNECTED_TO");
  const [tab, setTab] = useState("model");
  const [error, setError] = useState<unknown>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["locations-graph"] });
  const g = graph.data;
  const frames = layoutFrames(g);

  useEffect(() => {
    if (!g) return;
    if (frameId == null || !g.nodes.some((n) => n.id === frameId)) setFrameId(frames[0]?.id ?? null);
  }, [g, frameId, frames]);

  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(e);
    }
  };
  const select = (id: number | null) => {
    setSelected(id);
    setSelLink(null);
    if (id != null && g) {
      const f = frameFor(g, id);
      const n = g.nodes.find((x) => x.id === id);
      if (n?.layout) setFrameId(id);
      else if (f != null && f !== frameId && !frames.some((x) => x.id === frameId && g.nodes.find((y) => y.id === id)?.frame_id === x.id)) setFrameId(f);
    }
  };
  const node = g?.nodes.find((n) => n.id === selected) ?? null;
  const link = g?.edges.find((e) => !e.derived && e.id === selLink) as (LocLink & { derived: boolean }) | undefined;
  const canEdit = meta.data?.viewer.can.rules ?? true;

  const addChild = (kind: NodeKind, parent: LocNode | null, extra: Partial<LocNode> = {}) =>
    act(async () => {
      const base = blankNode(kind, parent, g!);
      const label = meta.data?.node_kinds.find((k) => k.id === kind)?.label ?? kind;
      const n = await loc.createNode(toInput({ ...base, name: extra.name ?? `${label} ${(g?.nodes.filter((x) => x.kind === kind).length ?? 0) + 1}`, ...extra }) as never);
      setSelected(n.id);
    });

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Locations and camera topology</h1>
          <div className="sub">Where cameras and places are relative to each other, and how people and vehicles can move between them. Cross-camera correlation uses this to tell plausible moves from impossible ones. GPS is optional: logical plans and schematics work.</div>
        </div>
        <div className="row wrap">
          <Link className="btn" to="/locations/site">
            Site view
          </Link>
          <Link className="btn" to="/relationships/journeys">
            Journeys
          </Link>
        </div>
      </div>
      <Tabs tabs={[{ id: "model", label: "Location model" }, { id: "check", label: "Check a move" }, { id: "settings", label: "Cross-camera settings" }]} active={tab} onChange={setTab} />
      <ErrorNotice error={error} />
      {!canEdit && <Notice tone="warn">Your recognition token's role cannot change the location model (the rules role of Relationship settings).</Notice>}
      {tab === "check" && g && <CheckMove graph={g} />}
      {tab === "settings" && <SettingsForm />}
      {tab === "model" && g && (
        <div className="topo-layout">
          <div className="stack">
            <Panel title="Hierarchy" flush actions={<AddRoot onAdd={(kind) => addChild(kind, null)} />}>
              {g.nodes.length === 0 ? (
                <div style={{ padding: 10 }}>
                  <Empty>Start with a site (or an organization with several sites). Then add buildings, floors and areas, or a road network with junctions, and place the cameras.</Empty>
                </div>
              ) : (
                <Tree graph={g} selected={selected} onSelect={select} />
              )}
            </Panel>
            {g.unplaced_cameras.length > 0 && (
              <Panel title={`Cameras not placed yet (${g.unplaced_cameras.length})`}>
                <ul className="list-plain">
                  {g.unplaced_cameras.map((c) => (
                    <li key={c.id} className="row" style={{ justifyContent: "space-between" }}>
                      <span>{c.name}</span>
                      <button className="btn sm" disabled={!node || node.kind === "camera"} title={node ? `Place inside ${node.name}` : "Select where it is first"}
                        onClick={() => addChild("camera", node, { name: c.name, camera_id: c.id, orientation_deg: 90, fov_deg: 70 })}>
                        Place in {node && node.kind !== "camera" ? node.name : "…"}
                      </button>
                    </li>
                  ))}
                </ul>
              </Panel>
            )}
          </div>
          <div className="stack" style={{ minWidth: 0 }}>
            <Panel
              title={
                <span className="row" style={{ gap: 8 }}>
                  Plan
                  <select value={frameId ?? ""} onChange={(e) => setFrameId(e.target.value ? Number(e.target.value) : null)} aria-label="Layout">
                    {frames.map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.path}
                      </option>
                    ))}
                  </select>
                </span>
              }
              actions={
                <span className="topo-mode">
                  <button className={`btn sm ${!linkMode ? "active" : ""}`} onClick={() => setLinkMode(false)}>
                    Select / move
                  </button>
                  <button className={`btn sm ${linkMode ? "active" : ""}`} onClick={() => setLinkMode(true)} disabled={!canEdit}>
                    Link
                  </button>
                  {linkMode && (
                    <select value={newLinkKind} onChange={(e) => setNewLinkKind(e.target.value as LinkKind)} aria-label="Kind of link">
                      {(meta.data?.link_kinds ?? []).map((k) => (
                        <option key={k.id} value={k.id}>
                          {k.id}
                        </option>
                      ))}
                    </select>
                  )}
                </span>
              }
            >
              {frameId == null ? (
                <Empty>Give a site, building, floor or road network a layout (size and unit) to draw it here.</Empty>
              ) : (
                <SitePlan graph={g} frameId={frameId} selected={selected} selectedLink={selLink} editable={canEdit} linkMode={linkMode}
                  onSelect={select} onSelectLink={(l) => { setSelLink(l.id); setSelected(null); }}
                  onMove={(id, x, y) => act(() => loc.positions([{ id, x, y }]))}
                  onLink={(a, b) => act(async () => { const l = await loc.createLink({ source_id: a, target_id: b, kind: newLinkKind, one_way: false }); setSelLink(l.id); setSelected(null); setLinkMode(false); })} />
              )}
              <div className="hint" style={{ marginTop: 6 }}>
                Drag nodes to place them. In Link mode click two nodes: cameras linked directly form the camera topology (adjacent cameras, travel time, direction); places linked to places describe how one can move. A place between two cameras goes in the link's “via”.
              </div>
            </Panel>
          </div>
          <div className="stack topo-props">
            {node && <NodeEditor key={node.id} node={node} graph={g} canEdit={canEdit} onChanged={refresh} onError={setError} onAddChild={(k) => addChild(k, node)} onDeleted={() => setSelected(null)}
              onSelectLink={(id) => { setSelLink(id); setSelected(null); }} />}
            {link && <LinkEditor key={link.id} link={link} graph={g} canEdit={canEdit} onChanged={refresh} onError={setError} onDeleted={() => setSelLink(null)} />}
            {!node && !link && <Panel title="Properties"><Empty>Select a node in the hierarchy or on the plan, or a link on the plan.</Empty></Panel>}
          </div>
        </div>
      )}
    </div>
  );
}

function AddRoot({ onAdd }: { onAdd: (k: NodeKind) => void }) {
  return (
    <span className="row" style={{ gap: 4 }}>
      <button className="btn sm" onClick={() => onAdd("site")}>
        + Site
      </button>
      <button className="btn sm ghost" onClick={() => onAdd("organization")}>
        + Organization
      </button>
    </span>
  );
}

function Tree({ graph, selected, onSelect }: { graph: LocGraph; selected: number | null; onSelect: (id: number) => void }) {
  const children = useMemo(() => {
    const m = new Map<number | null, LocNode[]>();
    for (const n of graph.nodes) {
      if (!m.has(n.parent_id)) m.set(n.parent_id, []);
      m.get(n.parent_id)!.push(n);
    }
    for (const list of m.values()) list.sort((a, b) => Number(a.kind === "camera") - Number(b.kind === "camera") || a.name.localeCompare(b.name));
    return m;
  }, [graph]);
  const render = (parent: number | null, depth: number): React.ReactNode =>
    (children.get(parent) ?? []).map((n) => (
      <li key={n.id} className={selected === n.id ? "selected" : ""}>
        <button onClick={() => onSelect(n.id)} style={{ paddingLeft: 6 + depth * 14 }}>
          <span>{n.name}</span> <span className="topo-kind">{n.kind_label}</span>
          {n.is_entry && <span className="hint" title="Entry point">⇥</span>}
          {n.restricted && <span className="hint" title="Restricted">⛔</span>}
        </button>
        {children.has(n.id) && <ul className="topo-tree">{render(n.id, depth + 1)}</ul>}
      </li>
    ));
  return <ul className="topo-tree">{render(null, 0)}</ul>;
}

function num(v: string): number | null {
  if (v.trim() === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function NodeEditor({ node, graph, canEdit, onChanged, onError, onAddChild, onDeleted, onSelectLink }: {
  node: LocNode; graph: LocGraph; canEdit: boolean; onChanged: () => void; onError: (e: unknown) => void; onAddChild: (k: NodeKind) => void; onDeleted: () => void; onSelectLink: (id: number) => void;
}) {
  const meta = useQuery({ queryKey: ["locations-meta"], queryFn: loc.meta });
  const [d, setD] = useState<LocNode>(node);
  const [childKind, setChildKind] = useState<NodeKind>((CHILD_HINT[node.kind] ?? ["area"])[0]);
  const dirty = JSON.stringify(toInput(d)) !== JSON.stringify(toInput(node));
  const save = useMutation({ mutationFn: () => loc.updateNode(node.id, toInput(d) as never), onSuccess: onChanged, onError });
  const del = useMutation({ mutationFn: () => loc.deleteNode(node.id), onSuccess: () => { onDeleted(); onChanged(); }, onError });
  const links = graph.edges.filter((e) => !e.derived && (e.source === node.id || e.target === node.id));
  const name = (id: number | null | undefined) => graph.nodes.find((n) => n.id === id)?.name ?? "?";
  const possibleParents = graph.nodes.filter((n) => n.id !== node.id && n.kind !== "camera" && n.kind !== "sensor" && !n.path.startsWith(`${node.path} /`));
  const set = (patch: Partial<LocNode>) => setD({ ...d, ...patch });
  const L = d.layout;
  return (
    <>
      <Panel title={node.name} actions={<Pill>{node.kind_label}</Pill>}>
        <div className="stack" style={{ gap: 8 }}>
          <div className="hint">{node.path}</div>
          <Field label="Name">
            <input value={d.name} onChange={(e) => set({ name: e.target.value })} disabled={!canEdit} />
          </Field>
          <div className="row" style={{ gap: 8 }}>
            <Field label="Kind">
              <select value={d.kind} onChange={(e) => set({ kind: e.target.value as NodeKind })} disabled={!canEdit || node.kind === "camera"}>
                {(meta.data?.node_kinds ?? []).filter((k) => (node.kind === "camera") === (k.id === "camera")).map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Inside">
              <select value={d.parent_id ?? ""} onChange={(e) => set({ parent_id: e.target.value ? Number(e.target.value) : null })} disabled={!canEdit}>
                <option value="">(top level)</option>
                {possibleParents.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.path}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div className="row" style={{ gap: 8 }}>
            <Field label={`x${graph.nodes.find((n) => n.id === node.frame_id)?.layout?.unit === "m" ? " (m)" : ""}`}>
              <input type="number" value={d.x ?? ""} onChange={(e) => set({ x: num(e.target.value) })} disabled={!canEdit} style={{ width: 80 }} />
            </Field>
            <Field label="y">
              <input type="number" value={d.y ?? ""} onChange={(e) => set({ y: num(e.target.value) })} disabled={!canEdit} style={{ width: 80 }} />
            </Field>
            {node.kind !== "camera" && node.kind !== "sensor" && (
              <>
                <Field label="Width">
                  <input type="number" value={d.w ?? ""} onChange={(e) => set({ w: num(e.target.value) })} disabled={!canEdit} style={{ width: 70 }} />
                </Field>
                <Field label="Depth">
                  <input type="number" value={d.h ?? ""} onChange={(e) => set({ h: num(e.target.value) })} disabled={!canEdit} style={{ width: 70 }} />
                </Field>
              </>
            )}
          </div>
          <details>
            <summary className="small">GPS and floor (optional)</summary>
            <div className="row" style={{ gap: 8, marginTop: 6 }}>
              <Field label="Latitude">
                <input type="number" step="any" value={d.lat ?? ""} onChange={(e) => set({ lat: num(e.target.value) })} disabled={!canEdit} style={{ width: 110 }} />
              </Field>
              <Field label="Longitude">
                <input type="number" step="any" value={d.lon ?? ""} onChange={(e) => set({ lon: num(e.target.value) })} disabled={!canEdit} style={{ width: 110 }} />
              </Field>
              <Field label="Floor level">
                <input type="number" value={d.level ?? ""} onChange={(e) => set({ level: num(e.target.value) })} disabled={!canEdit} style={{ width: 60 }} />
              </Field>
            </div>
          </details>
          {node.kind === "camera" && (
            <div className="row" style={{ gap: 8 }}>
              <Field label="Facing (°, 0 = up)">
                <input type="number" value={d.orientation_deg ?? ""} onChange={(e) => set({ orientation_deg: num(e.target.value) })} disabled={!canEdit} style={{ width: 70 }} />
              </Field>
              <Field label="Field of view (°)">
                <input type="number" value={d.fov_deg ?? ""} onChange={(e) => set({ fov_deg: num(e.target.value) })} disabled={!canEdit} style={{ width: 70 }} />
              </Field>
              <Field label="Reach">
                <input type="number" value={d.view_range ?? ""} onChange={(e) => set({ view_range: num(e.target.value) })} disabled={!canEdit} style={{ width: 70 }} />
              </Field>
            </div>
          )}
          {node.kind === "sensor" && (
            <Field label="Sensor id" help="The sensor_id its observations use (POST /api/relationships/observations).">
              <input value={d.sensor_id ?? ""} onChange={(e) => set({ sensor_id: e.target.value })} disabled={!canEdit} />
            </Field>
          )}
          {node.kind !== "camera" && node.kind !== "sensor" && (
            <div className="row wrap" style={{ gap: 12 }}>
              <label className="row small" style={{ gap: 4 }} title="People and vehicles enter and leave the site here (journeys start and end here)">
                <input type="checkbox" checked={d.is_entry} onChange={(e) => set({ is_entry: e.target.checked })} disabled={!canEdit} /> Entry point
              </label>
              <label className="row small" style={{ gap: 4 }} title="Being here without passing an entry point first is reported (an observation, not an accusation)">
                <input type="checkbox" checked={d.restricted} onChange={(e) => set({ restricted: e.target.checked })} disabled={!canEdit} /> Restricted
              </label>
            </div>
          )}
          {node.kind !== "camera" && node.kind !== "sensor" && (
            <details open={!!L}>
              <summary className="small">Layout (this node is drawn as a plan)</summary>
              <div className="stack" style={{ gap: 6, marginTop: 6 }}>
                <label className="row small" style={{ gap: 4 }}>
                  <input type="checkbox" checked={!!L} onChange={(e) => set({ layout: e.target.checked ? { mode: "schematic", width: 100, height: 60, unit: "m" } : null })} disabled={!canEdit} /> Has its own layout
                </label>
                {L && (
                  <>
                    <div className="row" style={{ gap: 8 }}>
                      <Field label="Kind">
                        <select value={L.mode} onChange={(e) => set({ layout: { ...L, mode: e.target.value as "plan" } })} disabled={!canEdit}>
                          <option value="plan">Floor plan</option>
                          <option value="schematic">Schematic</option>
                          <option value="map">Map</option>
                        </select>
                      </Field>
                      <Field label="Width">
                        <input type="number" value={L.width} onChange={(e) => set({ layout: { ...L, width: Math.max(1, Number(e.target.value)) } })} disabled={!canEdit} style={{ width: 80 }} />
                      </Field>
                      <Field label="Height">
                        <input type="number" value={L.height} onChange={(e) => set({ layout: { ...L, height: Math.max(1, Number(e.target.value)) } })} disabled={!canEdit} style={{ width: 80 }} />
                      </Field>
                      <Field label="Unit">
                        <select value={L.unit} onChange={(e) => set({ layout: { ...L, unit: e.target.value as "m" } })} disabled={!canEdit}>
                          <option value="m">metres</option>
                          <option value="units">units (not to scale)</option>
                        </select>
                      </Field>
                    </div>
                    {L.mode === "map" && (
                      <div className="row wrap" style={{ gap: 6 }}>
                        {(["north", "south", "west", "east"] as const).map((k) => (
                          <Field key={k} label={k}>
                            <input type="number" step="any" value={L.bounds?.[k] ?? ""} disabled={!canEdit} style={{ width: 100 }}
                              onChange={(e) => set({ layout: { ...L, bounds: { north: 0, south: 0, east: 0, west: 0, ...(L.bounds ?? {}), [k]: Number(e.target.value) } } })} />
                          </Field>
                        ))}
                        <div className="hint">The geographic box of the map: nodes with GPS and no x/y are placed from it.</div>
                      </div>
                    )}
                    {node.layout && canEdit && (
                      <div className="row" style={{ gap: 6 }}>
                        <label className="btn sm">
                          {node.layout.image ? "Replace picture" : "Upload floor plan / map picture"}
                          <input type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={async (e) => { const f = e.target.files?.[0]; if (!f) return; try { await uploadImage(node.id, f); onChanged(); } catch (err) { onError(err); } }} />
                        </label>
                        {node.layout.image && <button className="btn sm ghost" onClick={async () => { await loc.deleteImage(node.id); onChanged(); }}>Remove picture</button>}
                      </div>
                    )}
                  </>
                )}
              </div>
            </details>
          )}
          <Field label="Notes">
            <textarea rows={2} value={d.description} onChange={(e) => set({ description: e.target.value })} disabled={!canEdit} />
          </Field>
          {canEdit && (
            <div className="row" style={{ justifyContent: "space-between" }}>
              <button className="btn primary sm" disabled={!dirty || save.isPending || !d.name.trim()} onClick={() => save.mutate()}>
                Save
              </button>
              <ConfirmButton label="Delete" confirm={`Delete ${node.name} and everything inside it?`} onConfirm={() => del.mutate()} />
            </div>
          )}
          {canEdit && node.kind !== "camera" && node.kind !== "sensor" && (
            <div className="row" style={{ gap: 6 }}>
              <select value={childKind} onChange={(e) => setChildKind(e.target.value as NodeKind)} aria-label="Kind of child">
                {(meta.data?.node_kinds ?? []).filter((k) => k.id !== "camera").map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.label}
                  </option>
                ))}
              </select>
              <button className="btn sm" onClick={() => onAddChild(childKind)}>
                + Add inside
              </button>
            </div>
          )}
        </div>
      </Panel>
      {node.kind === "camera" && node.camera_id != null && <ZoneMapping cameraId={node.camera_id} graph={graph} canEdit={canEdit} onChanged={onChanged} onError={onError} />}
      <Panel title={`Links (${links.length})`}>
        {links.length === 0 ? (
          <div className="hint">None. Use Link mode on the plan.</div>
        ) : (
          <ul className="list-plain">
            {links.map((l) => (
              <li key={l.id}>
                <button className="linklike" onClick={() => onSelectLink(l.id!)}>
                  {l.source === node.id ? `${l.kind} → ${name(l.target)}` : `${name(l.source)} ${l.kind} → this`}
                </button>
                {(l.travel_min_s != null || l.travel_max_s != null) && <span className="hint"> · {l.travel_min_s ?? 0}–{l.travel_max_s ?? "?"} s</span>}
                {l.one_way && <span className="hint"> · one way</span>}
                {l.via_id && <span className="hint"> · via {name(l.via_id)}</span>}
              </li>
            ))}
          </ul>
        )}
        {node.kind === "camera" && (
          <div className="hint" style={{ marginTop: 6 }}>
            A camera covers the places its scene zones are mapped to and the places linked to it with VISIBLE_FROM. Without either, it stands for the area it is placed in.
          </div>
        )}
      </Panel>
    </>
  );
}

function ZoneMapping({ cameraId, graph, canEdit, onChanged, onError }: { cameraId: number; graph: LocGraph; canEdit: boolean; onChanged: () => void; onError: (e: unknown) => void }) {
  const q = useQuery({ queryKey: ["camera-zones", cameraId], queryFn: () => loc.cameraZones(cameraId) });
  const [map, setMap] = useState<Record<string, number | null>>({});
  useEffect(() => {
    if (q.data) setMap(Object.fromEntries(q.data.items.map((i) => [i.object_id, i.node_id])));
  }, [q.data]);
  const places = graph.nodes.filter((n) => n.kind !== "camera" && n.kind !== "sensor");
  const save = useMutation({
    mutationFn: () => loc.setCameraZones(cameraId, (q.data?.items ?? []).map((i) => ({ object_id: i.object_id, object_kind: i.object_kind, node_id: map[i.object_id] ?? null }))),
    onSuccess: () => { void q.refetch(); onChanged(); },
    onError,
  });
  return (
    <Panel title="Scene zones → locations">
      {q.isError && <ErrorNotice error={q.error} />}
      {q.data && q.data.items.length === 0 && (
        <div className="hint">
          This camera's scene has no zones, lines or routes yet. <Link to={`/scene/${cameraId}`}>Draw them in the Scene Builder</Link>.
        </div>
      )}
      {q.data && q.data.items.length > 0 && (
        <div className="stack" style={{ gap: 6 }}>
          <div className="hint">Scene v{q.data.scene_version}. Mapped zones resolve observations to places (“entered Gate A” → Gate North).</div>
          <table className="table">
            <tbody>
              {q.data.items.map((i) => (
                <tr key={i.object_id}>
                  <td>
                    {i.name} <span className="hint">{i.type}</span>
                  </td>
                  <td>
                    <select value={map[i.object_id] ?? ""} onChange={(e) => setMap({ ...map, [i.object_id]: e.target.value ? Number(e.target.value) : null })} disabled={!canEdit}>
                      <option value="">(not mapped)</option>
                      {places.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.path}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {canEdit && (
            <button className="btn sm primary" onClick={() => save.mutate()} disabled={save.isPending}>
              Save mapping
            </button>
          )}
        </div>
      )}
    </Panel>
  );
}

function LinkEditor({ link, graph, canEdit, onChanged, onError, onDeleted }: { link: LocLink; graph: LocGraph; canEdit: boolean; onChanged: () => void; onError: (e: unknown) => void; onDeleted: () => void }) {
  const [d, setD] = useState<LinkInput>({ ...link });
  const name = (id: number | null) => graph.nodes.find((n) => n.id === id)?.name ?? "?";
  const save = useMutation({ mutationFn: () => loc.updateLink(link.id, d), onSuccess: onChanged, onError });
  const del = useMutation({ mutationFn: () => loc.deleteLink(link.id), onSuccess: () => { onDeleted(); onChanged(); }, onError });
  const places = graph.nodes.filter((n) => n.kind !== "camera" && n.kind !== "sensor");
  const cams = [link.source_id, link.target_id].every((id) => graph.nodes.find((n) => n.id === id)?.kind === "camera");
  return (
    <Panel title="Link" actions={<Pill>{d.kind}</Pill>}>
      <div className="stack" style={{ gap: 8 }}>
        <div>
          <strong>{name(d.source_id)}</strong> → <strong>{name(d.target_id)}</strong>{" "}
          {canEdit && <button className="linklike" onClick={() => setD({ ...d, source_id: d.target_id, target_id: d.source_id })}>swap</button>}
        </div>
        <Field label="Kind">
          <select value={d.kind} onChange={(e) => setD({ ...d, kind: e.target.value as LinkKind })} disabled={!canEdit}>
            {["CONNECTED_TO", "ADJACENT_TO", "LEADS_TO", "VISIBLE_FROM", "ABOVE", "BELOW"].map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </Field>
        {TRAVERSABLE.has(d.kind) && (
          <>
            <div className="row" style={{ gap: 8 }}>
              <Field label="Shortest travel (s)">
                <input type="number" min={0} value={d.travel_min_s ?? ""} onChange={(e) => setD({ ...d, travel_min_s: num(e.target.value) })} disabled={!canEdit} style={{ width: 90 }} />
              </Field>
              <Field label="Longest travel (s)">
                <input type="number" min={0} value={d.travel_max_s ?? ""} onChange={(e) => setD({ ...d, travel_max_s: num(e.target.value) })} disabled={!canEdit} style={{ width: 90 }} />
              </Field>
              <Field label="Distance">
                <input type="number" min={0} value={d.distance ?? ""} onChange={(e) => setD({ ...d, distance: num(e.target.value) })} disabled={!canEdit} style={{ width: 80 }} />
              </Field>
            </div>
            <div className="hint">Without travel times, a metric distance (given here or measured on a plan in metres) gives an estimate; otherwise the time is unknown and weighs less.</div>
            <div className="row wrap" style={{ gap: 12 }}>
              <label className="row small" style={{ gap: 4 }}>
                <input type="checkbox" checked={d.one_way} onChange={(e) => setD({ ...d, one_way: e.target.checked })} disabled={!canEdit} /> One way ({name(d.source_id)} → {name(d.target_id)})
              </label>
              {cams && (
                <label className="row small" style={{ gap: 4 }}>
                  <input type="checkbox" checked={d.overlap} onChange={(e) => setD({ ...d, overlap: e.target.checked })} disabled={!canEdit} /> Views overlap
                </label>
              )}
            </div>
            <div className="row" style={{ gap: 8 }}>
              <Field label="Via (the place between)">
                <select value={d.via_id ?? ""} onChange={(e) => setD({ ...d, via_id: e.target.value ? Number(e.target.value) : null })} disabled={!canEdit}>
                  <option value="">–</option>
                  {places.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.path}
                    </option>
                  ))}
                </select>
              </Field>
              {cams && (
                <Field label="Shared zone (both see it)">
                  <select value={d.shared_id ?? ""} onChange={(e) => setD({ ...d, shared_id: e.target.value ? Number(e.target.value) : null })} disabled={!canEdit}>
                    <option value="">–</option>
                    {places.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.path}
                      </option>
                    ))}
                  </select>
                </Field>
              )}
            </div>
          </>
        )}
        <Field label="Notes">
          <input value={d.notes} onChange={(e) => setD({ ...d, notes: e.target.value })} disabled={!canEdit} />
        </Field>
        {canEdit && (
          <div className="row" style={{ justifyContent: "space-between" }}>
            <button className="btn primary sm" onClick={() => save.mutate()} disabled={save.isPending}>
              Save link
            </button>
            <ConfirmButton label="Delete link" onConfirm={() => del.mutate()} />
          </div>
        )}
      </div>
    </Panel>
  );
}

function CheckMove({ graph }: { graph: LocGraph }) {
  const cams = graph.nodes.filter((n) => n.kind === "camera" && n.camera_id != null);
  const [a, setA] = useState<number | "">(cams[0]?.camera_id ?? "");
  const [b, setB] = useState<number | "">(cams[1]?.camera_id ?? "");
  const [cls, setCls] = useState("person");
  const q = useQuery<TopologyCheck>({ queryKey: ["topology-check", a, b, cls], queryFn: () => loc.check({ from_camera: Number(a), to_camera: Number(b), object_class: cls }), enabled: a !== "" && b !== "" && a !== b });
  const r = q.data;
  return (
    <Panel title="What would the correlation engine conclude about a move?">
      <div className="stack">
        <div className="row wrap" style={{ gap: 10 }}>
          <Field label="From camera">
            <select value={a} onChange={(e) => setA(Number(e.target.value))}>
              {cams.map((c) => (
                <option key={c.id} value={c.camera_id!}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="To camera">
            <select value={b} onChange={(e) => setB(Number(e.target.value))}>
              {cams.map((c) => (
                <option key={c.id} value={c.camera_id!}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Object">
            <select value={cls} onChange={(e) => setCls(e.target.value)}>
              <option value="person">Person</option>
              <option value="car">Vehicle</option>
            </select>
          </Field>
        </div>
        {cams.length < 2 && <Empty>Place at least two cameras.</Empty>}
        {q.isError && <ErrorNotice error={q.error} />}
        {r && (
          <dl className="prov-grid">
            <dt>Topology</dt>
            <dd>
              <strong>{r.kind === "direct" ? "Directly connected" : r.kind === "overlap" ? "Overlapping views" : r.kind === "path" ? `Connected through ${r.hops} link${r.hops === 1 ? "" : "s"}` : r.kind === "unconnected" ? "Not connected" : "Not in the location model"}</strong>
              {r.wrong_way && <Pill tone="err">only against a one-way link</Pill>} <span className="hint">{r.note}</span>
            </dd>
            <dt>Way</dt>
            <dd>{r.path_nodes.map((n) => n.name).join(" → ") || "–"}</dd>
            <dt>Expected travel</dt>
            <dd>
              {r.travel.min_s != null || r.travel.max_s != null ? `${r.travel.min_s ?? 0}–${r.travel.max_s ?? "?"} s` : "unknown"} <span className="hint">({r.travel.source})</span>
            </dd>
            <dt>Topology certainty</dt>
            <dd>{Math.round(r.certainty * 100)}%</dd>
          </dl>
        )}
      </div>
    </Panel>
  );
}

function SettingsForm() {
  const q = useQuery({ queryKey: ["crosscam-settings"], queryFn: loc.settings });
  const [s, setS] = useState<CrossCameraSettings | null>(null);
  const [hours, setHours] = useState(24);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    if (q.data) setS(q.data.settings);
  }, [q.data]);
  const save = useMutation({ mutationFn: () => loc.saveSettings(s!), onSuccess: () => { void q.refetch(); setMsg("Saved."); } });
  const recorrelate = useMutation({ mutationFn: () => loc.correlate({ hours }), onSuccess: (r) => setMsg(`Correlated ${r.runs.length} run(s): ${r.transitions} transitions, ${r.withdrawn} withdrawn, ${r.deviations} deviations.`) });
  if (!s) return <Panel><div className="hint">Loading…</div></Panel>;
  const can = q.data?.viewer.can.settings;
  const bool = (k: keyof CrossCameraSettings, label: string, help?: string) => (
    <label className="row small" style={{ gap: 6 }} title={help}>
      <input type="checkbox" checked={Boolean(s[k])} onChange={(e) => setS({ ...s, [k]: e.target.checked })} disabled={!can} /> {label}
    </label>
  );
  const numf = (k: keyof CrossCameraSettings, label: string, help: string, step = 1) => (
    <Field label={label} help={help}>
      <input type="number" step={step} value={Number(s[k])} onChange={(e) => setS({ ...s, [k]: Number(e.target.value) })} disabled={!can} style={{ width: 110 }} />
    </Field>
  );
  return (
    <div className="stack">
      <Panel title="Cross-camera correlation">
        <div className="stack" style={{ gap: 10 }}>
          {!can && <Notice tone="warn">Changing these settings needs the settings role (or this computer while no recognition token exists).</Notice>}
          {bool("enabled", "Correlate recognized people and plates across cameras")}
          <Field label="Identity links used" help="Weaker identity links never join two sightings.">
            <select value={s.min_identity_state} onChange={(e) => setS({ ...s, min_identity_state: e.target.value as "likely" })} disabled={!can}>
              <option value="likely">Likely or confirmed</option>
              <option value="confirmed">Confirmed only</option>
            </select>
          </Field>
          <div className="row wrap" style={{ gap: 12 }}>
            {numf("lookback_hours", "Look back (h)", "How far back the previous sighting may be.")}
            {numf("journey_break_s", "New journey after (s)", "A longer gap between sightings starts a new journey.")}
            {numf("overlap_tolerance_s", "Hand-over tolerance (s)", "How early the next camera may see the entity (clocks, hand-over).")}
            {numf("default_max_s", "Assumed longest travel (s)", "Where the topology gives no time.")}
            {numf("too_fast_factor", "Implausible below", "Share of the shortest expected time.", 0.05)}
          </div>
          {bool("anonymous", "Also link anonymous tracks by timing alone", "Only between directly connected cameras with a known travel time, only when exactly one candidate fits on both sides, never above 'possible'.")}
          {bool("anomalies", "Report topology deviations (implausible timing, unknown connection, one-way, restricted place without entry, unusual camera sequence)")}
          {bool("publish_anomalies", "Also record them as events of the destination run")}
          <div className="row wrap" style={{ gap: 12 }}>
            {numf("history_min_journeys", "Earlier journeys needed", "Before a camera sequence can be called unusual.")}
            {numf("history_rare_share", "Unusual below share", "Of earlier journeys with the same move.", 0.05)}
          </div>
          {can && (
            <button className="btn primary sm" onClick={() => save.mutate()} disabled={save.isPending} style={{ alignSelf: "flex-start" }}>
              Save settings
            </button>
          )}
          {save.isError && <ErrorNotice error={save.error} />}
        </div>
      </Panel>
      <Panel title="Correlate again">
        <div className="row wrap" style={{ gap: 8, alignItems: "flex-end" }}>
          <Field label="Runs of the last (hours)">
            <input type="number" min={1} max={2160} value={hours} onChange={(e) => setHours(Number(e.target.value))} style={{ width: 90 }} />
          </Field>
          <button className="btn sm" onClick={() => recorrelate.mutate()} disabled={recorrelate.isPending}>
            {recorrelate.isPending ? "Correlating…" : "Correlate again"}
          </button>
          <span className="hint">After changing the topology: results are recomputed (unsupported moves are withdrawn and kept for the record).</span>
        </div>
        {recorrelate.isError && <ErrorNotice error={recorrelate.error} />}
      </Panel>
      {msg && <Notice tone="ok">{msg}</Notice>}
    </div>
  );
}
