/* Structured editor of one relationship rule. Reads like the rule:
 *
 *   WHEN   <subject>   <condition>   <object>   DISTANCE 2 m   FOR 5 s
 *   AND    <extra conditions>
 *   CREATE RELATIONSHIP  ASSOCIATED_WITH   [CREATE EVENT  "…"]
 *
 * An "Advanced" tab shows the same rule as JSON for more expressive edits. */

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { SceneObject } from "../api/types";
import { ANY_SUBJECT } from "../api/types";
import { ClassPicker, ErrorNotice, Field, Notice, Tabs } from "../components/ui";
import { CLASS_OPTIONS } from "../lib/format";
import { useRecognitionAuth } from "../lib/recognitionToken";
import SubjectClause, { type RecognitionContext } from "../rule-builder/SubjectClause";
import { rel, type DistanceSpec, type ExtraCondition, type PairCondition, type PlaceEvent, type RoleFilter, type RuleDefinition, type RuleKind, type SequenceStep, type StateName } from "./api";
import { useMeta } from "./bits";

export const KIND_LABEL: Record<RuleKind, string> = {
  pair: "Two entities in space (near, approach, together, follow…)",
  place: "An entity and a place (enters, parks, remains…)",
  follow_route: "One follows another through checkpoints",
  sequence: "A sequence of steps (correlation)",
};

const CONDITIONS: { id: PairCondition; label: string; relation: string }[] = [
  { id: "near", label: "is within … of", relation: "NEAR" },
  { id: "approaches", label: "approaches", relation: "APPROACHED" },
  { id: "moves_away", label: "moves away from", relation: "MOVED_AWAY_FROM" },
  { id: "moves_together", label: "moves together with", relation: "TRAVELLED_WITH" },
  { id: "follows", label: "follows (same path, some seconds behind)", relation: "FOLLOWED" },
  { id: "stopped_near", label: "stops within … of", relation: "STOPPED_NEAR" },
  { id: "disappears_near", label: "disappears right beside (e.g. gets into)", relation: "ENTERED_VEHICLE" },
  { id: "appears_near", label: "appears right beside (e.g. gets out of)", relation: "EXITED_VEHICLE" },
];

const PLACE_EVENTS: { id: PlaceEvent; label: string; relation: string }[] = [
  { id: "enters", label: "enters", relation: "ENTERED" },
  { id: "exits", label: "exits", relation: "EXITED" },
  { id: "crosses", label: "crosses", relation: "CROSSED" },
  { id: "uses_route", label: "completes route", relation: "USED_ROUTE" },
  { id: "remains_in", label: "remains in", relation: "REMAINED_IN" },
  { id: "stops_in", label: "stands still in (parks)", relation: "PARKED_IN" },
  { id: "moves_between", label: "moves from … to …", relation: "MOVED_TO" },
];

const PERSON = { classes: ["person"], subject: { ...ANY_SUBJECT } };
const VEHICLE = { classes: ["car", "truck", "bus", "motorcycle"], subject: { ...ANY_SUBJECT } };

export function blankRule(kind: RuleKind): RuleDefinition {
  if (kind === "pair") return { kind, name: "", subject: PERSON, object: VEHICLE, condition: "near", distance: { value: 2, unit: "m", fallback_fw: 0.06 }, for_s: 5, relation: "ASSOCIATED_WITH", act_min_state: "likely", actions: [] };
  if (kind === "place") return { kind, name: "", subject: VEHICLE, place_event: "stops_in", for_s: 30, places: [], relation: "PARKED_IN", act_min_state: "likely", actions: [] };
  if (kind === "follow_route") return { kind, name: "", subject: PERSON, object: PERSON, min_checkpoints: 3, max_lag_s: 20, window_s: 60, relation: "FOLLOWED", act_min_state: "likely", actions: [] };
  return { kind, name: "", subject: PERSON, object: VEHICLE, window_s: 120, steps: [{ role: "A", what: "relation", relation: "ASSOCIATED_WITH", min_state: "likely" }, { role: "B", what: "disappears", within_s: 60 }], relation: "DEPARTED_WITH", event_label: "", act_min_state: "likely", actions: [] };
}

function num(v: string, fallback: number | null = null): number | null {
  if (v.trim() === "") return fallback;
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function Distance({ value, onChange, label }: { value: DistanceSpec | null | undefined; onChange: (d: DistanceSpec | null) => void; label: string }) {
  const d = value ?? { value: 2, unit: "m" as const, fallback_fw: null };
  return (
    <div className="clause">
      <span className="kw">{label}</span>
      <span className="row wrap">
        <input type="number" min={0.01} step={0.1} value={d.value} onChange={(e) => onChange({ ...d, value: num(e.target.value, d.value) ?? d.value })} style={{ width: 80 }} />
        <select value={d.unit} onChange={(e) => onChange({ ...d, unit: e.target.value as "m" | "fw" })} style={{ width: 130 }}>
          <option value="m">metres</option>
          <option value="fw">frame widths</option>
        </select>
        {d.unit === "m" && (
          <>
            <span className="small muted">without calibration:</span>
            <input type="number" min={0.001} step={0.01} value={d.fallback_fw ?? ""} placeholder="rule off" onChange={(e) => onChange({ ...d, fallback_fw: num(e.target.value) })} style={{ width: 80 }} />
            <span className="small muted">frame widths</span>
          </>
        )}
      </span>
    </div>
  );
}

function Role({ kw, value, onChange, recognition }: { kw: string; value: RoleFilter | null | undefined; onChange: (r: RoleFilter) => void; recognition: RecognitionContext }) {
  const r = value ?? { classes: [], subject: { ...ANY_SUBJECT } };
  return (
    <>
      <div className="clause">
        <span className="kw">{kw}</span>
        <ClassPicker value={r.classes} onChange={(classes) => onChange({ ...r, classes })} options={CLASS_OPTIONS} />
      </div>
      <SubjectClause classes={r.classes} subject={r.subject} onChange={(subject) => onChange({ ...r, subject })} ctx={recognition} />
    </>
  );
}

function PlacesPick({ value, onChange, objects, routes, label = "PLACES" }: { value: string[]; onChange: (v: string[]) => void; objects: { id: string; name: string; type: string }[]; routes?: boolean; label?: string }) {
  const options = objects;
  return (
    <div className="clause">
      <span className="kw">{label}</span>
      <div className="stack" style={{ gap: 4 }}>
        {options.length > 0 ? (
          <span className="row wrap" style={{ gap: 6 }}>
            {options.map((o) => (
              <label key={o.id} className="check">
                <input type="checkbox" checked={value.includes(o.id)} onChange={(e) => onChange(e.target.checked ? [...value, o.id] : value.filter((x) => x !== o.id))} />
                {o.name || o.id} <span className="hint">({o.type})</span>
              </label>
            ))}
          </span>
        ) : (
          <span className="hint">Choose a camera above to pick its {routes ? "routes" : "zones and lines"}, or type ids.</span>
        )}
        <input type="text" value={value.join(", ")} placeholder={routes ? "route ids (empty = any route)" : "scene object ids (empty = any)"} onChange={(e) => onChange(e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} />
      </div>
    </div>
  );
}

function Step({ step, index, onChange, onRemove, onMove, relations, objects, routes }: {
  step: SequenceStep; index: number; onChange: (s: SequenceStep) => void; onRemove: () => void; onMove: (d: -1 | 1) => void; relations: string[]; objects: { id: string; name: string; type: string }[]; routes: { id: string; name: string; type: string }[];
}) {
  return (
    <div className="rel-step">
      <div className="row wrap" style={{ gap: 6 }}>
        <strong>{index === 0 ? "WHEN" : "THEN"}</strong>
        <select value={step.role} onChange={(e) => onChange({ ...step, role: e.target.value as SequenceStep["role"] })} style={{ width: 90 }} disabled={step.what === "relation"}>
          <option value="A">A</option>
          <option value="B">B</option>
          <option value="both">A and B</option>
        </select>
        <select value={step.what} onChange={(e) => onChange({ ...step, what: e.target.value as SequenceStep["what"], relation: e.target.value === "relation" ? step.relation ?? "ASSOCIATED_WITH" : null, place_event: e.target.value === "place" ? step.place_event ?? "enters" : null })} style={{ width: 200 }}>
          <option value="relation">has relationship with B</option>
          <option value="place">place event</option>
          <option value="appears">appears</option>
          <option value="disappears">disappears</option>
          <option value="event">has an event</option>
        </select>
        {step.what === "relation" && (
          <>
            <select value={step.relation ?? ""} onChange={(e) => onChange({ ...step, relation: e.target.value })} style={{ width: 200 }}>
              {relations.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <span className="small muted">at least</span>
            <select value={step.min_state ?? "possible"} onChange={(e) => onChange({ ...step, min_state: e.target.value as StateName })} style={{ width: 110 }}>
              <option value="confirmed">confirmed</option>
              <option value="likely">likely</option>
              <option value="possible">possible</option>
            </select>
          </>
        )}
        {step.what === "place" && (
          <select value={step.place_event ?? "enters"} onChange={(e) => onChange({ ...step, place_event: e.target.value as SequenceStep["place_event"] })} style={{ width: 150 }}>
            <option value="enters">enters</option>
            <option value="exits">exits</option>
            <option value="crosses">crosses</option>
            <option value="uses_route">completes route</option>
          </select>
        )}
        {step.what === "event" && <input type="text" value={step.event_type ?? ""} placeholder="event type, e.g. anomaly" onChange={(e) => onChange({ ...step, event_type: e.target.value })} style={{ width: 170 }} />}
        {index > 0 && (
          <>
            <span className="small muted">within</span>
            <input type="number" min={1} value={step.within_s ?? ""} placeholder="∞" onChange={(e) => onChange({ ...step, within_s: num(e.target.value) })} style={{ width: 70 }} />
            <span className="small muted">s of the previous step</span>
          </>
        )}
        {step.role === "both" && (
          <>
            <span className="small muted">both within</span>
            <input type="number" min={1} value={step.together_s ?? 15} onChange={(e) => onChange({ ...step, together_s: num(e.target.value, 15) ?? 15 })} style={{ width: 60 }} />
            <span className="small muted">s of each other</span>
          </>
        )}
        <span className="grow" />
        <button className="btn sm ghost" onClick={() => onMove(-1)} disabled={index === 0} aria-label="Move up">
          ↑
        </button>
        <button className="btn sm ghost" onClick={() => onMove(1)} aria-label="Move down">
          ↓
        </button>
        <button className="btn sm ghost" onClick={onRemove}>
          Remove
        </button>
      </div>
      {step.what === "place" && (
        <div className="rule" style={{ marginTop: 6 }}>
          <PlacesPick value={step.places ?? []} onChange={(places) => onChange({ ...step, places })} objects={step.place_event === "uses_route" ? routes : objects} routes={step.place_event === "uses_route"} />
        </div>
      )}
    </div>
  );
}

export default function RuleEditor({ value, onChange }: { value: RuleDefinition; onChange: (d: RuleDefinition) => void }) {
  const meta = useMeta();
  const rtoken = useRecognitionAuth((s) => s.token);
  const [tab, setTab] = useState("form");
  const [json, setJson] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [cameraId, setCameraId] = useState<number | undefined>(undefined);
  const cameras = useQuery({ queryKey: ["cameras"], queryFn: () => api.cameras.list() });
  const scenes = useQuery({ queryKey: ["scenes", cameraId], queryFn: () => api.cameras.scenes(cameraId!), enabled: !!cameraId });
  const recStatus = useQuery({ queryKey: ["recognition-status"], queryFn: api.recognition.status, retry: 0, staleTime: 30_000 });
  const recPeople = useQuery({ queryKey: ["recognition-people"], queryFn: api.recognition.people, enabled: !!rtoken, retry: 0 });
  const recVehicles = useQuery({ queryKey: ["recognition-vehicles"], queryFn: api.recognition.vehicles, enabled: !!rtoken, retry: 0 });
  const recGroups = useQuery({ queryKey: ["recognition-vehicle-groups"], queryFn: api.recognition.vehicleGroups, enabled: !!rtoken, retry: 0 });
  const recognition: RecognitionContext = { status: recStatus.data, people: recPeople.data ?? [], vehicles: recVehicles.data ?? [], groups: recGroups.data ?? [], hasToken: !!rtoken };
  const doc = scenes.data?.[0]?.document;
  const objects = (doc?.objects ?? []).filter((o: SceneObject) => o.type !== "ignore").map((o: SceneObject) => ({ id: o.id, name: o.name, type: o.type }));
  const zones = objects.filter((o) => o.type === "zone" || o.type === "checkpoint");
  const routes = (doc?.routes ?? []).map((r) => ({ id: r.id, name: r.name, type: "route" }));
  const inferable = (meta.data?.relation_types ?? []).filter((t) => t.inferable && !t.external_only).map((t) => t.id);
  const allRelations = (meta.data?.relation_types ?? []).filter((t) => !t.external_only).map((t) => t.id);
  const d = value;
  const set = (patch: Partial<RuleDefinition>) => onChange({ ...d, ...patch });

  // live validation and the rule as a sentence
  const [check, setCheck] = useState<{ ok: boolean; summary?: string; error?: string } | null>(null);
  useEffect(() => {
    let cancel = false;
    const t = setTimeout(() => {
      rel.validateRule(d).then(
        (r) => !cancel && setCheck({ ok: true, summary: r.summary }),
        (e) => !cancel && setCheck({ ok: false, error: e instanceof Error ? e.message : String(e) }),
      );
    }, 350);
    return () => {
      cancel = true;
      clearTimeout(t);
    };
  }, [d]);

  const conditions = d.conditions ?? [];
  const setCondition = (i: number, c: ExtraCondition) => set({ conditions: conditions.map((x, j) => (j === i ? c : x)) });
  const steps = d.steps ?? [];

  return (
    <div className="stack" style={{ gap: 10 }}>
      <Tabs
        tabs={[
          { id: "form", label: "Rule" },
          { id: "json", label: "Advanced (JSON)" },
        ]}
        active={tab}
        onChange={(t) => {
          if (t === "json") {
            setJson(JSON.stringify(d, null, 2));
            setJsonError(null);
          }
          setTab(t);
        }}
      />
      {tab === "json" && (
        <div className="stack" style={{ gap: 6 }}>
          <textarea className="rel-json" value={json} onChange={(e) => setJson(e.target.value)} spellCheck={false} />
          {jsonError && <Notice tone="err">{jsonError}</Notice>}
          <div className="row">
            <button
              className="btn"
              onClick={() => {
                try {
                  onChange(JSON.parse(json) as RuleDefinition);
                  setJsonError(null);
                  setTab("form");
                } catch (e) {
                  setJsonError(e instanceof Error ? e.message : String(e));
                }
              }}
            >
              Use this JSON
            </button>
            <span className="hint">All fields of the rule format are available here (speeds, headings, lags, gap tolerance, several extra conditions, step options).</span>
          </div>
        </div>
      )}
      {tab === "form" && (
        <>
          <div className="row wrap" style={{ gap: 10 }}>
            <Field label="Name">
              <input type="text" value={d.name} onChange={(e) => set({ name: e.target.value })} placeholder="Person beside vehicle" style={{ minWidth: 260 }} />
            </Field>
            <Field label="Kind of rule">
              <select value={d.kind} onChange={(e) => onChange({ ...blankRule(e.target.value as RuleKind), name: d.name, description: d.description })}>
                {(Object.keys(KIND_LABEL) as RuleKind[]).map((k) => (
                  <option key={k} value={k}>
                    {KIND_LABEL[k]}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Pick places from camera" help="Only to choose zones, lines and routes by name">
              <select value={cameraId ?? ""} onChange={(e) => setCameraId(e.target.value ? Number(e.target.value) : undefined)}>
                <option value="">—</option>
                {cameras.data?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div className="rule">
            <Role kw={d.kind === "sequence" ? "ROLE A" : d.kind === "follow_route" ? "WHEN (follower)" : "WHEN"} value={d.subject} onChange={(subject) => set({ subject })} recognition={recognition} />
            {d.kind === "pair" && (
              <>
                <div className="clause">
                  <span className="kw">CONDITION</span>
                  <select
                    value={d.condition ?? "near"}
                    onChange={(e) => {
                      const c = CONDITIONS.find((x) => x.id === e.target.value)!;
                      const keepRelation = d.relation && !CONDITIONS.some((x) => x.relation === d.relation);
                      set({ condition: c.id, relation: keepRelation ? d.relation : c.relation, distance: d.distance ?? { value: 2, unit: "m", fallback_fw: 0.06 } });
                    }}
                    style={{ maxWidth: 360 }}
                  >
                    {CONDITIONS.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                </div>
                <Role kw="OF / OBJECT" value={d.object} onChange={(object) => set({ object })} recognition={recognition} />
                <Distance label={d.condition === "follows" ? "PATH WITHIN" : d.condition === "moves_away" ? "FROM WITHIN" : "DISTANCE"} value={d.distance} onChange={(distance) => set({ distance })} />
                {(d.condition === "approaches" || d.condition === "moves_away") && (
                  <Distance label={d.condition === "approaches" ? "STARTING AT LEAST" : "TO AT LEAST"} value={d.from_distance ?? { value: (d.distance?.value ?? 2) * 3, unit: d.distance?.unit ?? "m", fallback_fw: d.distance?.fallback_fw ? d.distance.fallback_fw * 3 : null }} onChange={(from_distance) => set({ from_distance })} />
                )}
                {!["approaches", "moves_away", "disappears_near", "appears_near"].includes(d.condition ?? "") && (
                  <div className="clause">
                    <span className="kw">FOR</span>
                    <span className="row">
                      <span className="small muted">at least</span>
                      <input type="number" min={0} value={d.for_s ?? 0} onChange={(e) => set({ for_s: num(e.target.value, 0) ?? 0 })} style={{ width: 80 }} />
                      <span className="small muted">seconds (short gaps up to</span>
                      <input type="number" min={0} step={0.5} value={d.gap_s ?? 1} onChange={(e) => set({ gap_s: num(e.target.value, 1) ?? 1 })} style={{ width: 60 }} />
                      <span className="small muted">s are tolerated)</span>
                    </span>
                  </div>
                )}
                {(d.condition === "approaches" || d.condition === "moves_away") && (
                  <div className="clause">
                    <span className="kw">WITHIN</span>
                    <span className="row">
                      <input type="number" min={1} value={d.window_s ?? 60} onChange={(e) => set({ window_s: num(e.target.value, 60) ?? 60 })} style={{ width: 80 }} />
                      <span className="small muted">seconds</span>
                    </span>
                  </div>
                )}
                {d.condition === "follows" && (
                  <div className="clause">
                    <span className="kw">BEHIND BY</span>
                    <span className="row">
                      <input type="number" min={0} step={0.5} value={d.lag_min_s ?? 1} onChange={(e) => set({ lag_min_s: num(e.target.value, 1) ?? 1 })} style={{ width: 60 }} />
                      <span className="small muted">to</span>
                      <input type="number" min={1} value={d.lag_max_s ?? 10} onChange={(e) => set({ lag_max_s: num(e.target.value, 10) ?? 10 })} style={{ width: 60 }} />
                      <span className="small muted">seconds</span>
                    </span>
                  </div>
                )}
                <div className="clause">
                  <span className="kw">AND</span>
                  <div className="stack" style={{ gap: 6 }}>
                    {conditions.map((c, i) => (
                      <div key={i} className="row wrap" style={{ gap: 6 }}>
                        <select value={c.role} onChange={(e) => setCondition(i, { ...c, role: e.target.value as ExtraCondition["role"] })} style={{ width: 110 }}>
                          <option value="both">both</option>
                          <option value="subject">the subject</option>
                          <option value="object">the object</option>
                        </select>
                        <select value={c.kind} onChange={(e) => setCondition(i, { ...c, kind: e.target.value as ExtraCondition["kind"] })} style={{ width: 150 }}>
                          <option value="in_zone">are in zone</option>
                          <option value="not_in_zone">are not in zone</option>
                          <option value="speed_below">move slower than</option>
                          <option value="speed_above">move faster than</option>
                        </select>
                        {c.kind === "in_zone" || c.kind === "not_in_zone" ? (
                          zones.length ? (
                            <select multiple value={c.zone_ids} onChange={(e) => setCondition(i, { ...c, zone_ids: [...e.target.selectedOptions].map((o) => o.value) })} style={{ minWidth: 160, height: 60 }}>
                              {zones.map((z) => (
                                <option key={z.id} value={z.id}>
                                  {z.name || z.id}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <input type="text" value={c.zone_ids.join(", ")} placeholder="zone ids" onChange={(e) => setCondition(i, { ...c, zone_ids: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} style={{ width: 180 }} />
                          )
                        ) : (
                          <>
                            <input type="number" min={0} step={0.1} value={c.value ?? ""} placeholder="m/s" onChange={(e) => setCondition(i, { ...c, value: num(e.target.value) })} style={{ width: 70 }} />
                            <span className="small muted">m/s · uncalibrated:</span>
                            <input type="number" min={0} step={0.01} value={c.value_fw ?? ""} placeholder="fw/s" onChange={(e) => setCondition(i, { ...c, value_fw: num(e.target.value) })} style={{ width: 70 }} />
                            <span className="small muted">frame widths/s</span>
                          </>
                        )}
                        <button className="btn sm ghost" onClick={() => set({ conditions: conditions.filter((_, j) => j !== i) })}>
                          Remove
                        </button>
                      </div>
                    ))}
                    <div>
                      <button className="btn sm" onClick={() => set({ conditions: [...conditions, { kind: "in_zone", role: "both", zone_ids: [] }] })}>
                        Add condition
                      </button>
                    </div>
                  </div>
                </div>
              </>
            )}
            {d.kind === "place" && (
              <>
                <div className="clause">
                  <span className="kw">EVENT</span>
                  <select
                    value={d.place_event ?? "enters"}
                    onChange={(e) => {
                      const p = PLACE_EVENTS.find((x) => x.id === e.target.value)!;
                      set({ place_event: p.id, relation: p.relation, for_s: p.id === "remains_in" || p.id === "stops_in" ? d.for_s || 30 : d.for_s });
                    }}
                    style={{ maxWidth: 260 }}
                  >
                    {PLACE_EVENTS.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                </div>
                <PlacesPick label={d.place_event === "moves_between" ? "FROM" : "PLACES"} value={d.places ?? []} onChange={(places) => set({ places })} objects={d.place_event === "uses_route" ? routes : objects} routes={d.place_event === "uses_route"} />
                {d.place_event === "moves_between" && <PlacesPick label="TO" value={d.to_places ?? []} onChange={(to_places) => set({ to_places })} objects={objects} />}
                {(d.place_event === "remains_in" || d.place_event === "stops_in" || d.place_event === "moves_between") && (
                  <div className="clause">
                    <span className="kw">{d.place_event === "moves_between" ? "WITHIN" : "FOR"}</span>
                    <span className="row">
                      <input type="number" min={1} value={d.for_s ?? 30} onChange={(e) => set({ for_s: num(e.target.value, 30) ?? 30 })} style={{ width: 80 }} />
                      <span className="small muted">seconds</span>
                    </span>
                  </div>
                )}
              </>
            )}
            {d.kind === "follow_route" && (
              <>
                <Role kw="FOLLOWS" value={d.object} onChange={(object) => set({ object })} recognition={recognition} />
                <div className="clause">
                  <span className="kw">THROUGH</span>
                  <span className="row wrap">
                    <input type="number" min={2} value={d.min_checkpoints ?? 3} onChange={(e) => set({ min_checkpoints: num(e.target.value, 3) ?? 3 })} style={{ width: 60 }} />
                    <span className="small muted">checkpoints within</span>
                    <input type="number" min={1} value={d.window_s ?? 60} onChange={(e) => set({ window_s: num(e.target.value, 60) ?? 60 })} style={{ width: 70 }} />
                    <span className="small muted">s, each at most</span>
                    <input type="number" min={1} value={d.max_lag_s ?? 20} onChange={(e) => set({ max_lag_s: num(e.target.value, 20) ?? 20 })} style={{ width: 60 }} />
                    <span className="small muted">s behind</span>
                  </span>
                </div>
                <PlacesPick label="CHECKPOINTS" value={d.places ?? []} onChange={(places) => set({ places })} objects={objects} />
              </>
            )}
            {d.kind === "sequence" && (
              <>
                <Role kw="ROLE B" value={d.object} onChange={(object) => set({ object })} recognition={recognition} />
                <div className="clause">
                  <span className="kw">STEPS</span>
                  <div className="stack" style={{ gap: 6 }}>
                    {steps.map((s, i) => (
                      <Step key={i} step={s} index={i} relations={allRelations} objects={objects} routes={routes}
                        onChange={(ns) => set({ steps: steps.map((x, j) => (j === i ? ns : x)) })}
                        onRemove={() => set({ steps: steps.filter((_, j) => j !== i) })}
                        onMove={(dir) => {
                          const j = i + dir;
                          if (j < 0 || j >= steps.length) return;
                          const next = [...steps];
                          [next[i], next[j]] = [next[j], next[i]];
                          set({ steps: next });
                        }}
                      />
                    ))}
                    <div>
                      <button className="btn sm" onClick={() => set({ steps: [...steps, { role: "A", what: "place", place_event: "enters", places: [], within_s: 60 }] })}>
                        Add step
                      </button>
                    </div>
                  </div>
                </div>
                <div className="clause">
                  <span className="kw">ALL WITHIN</span>
                  <span className="row">
                    <input type="number" min={1} value={d.window_s ?? 120} onChange={(e) => set({ window_s: num(e.target.value, 120) ?? 120 })} style={{ width: 80 }} />
                    <span className="small muted">seconds from the first step</span>
                  </span>
                </div>
              </>
            )}
            <div className="clause">
              <span className="kw">CREATE RELATIONSHIP</span>
              <span className="row wrap">
                <select value={d.relation ?? ""} onChange={(e) => set({ relation: e.target.value || null })} style={{ width: 220 }}>
                  {d.kind === "sequence" && <option value="">(none, event only)</option>}
                  {inferable.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
                <span className="hint">Observable relations only: personal relationships and ownership are never inferred.</span>
              </span>
            </div>
            <div className="clause">
              <span className="kw">CREATE EVENT</span>
              <input type="text" value={d.event_label ?? ""} placeholder={d.kind === "sequence" || d.kind === "follow_route" ? "Correlated event name (optional)" : "Label of the run event (optional)"} onChange={(e) => set({ event_label: e.target.value || null })} style={{ maxWidth: 300 }} />
            </div>
            <div className="clause">
              <span className="kw">ACTIONS</span>
              <span className="row wrap">
                <label className="check">
                  <input type="checkbox" checked={(d.actions ?? []).some((a) => a.kind === "record_event")} onChange={(e) => set({ actions: e.target.checked ? [...(d.actions ?? []), { kind: "record_event" }] : (d.actions ?? []).filter((a) => a.kind !== "record_event") })} />
                  Record a run event
                </label>
                <label className="check">
                  <input type="checkbox" checked={(d.actions ?? []).some((a) => a.kind === "webhook")} onChange={(e) => set({ actions: e.target.checked ? [...(d.actions ?? []), { kind: "webhook", url: "" }] : (d.actions ?? []).filter((a) => a.kind !== "webhook") })} />
                  Send webhook
                </label>
                {(d.actions ?? []).some((a) => a.kind === "webhook") && (
                  <input type="url" placeholder="https://example.org/hook" value={(d.actions ?? []).find((a) => a.kind === "webhook")?.url ?? ""} onChange={(e) => set({ actions: (d.actions ?? []).map((a) => (a.kind === "webhook" ? { ...a, url: e.target.value } : a)) })} style={{ maxWidth: 260 }} />
                )}
                <span className="small muted">only when at least</span>
                <select value={d.act_min_state ?? "likely"} onChange={(e) => set({ act_min_state: e.target.value as StateName })} style={{ width: 150 }}>
                  <option value="confirmed">confirmed by rule</option>
                  <option value="likely">likely</option>
                  <option value="possible">possible</option>
                </select>
              </span>
            </div>
          </div>
        </>
      )}
      {check?.ok && <div className="rel-reason small">{check.summary}</div>}
      {check && !check.ok && <ErrorNotice error={check.error} />}
    </div>
  );
}
