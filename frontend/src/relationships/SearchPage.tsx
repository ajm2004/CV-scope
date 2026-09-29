/* Structured questions about the relationship graph (no free text). */

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import { Empty, ErrorNotice, Field, Panel, Pill } from "../components/ui";
import { dateTime, seconds } from "../lib/format";
import { rel, type CorrelatedOut, type EntityOut, type RelatedGroup, type RelationshipOut, type StateName, type TimelineItem } from "./api";
import { EntityLink, IdentityNotice, StatePill, useMeta, useRelationLabels, VideoLink } from "./bits";
import EntityPicker from "./EntityPicker";
import Evidence, { type EvidenceRef } from "./Evidence";
import "./relationships.css";

type Kind = "events" | "associated" | "near" | "entered_after" | "routes" | "correlated";

const QUESTIONS: { id: Kind; label: string; needsEntity: boolean }[] = [
  { id: "events", label: "Show everything involving …", needsEntity: true },
  { id: "associated", label: "Show what is associated with …", needsEntity: true },
  { id: "near", label: "Show people observed near …", needsEntity: true },
  { id: "entered_after", label: "Show who entered a zone after … arrived", needsEntity: true },
  { id: "routes", label: "Show route use", needsEntity: false },
  { id: "correlated", label: "Show correlated events and pattern deviations", needsEntity: false },
];

export default function SearchPage() {
  const meta = useMeta();
  const labelFor = useRelationLabels();
  const [kind, setKind] = useState<Kind>("associated");
  const [entity, setEntity] = useState<EntityOut | null>(null);
  const [zone, setZone] = useState<EntityOut | null>(null);
  const [target, setTarget] = useState("vehicle");
  const [windowMin, setWindowMin] = useState(10);
  const [experiment, setExperiment] = useState<number | undefined>(undefined);
  const [minState, setMinState] = useState<StateName>("likely");
  const [evidence, setEvidence] = useState<EvidenceRef | null>(null);
  const experiments = useQuery({ queryKey: ["experiments"], queryFn: () => api.experiments.list() });
  const q = QUESTIONS.find((x) => x.id === kind)!;
  const run = useMutation({
    mutationFn: () =>
      rel.search({ kind, key: entity?.key ?? undefined, target: kind === "near" ? "person" : kind === "associated" ? target : undefined, zone_key: zone?.key ?? undefined, window_s: windowMin * 60, experiment_id: experiment, min_state: minState }),
  });
  const ready = (!q.needsEntity || !!entity) && (kind !== "entered_after" || !!zone);
  const res = run.data as (Record<string, unknown> & { items: unknown[] }) | undefined;

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Relationship search</h1>
          <div className="sub">Structured questions about who and what was observed together, where and when.</div>
        </div>
      </div>
      <IdentityNotice sees={meta.data?.viewer.sees_identities} />
      <Panel>
        <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
          <Field label="Question">
            <select value={kind} onChange={(e) => { setKind(e.target.value as Kind); run.reset(); }}>
              {QUESTIONS.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.label}
                </option>
              ))}
            </select>
          </Field>
          {q.needsEntity && (
            <Field label={kind === "entered_after" ? "Who or what arrived" : "Entity"}>
              <EntityPicker value={entity} onChange={setEntity} experimentId={experiment} />
            </Field>
          )}
          {kind === "associated" && (
            <Field label="Show">
              <select value={target} onChange={(e) => setTarget(e.target.value)}>
                <option value="vehicle">Vehicles</option>
                <option value="person">People</option>
                <option value="any">Everything</option>
              </select>
            </Field>
          )}
          {kind === "entered_after" && (
            <>
              <Field label="Zone">
                <EntityPicker value={zone} onChange={setZone} types="zone" placeholder="Zone name…" experimentId={experiment} />
              </Field>
              <Field label="Within (minutes)">
                <input type="number" min={1} value={windowMin} onChange={(e) => setWindowMin(Number(e.target.value) || 1)} style={{ width: 80 }} />
              </Field>
            </>
          )}
          <Field label="Experiment">
            <select value={experiment ?? ""} onChange={(e) => setExperiment(e.target.value ? Number(e.target.value) : undefined)}>
              <option value="">All</option>
              {experiments.data?.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="At least">
            <select value={minState} onChange={(e) => setMinState(e.target.value as StateName)}>
              <option value="confirmed">Confirmed by rule</option>
              <option value="likely">Likely</option>
              <option value="possible">Possible</option>
            </select>
          </Field>
          <button className="btn primary" disabled={!ready || run.isPending} onClick={() => run.mutate()}>
            Search
          </button>
        </div>
      </Panel>
      {run.isError && <ErrorNotice error={run.error} />}
      {res && (
        <div className="grid-2" style={{ gridTemplateColumns: "minmax(0, 1.3fr) minmax(300px, 1fr)", alignItems: "start" }}>
          <Panel title={`${res.items.length} result${res.items.length === 1 ? "" : "s"}`} flush>
            {res.items.length === 0 && <Empty>Nothing found.</Empty>}
            <div className="table-wrap">
              <table className="table">
                <tbody>
                  {kind === "events" &&
                    (res.items as TimelineItem[]).map((i) => (
                      <tr key={`${i.kind}-${i.id}`} className={i.kind !== "observation" ? "clickable" : ""} onClick={() => i.kind !== "observation" && setEvidence({ kind: i.kind as "relationship" | "correlated", id: i.id })}>
                        <td className="muted nowrap">{dateTime(i.at)}</td>
                        <td>{i.text}</td>
                        <td>{i.state && <StatePill state={i.state} confidence={i.confidence} />}</td>
                        <td>
                          <VideoLink runId={i.run_id} t={i.media_time_s} label="" />
                        </td>
                      </tr>
                    ))}
                  {(kind === "associated" || kind === "near") &&
                    (res.items as RelatedGroup[]).map((g) => (
                      <tr key={(g.entity.key ?? g.entity.label) + g.relationships[0]?.id} className="clickable" onClick={() => setEvidence({ kind: "relationship", id: g.relationships[g.relationships.length - 1].id })}>
                        <td>
                          <EntityLink e={g.entity} showType />
                        </td>
                        <td>{Object.entries(g.types).map(([t, n]) => `${labelFor(t)}${n > 1 ? ` ×${n}` : ""}`).join(", ")}</td>
                        <td className="num">{g.sessions} session{g.sessions === 1 ? "" : "s"}</td>
                        <td className="muted nowrap">{dateTime(g.last_at)}</td>
                        <td>
                          <Pill>{Math.round(g.best_confidence * 100)}%</Pill>
                        </td>
                      </tr>
                    ))}
                  {kind === "entered_after" &&
                    (res.items as { entity: EntityOut; at: string; after_s: number; relationship_id: number; run_id: number; media_time_s: number }[]).map((i) => (
                      <tr key={i.relationship_id} className="clickable" onClick={() => setEvidence({ kind: "relationship", id: i.relationship_id })}>
                        <td>
                          <EntityLink e={i.entity} showType />
                        </td>
                        <td className="muted nowrap">{dateTime(i.at)}</td>
                        <td>{seconds(i.after_s, 0)} after the arrival</td>
                        <td>
                          <VideoLink runId={i.run_id} t={i.media_time_s} label="" />
                        </td>
                      </tr>
                    ))}
                  {kind === "routes" &&
                    (res.items as { route: EntityOut; count: number; items: RelationshipOut[] }[]).map((g) => (
                      <tr key={g.route.key ?? g.route.label}>
                        <td>
                          <EntityLink e={g.route} />
                        </td>
                        <td className="num">{g.count} use{g.count === 1 ? "" : "s"}</td>
                        <td>
                          {g.items.slice(0, 6).map((r) => (
                            <button key={r.id} className="linklike" style={{ marginRight: 8 }} onClick={() => setEvidence({ kind: "relationship", id: r.id })}>
                              {r.subject?.label}
                            </button>
                          ))}
                          {g.items.length > 6 && <span className="hint">+{g.items.length - 6}</span>}
                        </td>
                      </tr>
                    ))}
                  {kind === "correlated" &&
                    (res.items as CorrelatedOut[]).map((c) => (
                      <tr key={c.id} className="clickable" onClick={() => setEvidence({ kind: "correlated", id: c.id })}>
                        <td className="muted nowrap">{dateTime(c.start_at)}</td>
                        <td>
                          <strong>{c.label}</strong>
                          <div className="hint">{c.description}</div>
                        </td>
                        <td>
                          <StatePill state={c.state} confidence={c.confidence} />
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
            {kind === "entered_after" && Array.isArray(res.arrivals) && <div className="hint" style={{ padding: 8 }}>{(res.arrivals as string[]).length} arrival(s) of the chosen entity considered.</div>}
          </Panel>
          <div className="rel-evidence">{evidence ? <Evidence target={evidence} onOpen={setEvidence} onClose={() => setEvidence(null)} /> : <Panel><Empty>Select a result to see its evidence.</Empty></Panel>}</div>
        </div>
      )}
      <div className="hint">
        Natural-language questions are not supported; every result comes from stored relationships. <Link to="/relationships">Explorer</Link> · <Link to="/relationships/timeline">Timeline</Link>
      </div>
    </div>
  );
}
