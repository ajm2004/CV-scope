/* Client and types of the Location Engine and cross-camera correlation
 * (/api/locations) and of the visual graph (/api/relationships/visual). */

import { qs, request, type EntityOut, type Filters, type StateName, type ViewerInfo, type Components } from "../relationships/api";

export type NodeKind =
  | "organization" | "site" | "building" | "floor" | "area" | "room" | "corridor" | "entrance" | "gate" | "zone" | "parking" | "loading" | "stairs"
  | "road_network" | "road" | "junction" | "camera" | "sensor" | "other";

export interface Layout {
  mode: "plan" | "schematic" | "map";
  width: number;
  height: number;
  unit: "m" | "units";
  image?: string | null;
  bounds?: { north: number; south: number; east: number; west: number } | null;
}

export interface LocNode {
  id: number;
  parent_id: number | null;
  project_id: number | null;
  kind: NodeKind;
  kind_label: string;
  group: string;
  name: string;
  description: string;
  camera_id: number | null;
  sensor_id: string | null;
  x: number | null;
  y: number | null;
  w: number | null;
  h: number | null;
  shape: number[][];
  lat: number | null;
  lon: number | null;
  level: number | null;
  orientation_deg: number | null;
  fov_deg: number | null;
  view_range: number | null;
  layout: Layout | null;
  is_entry: boolean;
  restricted: boolean;
  meta: Record<string, unknown>;
  frame_id: number | null;
  path: string;
  camera?: { id: number; name: string; source_type: string; project_id: number; enabled: boolean };
}

export type LinkKind = "CONNECTED_TO" | "ADJACENT_TO" | "LEADS_TO" | "VISIBLE_FROM" | "ABOVE" | "BELOW";

export interface LocLink {
  id: number;
  source_id: number;
  target_id: number;
  kind: LinkKind;
  one_way: boolean;
  travel_min_s: number | null;
  travel_max_s: number | null;
  via_id: number | null;
  shared_id: number | null;
  overlap: boolean;
  distance: number | null;
  notes: string;
}

export interface LocGraph {
  nodes: LocNode[];
  edges: ({ source: number; target: number; kind: string; derived: boolean } & Partial<LocLink>)[];
  zone_links: { camera_id: number; object_id: string; node_id: number }[];
  unplaced_cameras: { id: number; name: string; project_id: number }[];
}

export type NodeInput = Omit<LocNode, "id" | "kind_label" | "group" | "frame_id" | "path" | "camera">;
export type LinkInput = Omit<LocLink, "id">;

export interface NodeRef {
  id: number;
  name: string;
  kind: string;
  path: string;
  frame_id: number | null;
  x: number | null;
  y: number | null;
  restricted?: boolean;
  is_entry?: boolean;
}

export interface CameraRef {
  id: number | null;
  name: string;
  node: NodeRef | null;
}

export interface TopologyCheck {
  kind: "direct" | "overlap" | "path" | "unconnected" | "no_topology";
  path: number[];
  hops: number | null;
  wrong_way: boolean;
  via: number[];
  note: string;
  travel: { min_s: number | null; max_s: number | null; source: string };
  certainty: number;
  path_nodes: { id: number; name: string; kind: string }[];
}

export interface Transition {
  id: number;
  uid: string;
  basis: "face" | "plate" | "registered" | "anonymous";
  status: "active" | "withdrawn";
  subject: EntityOut | null;
  from: { camera: CameraRef; node: NodeRef | null; track: EntityOut | null; run_id: number | null; media_s: number | null; at: string };
  to: { camera: CameraRef; node: NodeRef | null; track: EntityOut | null; run_id: number | null; media_s: number | null; at: string };
  left_at: string;
  arrived_at: string;
  gap_s: number;
  expected: { min_s: number | null; max_s: number | null; source: string };
  topology: { kind: string; hops: number | null; path: NodeRef[] };
  identity_confidence: number | null;
  components: Components;
  confidence: number;
  state: StateName;
  state_label: string;
  sensors: { observation_id: number; sensor_id: string; node: string; at: string; kind: string; value: unknown }[];
  flags: string[];
  reason: string;
  relationships: { moved_from: number | null; moved_to: number | null };
  from_index?: number | null;
  to_index?: number | null;
}

export interface JourneyEvent {
  relationship_id: number;
  type: string;
  verb: string;
  place: string;
  node: NodeRef | null;
  at: string;
  end_at: string | null;
  media_s: number | null;
  end_media_s: number | null;
  state: StateName;
  confidence: number;
}

export interface Sighting {
  index: number;
  track: EntityOut;
  basis: string;
  identity_confidence: number | null;
  camera: CameraRef;
  run_id: number | null;
  experiment_id: number | null;
  object_class: string;
  first_at: string;
  last_at: string;
  first_media_s: number | null;
  last_media_s: number | null;
  entry: NodeRef | null;
  exit: NodeRef | null;
  node: NodeRef | null;
  events: JourneyEvent[];
  summary: string;
}

export interface Journey {
  entity: EntityOut;
  time_from: string;
  time_to: string;
  sightings: Sighting[];
  transitions: Transition[];
  path: { node: NodeRef; camera: CameraRef; at: string; index: number }[];
  cameras: number[];
}

export interface CrossCameraSettings {
  enabled: boolean;
  min_identity_state: "confirmed" | "likely";
  lookback_hours: number;
  journey_break_s: number;
  overlap_tolerance_s: number;
  default_max_s: number;
  too_fast_factor: number;
  anonymous: boolean;
  anonymous_max_candidates: number;
  anomalies: boolean;
  publish_anomalies: boolean;
  history_min_journeys: number;
  history_rare_share: number;
}

export interface LiveCamera {
  camera_id: number;
  name: string;
  node_id: number | null;
  run_id: number | null;
  experiment_id?: number;
  state: string | null;
  active_tracks: number;
  classes: Record<string, number>;
  zones: Record<string, number>;
  media_time_s?: number;
}

export interface Live {
  at: string;
  cameras: LiveCamera[];
  events: { id: number; run_id: number; camera_id: number; event_type: string; label: string; object_class: string; track_id: number; at: string; media_time_s: number }[];
  alerts: { source: "relationships" | "anomaly"; camera_id: number | null; at: string; label: string; text: string; state: StateName | null; id: number; run_id: number | null }[];
  transitions: Transition[];
  present: { camera_id: number; track: EntityOut; identity: EntityOut | null; last_seen: string }[];
}

// ---------------------------------------------------------------- visual graph
export type EdgeNature = "observed" | "identity" | "inferred" | "cross_camera" | "external" | "context";
export type NodeClass = "track" | "identity" | "place" | "location" | "camera" | "sensor" | "event" | "context";

export interface VInterval {
  id: number | null;
  start: string | null;
  end: string | null;
  start_media_s: number | null;
  end_media_s: number | null;
  state: StateName;
  confidence: number;
  run_id: number | null;
  camera_id: number | null;
}

export interface VNode extends EntityOut {
  node: string;
  klass: NodeClass;
  expandable: boolean;
  location?: { id: number; name: string; path: string } | null;
}

export interface VEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  label: string;
  nature: EdgeNature;
  sensor: boolean;
  derived: boolean;
  count: number;
  best_confidence: number;
  state: StateName;
  ids: number[];
  intervals: VInterval[];
  first_at: string | null;
  last_at: string | null;
  merged: boolean;
}

export interface VGraph {
  center: string | null;
  nodes: VNode[];
  edges: VEdge[];
  time_range: { start: string | null; end: string | null };
  counts: Record<string, number>;
  projected: boolean;
  truncated: boolean;
}

export interface VPath extends VGraph {
  found: boolean;
  path_nodes: string[];
  path_edges: string[];
  depth: number;
}

const BASE = "/api/locations";
const REL = "/api/relationships";

export const loc = {
  meta: () => request<{ node_kinds: { id: NodeKind; label: string; group: string }[]; link_kinds: { id: LinkKind; description: string }[]; viewer: ViewerInfo }>("GET", `${BASE}/meta`),
  graph: (root_id?: number) => request<LocGraph>("GET", `${BASE}/graph${qs({ root_id })}`),
  createNode: (n: Partial<NodeInput>) => request<LocNode>("POST", `${BASE}/nodes`, n),
  updateNode: (id: number, n: Partial<NodeInput>) => request<LocNode>("PUT", `${BASE}/nodes/${id}`, n),
  deleteNode: (id: number) => request<void>("DELETE", `${BASE}/nodes/${id}`),
  positions: (items: { id: number; x?: number | null; y?: number | null; w?: number | null; h?: number | null }[]) => request<{ updated: number }>("PUT", `${BASE}/positions`, items),
  createLink: (l: Partial<LinkInput>) => request<LocLink>("POST", `${BASE}/links`, l),
  updateLink: (id: number, l: Partial<LinkInput>) => request<LocLink>("PUT", `${BASE}/links/${id}`, l),
  deleteLink: (id: number) => request<void>("DELETE", `${BASE}/links/${id}`),
  check: (p: { from_camera: number; to_camera: number; object_class?: string }) => request<TopologyCheck>("GET", `${BASE}/check${qs(p)}`),
  cameraZones: (cameraId: number) =>
    request<{ camera: { id: number; name: string }; scene_version: number | null; items: { object_id: string; name: string; type: string; object_kind: "zone" | "line" | "route"; node_id: number | null }[] }>(
      "GET",
      `${BASE}/cameras/${cameraId}/zones`,
    ),
  setCameraZones: (cameraId: number, items: { object_id: string; object_kind: string; node_id: number | null }[]) => request<unknown>("PUT", `${BASE}/cameras/${cameraId}/zones`, items),
  imageUrl: (nodeId: number, name: string) => `${BASE}/nodes/${nodeId}/image?v=${encodeURIComponent(name)}`,
  deleteImage: (nodeId: number) => request<void>("DELETE", `${BASE}/nodes/${nodeId}/image`),
  settings: () => request<{ settings: CrossCameraSettings; viewer: ViewerInfo }>("GET", `${BASE}/settings`),
  saveSettings: (s: CrossCameraSettings) => request<{ settings: CrossCameraSettings }>("PUT", `${BASE}/settings`, s),
  correlate: (body: { run_ids?: number[]; hours?: number; time_from?: string; time_to?: string }) =>
    request<{ transitions: number; withdrawn: number; relationships: number; deviations: number; subjects: number; runs: number[] }>("POST", `${BASE}/correlate`, body),
  transitions: (p: { time_from?: string; time_to?: string; location_id?: number; camera_id?: number; run_id?: number; key?: string; min_state?: StateName; flagged?: boolean; limit?: number }) =>
    request<Transition[]>("GET", `${BASE}/transitions${qs(p)}`),
  transition: (id: number) => request<Transition & { deviations: import("../relationships/api").CorrelatedOut[] }>("GET", `${BASE}/transitions/${id}`),
  journey: (key: string, p: { time_from?: string; time_to?: string } = {}) => request<Journey>("GET", `${BASE}/journey${qs({ key, ...p })}`),
  lastSeen: (key: string) => request<{ entity: EntityOut; last: { track: EntityOut; camera: CameraRef; node: NodeRef | null; at: string; media_s: number | null; run_id: number | null } | null }>("GET", `${BASE}/last-seen${qs({ key })}`),
  deviations: (p: { location_id?: number; time_from?: string; limit?: number }) => request<import("../relationships/api").CorrelatedOut[]>("GET", `${BASE}/deviations${qs(p)}`),
  live: (root_id?: number, minutes = 15) => request<Live>("GET", `${BASE}/live${qs({ root_id, minutes })}`),
  // visual graph (relationship API)
  visual: (p: Filters & { key?: string; depth?: number; project?: boolean; context?: boolean; max_edges?: number }) => request<VGraph>("GET", `${REL}/visual${qs({ ...p })}`),
  path: (p: Filters & { from_key: string; to_key: string; max_depth?: number; project?: boolean }) => request<VPath>("GET", `${REL}/visual/path${qs({ ...p })}`),
};

export async function uploadImage(nodeId: number, file: File): Promise<LocNode> {
  const { recognitionToken } = await import("../lib/recognitionToken");
  const fd = new FormData();
  fd.append("file", file);
  const headers: Record<string, string> = {};
  const token = recognitionToken();
  if (token) headers["X-Recognition-Token"] = token;
  const res = await fetch(`${BASE}/nodes/${nodeId}/image`, { method: "POST", body: fd, headers });
  if (!res.ok) {
    const { ApiError } = await import("../api/client");
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as LocNode;
}

export const LINK_LABEL: Record<string, string> = {
  CONNECTED_TO: "connected to",
  ADJACENT_TO: "adjacent to",
  LEADS_TO: "leads to",
  VISIBLE_FROM: "visible from",
  ABOVE: "above",
  BELOW: "below",
  INSIDE: "inside",
};

export const FLAG_LABEL: Record<string, string> = {
  implausible_time: "Implausibly fast",
  faster_than_expected: "Faster than expected",
  slower_than_expected: "Slower than expected",
  unconnected: "No known connection",
  wrong_way: "Against a one-way link",
  simultaneous: "Seen on both cameras at once",
};

export const BASIS_LABEL: Record<string, string> = { face: "Face recognition", plate: "Plate recognition", registered: "Registered vehicle", anonymous: "Timing only (anonymous)" };
