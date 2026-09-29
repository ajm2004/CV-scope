/* Client and types of the Relationship & Event Correlation Engine (/api/relationships).
 *
 * Every request carries this browser's recognition token when it has one, so
 * the server can decide whether names and plates may be shown. Without a
 * token, identities come back as "Recognized person" with no key. */

import { ApiError } from "../api/client";
import type { RuleSubject } from "../api/types";
import { recognitionToken } from "../lib/recognitionToken";

export type StateName = "confirmed" | "likely" | "possible" | "insufficient";

export interface EntityOut {
  id: number | null;
  key: string | null;
  type: string;
  type_label: string;
  category: string;
  sensitive: boolean;
  label: string;
  redacted: boolean;
  run_id?: number | null;
  camera_id?: number | null;
  experiment_id?: number | null;
  confidence?: number | null;
  first_seen?: string | null;
  last_seen?: string | null;
  first_media_s?: number | null;
  last_media_s?: number | null;
  meta?: Record<string, unknown>;
  identity?: { id: number; key: string; type: string; label: string };
}

export interface Components {
  tracking?: number | null;
  recognition?: number | null;
  spatial?: number | null;
  temporal?: number | null;
  sensor?: number | null;
  support?: number;
  /** Cross-camera moves: "annotation" when a reviewer, not a recognition module, identified the sightings */
  identity_method?: string;
}

export interface RelationshipOut {
  id: number;
  uid: string;
  type: string;
  label: string;
  category: string;
  subject: EntityOut | null;
  object: EntityOut | null;
  start_at: string;
  end_at: string | null;
  start_media_s: number | null;
  end_media_s: number | null;
  status: "open" | "closed";
  confidence: number;
  state: StateName;
  state_label: string;
  components: Components;
  rule: { key: string; version: number; name: string };
  reason: string;
  zone_id: string | null;
  sources: string[];
  calibration: { mode?: string; unit?: string; unit_label?: string; measure?: string; scene_version?: number | null; footprint?: string };
  metrics: Record<string, unknown>;
  run_id: number | null;
  camera_id: number | null;
  experiment_id: number | null;
  analysis_id: number | null;
  via?: EntityOut | null;
  direction?: "outgoing" | "incoming";
}

export interface ObservationOut {
  id: number;
  uid: string;
  type: string;
  label: string;
  entity: EntityOut | null;
  object: EntityOut | null;
  at: string;
  media_time_s: number | null;
  source: string;
  confidence: number | null;
  value: Record<string, unknown>;
  run_id: number | null;
  camera_id: number | null;
}

export interface CorrelatedOut {
  id: number;
  uid: string;
  kind: "correlated" | "deviation";
  label: string;
  start_at: string;
  end_at: string | null;
  start_media_s: number | null;
  end_media_s: number | null;
  confidence: number;
  state: StateName;
  state_label: string;
  description: string;
  rule: { key: string; version: number; name: string };
  roles: Record<string, EntityOut | null>;
  temporal: { a: string; relation: string; b: string; gap_s: number; step: number }[];
  metrics: Record<string, unknown>;
  run_id: number | null;
  camera_id: number | null;
  experiment_id: number | null;
  published: boolean;
}

export interface RelationshipDetail extends RelationshipOut {
  evidence: { observations: ObservationOut[]; relationships: RelationshipOut[] };
  cited_by: { relationships: RelationshipOut[]; correlated: CorrelatedOut[] };
  rule_definition: RuleDefinition | null;
  rule_summary: string | null;
  analysis: { id: number; source: string; current: boolean; status: string } | null;
}

export interface CorrelatedDetail extends CorrelatedOut {
  evidence: { observations: ObservationOut[]; relationships: RelationshipOut[] };
  rule_definition: RuleDefinition | null;
}

export interface RelatedGroup {
  entity: EntityOut;
  relationships: RelationshipOut[];
  types: Record<string, number>;
  best_confidence: number;
  last_at: string | null;
  sessions: number;
}

export interface Neighbors {
  entity: EntityOut;
  aliases: EntityOut[];
  related: RelatedGroup[];
  count: number;
}

export interface GraphNode extends EntityOut {
  node: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
  count: number;
  best_confidence: number;
  state: StateName;
  ids: number[];
}

export interface Subgraph {
  center: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface TimelineItem {
  kind: "observation" | "relationship" | "correlated";
  id: number;
  type: string;
  at: string;
  end_at?: string | null;
  media_time_s: number | null;
  end_media_s?: number | null;
  run_id: number | null;
  camera_id: number | null;
  text: string;
  description?: string;
  parts: { subject: string; verb: string; object: string; extra: string };
  state?: StateName;
  confidence?: number | null;
  source?: string;
  roles?: Record<string, string>;
}

export interface History {
  entity: EntityOut;
  sessions: number;
  tracks: number;
  first_seen: string | null;
  last_seen: string | null;
  cameras: { camera_id: number; count: number }[];
  associated: { entity: EntityOut; sessions: number; types: Record<string, number>; best_confidence: number }[];
  entries: { entity: EntityOut; count: number }[];
  parking: { entity: EntityOut; count: number }[];
  routes: { entity: EntityOut; count: number }[];
  stays: { entity: EntityOut; count: number }[];
  moves: { from: EntityOut; to: EntityOut; count: number }[];
}

export interface SummarySentence {
  span: string;
  text: string;
  start: string;
  end: string;
  run_id: number | null;
  media_time_s: number | null;
}

export interface SummaryOut {
  deterministic: { text: string; sentences: SummarySentence[]; facts: number; clock: "wall" | "media" };
  model: { text: string; provider: string; model: string; based_on: string } | null;
}

export interface RelationTypeInfo {
  id: string;
  label: string;
  inverse: string;
  category: string;
  symmetric: boolean;
  description: string;
  inferable: boolean;
  external_only: boolean;
  builtin: boolean;
}

export interface EntityTypeInfo {
  id: string;
  label: string;
  category: string;
  sensitive: boolean;
  description: string;
}

export interface ViewerInfo {
  name: string;
  role: string;
  sees_identities: boolean;
  can: { graph: boolean; export: boolean; export_identity: boolean; rules: boolean; delete: boolean; settings: boolean };
}

export interface Template {
  id: string;
  title: string;
  definition: RuleDefinition;
}

export interface Meta {
  entity_types: EntityTypeInfo[];
  relation_types: RelationTypeInfo[];
  observation_types: { id: string; label: string; description: string }[];
  states: { id: StateName; label: string; min: number }[];
  templates: Template[];
  viewer: ViewerInfo;
}

// ---------------------------------------------------------------- rules
export interface RoleFilter {
  classes: string[];
  subject: RuleSubject;
}

export interface DistanceSpec {
  value: number;
  unit: "m" | "fw";
  fallback_fw?: number | null;
}

export interface ExtraCondition {
  kind: "in_zone" | "not_in_zone" | "speed_below" | "speed_above";
  role: "subject" | "object" | "both";
  zone_ids: string[];
  value?: number | null;
  value_fw?: number | null;
}

export interface SequenceStep {
  role: "A" | "B" | "both";
  what: "relation" | "place" | "appears" | "disappears" | "event";
  relation?: string | null;
  any_direction?: boolean;
  place_event?: "enters" | "exits" | "crosses" | "uses_route" | null;
  places?: string[];
  event_type?: string | null;
  within_s?: number | null;
  together_s?: number;
  min_state?: StateName;
}

export type RuleKind = "pair" | "place" | "follow_route" | "sequence";
export type PairCondition = "near" | "approaches" | "moves_away" | "moves_together" | "follows" | "disappears_near" | "appears_near" | "stopped_near";
export type PlaceEvent = "enters" | "exits" | "crosses" | "uses_route" | "remains_in" | "stops_in" | "moves_between";

export interface RuleDefinition {
  kind: RuleKind;
  name: string;
  description?: string;
  enabled?: boolean;
  subject: RoleFilter;
  object?: RoleFilter | null;
  condition?: PairCondition | null;
  distance?: DistanceSpec | null;
  from_distance?: DistanceSpec | null;
  for_s?: number;
  gap_s?: number;
  min_speed?: number;
  min_speed_fw?: number;
  stop_speed?: number;
  stop_speed_fw?: number;
  max_heading_deg?: number;
  lag_min_s?: number;
  lag_max_s?: number;
  conditions?: ExtraCondition[];
  place_event?: PlaceEvent | null;
  places?: string[];
  to_places?: string[];
  min_checkpoints?: number;
  max_lag_s?: number;
  steps?: SequenceStep[];
  window_s?: number;
  relation?: string | null;
  event_label?: string | null;
  act_min_state?: StateName;
  actions?: { kind: "record_event" | "webhook"; url?: string | null }[];
}

export interface RuleOut {
  key: string;
  version: number;
  name: string;
  kind: RuleKind;
  definition: RuleDefinition;
  summary: string;
  note: string;
  created_by: string;
  created_at: string;
  archived: boolean;
  versions: number | null;
  used_by: { experiment_id: number; name: string; version: number | null; enabled: boolean }[] | null;
}

export interface Analysis {
  id: number;
  run_id: number;
  experiment_id: number | null;
  camera_id: number | null;
  source: "live" | "replay";
  status: "running" | "done" | "failed";
  current: boolean;
  rules: { key: string; version: number; name: string; kind: string }[];
  settings: Record<string, unknown>;
  calibration: { mode?: string; unit?: string; measure?: string; scene_version?: number | null };
  stats: Record<string, unknown>;
  error: string | null;
  created_by: string;
  started_at: string;
  finished_at: string | null;
  job: { progress: number; state: string } | null;
}

export interface RelationshipSettings {
  access: { graph_role: string; identity_role: string; export_role: string; export_identity_role: string; rules_role: string; delete_role: string; settings_role: string };
  modules: { face: boolean; plate: boolean; sensors: boolean };
  retention: { days: number; identity_days: number; audit_days: number };
  custom_types: { id: string; label: string; inverse: string; symmetric: boolean; description: string; external_only: boolean }[];
  llm_summaries: boolean;
}

export interface Expectation {
  id: string;
  name: string;
  enabled: boolean;
  subject: RoleFilter;
  relation: "ENTERED" | "CROSSED" | "USED_ROUTE" | "PARKED_IN" | "REMAINED_IN";
  allowed_places: string[];
  forbidden_places: string[];
}

export interface RelationExperimentSettings {
  enabled: boolean;
  rules: { key: string; version: number | null }[];
  identity: boolean;
  places: boolean;
  occupied: boolean;
  remained_min_s: number;
  transition_s: number;
  sample_s: number;
  max_tracks: number;
  expectations: Expectation[];
  learn_patterns: boolean;
  pattern_min_sessions: number;
  pattern_rare_share: number;
  publish_deviations: boolean;
}

export const DEFAULT_RELATIONS: RelationExperimentSettings = {
  enabled: false,
  rules: [],
  identity: true,
  places: true,
  occupied: false,
  remained_min_s: 10,
  transition_s: 30,
  sample_s: 0.2,
  max_tracks: 60,
  expectations: [],
  learn_patterns: true,
  pattern_min_sessions: 5,
  pattern_rare_share: 0.1,
  publish_deviations: true,
};

export interface AuditRow {
  id: number;
  at: string;
  actor: string;
  actor_role: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  detail: Record<string, unknown>;
  client: string | null;
}

export interface Filters {
  types?: string;
  time_from?: string;
  time_to?: string;
  camera_id?: number;
  experiment_id?: number;
  run_id?: number;
  zone_id?: string;
  min_state?: StateName;
  analysis_id?: number;
  include_superseded?: boolean;
  last_hours?: number;
  location_id?: number;
}

// ---------------------------------------------------------------- transport
export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const token = recognitionToken();
  if (token) headers["X-Recognition-Token"] = token;
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail ?? j;
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function qs(params: Record<string, unknown>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

const BASE = "/api/relationships";

/** Download with the token (exports may include identities). */
export async function download(path: string, filename: string): Promise<void> {
  const headers: Record<string, string> = {};
  const token = recognitionToken();
  if (token) headers["X-Recognition-Token"] = token;
  const res = await fetch(path, { headers });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

export const rel = {
  meta: () => request<Meta>("GET", `${BASE}/meta`),
  overview: (f: Filters = {}) => request<{ relationships: Record<string, number>; correlated: Record<string, number>; entities: Record<string, number>; analyses: number; rules: number; viewer: ViewerInfo }>("GET", `${BASE}/overview${qs({ ...f })}`),
  settings: () => request<{ settings: RelationshipSettings; viewer: ViewerInfo }>("GET", `${BASE}/settings`),
  saveSettings: (s: RelationshipSettings) => request<{ settings: RelationshipSettings }>("PUT", `${BASE}/settings`, s),
  audit: (limit = 200) => request<AuditRow[]>("GET", `${BASE}/audit${qs({ limit })}`),
  // rules
  rules: (archived = false) => request<RuleOut[]>("GET", `${BASE}/rules${qs({ archived })}`),
  rule: (key: string) => request<{ latest: RuleOut; versions: RuleOut[] }>("GET", `${BASE}/rules/${encodeURIComponent(key)}`),
  createRule: (definition: RuleDefinition, note = "") => request<RuleOut>("POST", `${BASE}/rules`, { definition, note }),
  saveRule: (key: string, definition: RuleDefinition, note = "") => request<RuleOut>("PUT", `${BASE}/rules/${encodeURIComponent(key)}`, { definition, note }),
  archiveRule: (key: string, archived: boolean) => request<{ key: string; archived: boolean }>("POST", `${BASE}/rules/${encodeURIComponent(key)}/archive${qs({ archived })}`),
  validateRule: (definition: RuleDefinition) => request<{ ok: boolean; summary: string; definition: RuleDefinition }>("POST", `${BASE}/rules/validate`, { definition }),
  // analyses
  analyses: (params: { run_id?: number; experiment_id?: number }) => request<Analysis[]>("GET", `${BASE}/analyses${qs(params)}`),
  analysis: (id: number) => request<Analysis>("GET", `${BASE}/analyses/${id}`),
  analyse: (runId: number, rules: { key: string; version: number | null }[] | null = null) => request<Analysis>("POST", `${BASE}/runs/${runId}/analyse`, { rules }),
  makeCurrent: (id: number) => request<Analysis>("POST", `${BASE}/analyses/${id}/current`),
  removeAnalysis: (id: number) => request<void>("DELETE", `${BASE}/analyses/${id}`),
  // graph
  entities: (params: { type?: string; q?: string; run_id?: number; experiment_id?: number; camera_id?: number; limit?: number }) => request<EntityOut[]>("GET", `${BASE}/entities${qs(params)}`),
  entity: (key: string) => request<EntityOut>("GET", `${BASE}/entity${qs({ key })}`),
  neighbors: (key: string, f: Filters = {}) => request<Neighbors>("GET", `${BASE}/entity/neighbors${qs({ key, ...f })}`),
  graph: (key: string, depth = 1, f: Filters = {}) => request<Subgraph>("GET", `${BASE}/entity/graph${qs({ key, depth, ...f })}`),
  history: (key: string, f: Filters = {}) => request<History>("GET", `${BASE}/entity/history${qs({ key, ...f })}`),
  list: (f: Filters & { subject_type?: string; object_type?: string; limit?: number; offset?: number } = {}) => request<{ items: RelationshipOut[]; count: number }>("GET", `${BASE}/list${qs({ ...f })}`),
  relationship: (id: number) => request<RelationshipDetail>("GET", `${BASE}/relationship/${id}`),
  correlated: (f: Filters & { kind?: string; limit?: number } = {}) => request<CorrelatedOut[]>("GET", `${BASE}/correlated${qs({ ...f })}`),
  correlatedDetail: (id: number) => request<CorrelatedDetail>("GET", `${BASE}/correlated/${id}`),
  timeline: (params: Filters & { key?: string; limit?: number }) => request<{ items: TimelineItem[]; entity: EntityOut | null }>("GET", `${BASE}/timeline${qs({ ...params })}`),
  summary: (body: { key?: string; run_id?: number; experiment_id?: number; camera_id?: number; time_from?: string; time_to?: string; min_state?: StateName; tz_offset_min: number; llm?: boolean }) =>
    request<SummaryOut>("POST", `${BASE}/summary`, body),
  search: (params: Filters & { kind: string; key?: string; target?: string; zone_key?: string; window_s?: number }) => request<Record<string, unknown> & { items: unknown[] }>("GET", `${BASE}/search${qs({ ...params })}`),
  exportUrl: (f: Filters & { format: "csv" | "json"; identities?: boolean }) => `${BASE}/export${qs({ ...f })}`,
};

/** Minutes to add to UTC for this browser's clock (summaries are written server-side). */
export function tzOffsetMin(): number {
  return -new Date().getTimezoneOffset();
}
