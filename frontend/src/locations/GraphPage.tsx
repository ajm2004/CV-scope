/* Relationship graph: an interactive node-edge view of the stored
 * relationships around an entity, or of everything in a run, an experiment,
 * a site/location or a time range. The graph is built from the stored
 * entities, observations and relationships on request; it is a view. */

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { api } from "../api/client";
import { ErrorNotice, Field, Panel } from "../components/ui";
import { useRecognitionAuth } from "../lib/recognitionToken";
import type { EntityOut } from "../relationships/api";
import { IdentityNotice, useMeta } from "../relationships/bits";
import EntityPicker from "../relationships/EntityPicker";
import "../relationships/relationships.css";
import { loc } from "./api";
import GraphWorkbench from "./GraphWorkbench";
import "./locations.css";
import { useGraph } from "./useGraph";

type Scope = "entity" | "run" | "experiment" | "location" | "time";

const HOURS = [1, 6, 24, 72, 168];

export default function GraphPage() {
  const [search, setSearch] = useSearchParams();
  const token = useRecognitionAuth((s) => s.token);
  const meta = useMeta();
  const initial: Scope = search.get("key") ? "entity" : search.get("run_id") ? "run" : search.get("experiment_id") ? "experiment" : search.get("location_id") ? "location" : "entity";
  const [scope, setScope] = useState<Scope>(initial);
  const [entity, setEntity] = useState<EntityOut | null>(null);
  const key = search.get("key");
  const runId = search.get("run_id") ? Number(search.get("run_id")) : undefined;
  const experimentId = search.get("experiment_id") ? Number(search.get("experiment_id")) : undefined;
  const locationId = search.get("location_id") ? Number(search.get("location_id")) : undefined;
  const hours = search.get("hours") ? Number(search.get("hours")) : 24;
  const depth = Number(search.get("depth") ?? 1);
  const project = search.get("project") !== "0";
  const context = search.get("context") !== "0";
  const g = useGraph();

  const experiments = useQuery({ queryKey: ["experiments"], queryFn: () => api.experiments.list() });
  const locations = useQuery({ queryKey: ["locations-graph", token], queryFn: () => loc.graph() });
  const runs = useQuery({ queryKey: ["runs-for-graph", experimentId], queryFn: () => api.runs.list({ experiment_id: experimentId }), enabled: scope === "run" });

  const set = (patch: Record<string, string | number | undefined | null>) => {
    const next = new URLSearchParams(search);
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined || v === null || v === "") next.delete(k);
      else next.set(k, String(v));
    }
    setSearch(next);
  };

  const params = useMemo(() => {
    const p: Record<string, unknown> = { project, context, min_state: "insufficient" };
    if (scope === "entity" && key) return { ...p, key, depth };
    if (scope === "run" && runId) return { ...p, run_id: runId };
    if (scope === "experiment" && experimentId) return { ...p, experiment_id: experimentId };
    if (scope === "location" && locationId) return { ...p, location_id: locationId, last_hours: hours };
    if (scope === "time") return { ...p, last_hours: hours, ...(locationId ? { location_id: locationId } : {}) };
    return null;
  }, [scope, key, depth, runId, experimentId, locationId, hours, project, context]);

  const q = useQuery({ queryKey: ["visual-graph", params, token], queryFn: () => loc.visual(params as never), enabled: !!params, retry: 0 });
  const { reset } = g;
  useEffect(() => {
    if (q.data) reset(q.data);
  }, [q.data, reset]);

  const serverParams = useMemo(() => ({ project, context, min_state: "insufficient" as const, ...(locationId && scope !== "entity" ? { location_id: locationId } : {}) }), [project, context, locationId, scope]);
  const locNodes = (locations.data?.nodes ?? []).filter((n) => !["camera", "sensor"].includes(n.kind));

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Relationship graph</h1>
          <div className="sub">People, vehicles, identities, places, cameras and events as nodes; their stored relationships as edges, with confidence and time. Built from the stored data on request — the graph itself stores nothing.</div>
        </div>
      </div>
      <IdentityNotice sees={meta.data?.viewer.sees_identities} />
      <Panel>
        <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
          <Field label="Show">
            <select value={scope} onChange={(e) => setScope(e.target.value as Scope)}>
              <option value="entity">Around an entity</option>
              <option value="run">A run</option>
              <option value="experiment">An experiment</option>
              <option value="location">A site or location</option>
              <option value="time">A time range</option>
            </select>
          </Field>
          {scope === "entity" && (
            <>
              <Field label="Entity">
                <EntityPicker value={entity ?? (q.data && key ? (q.data.nodes.find((n) => n.node === q.data!.center) ?? null) : null)} onChange={(e) => { setEntity(e); if (e?.key) set({ key: e.key }); }} />
              </Field>
              <Field label="Depth">
                <span className="btn-group">
                  {[1, 2, 3].map((d) => (
                    <button key={d} className={`btn sm ${depth === d ? "active" : ""}`} onClick={() => set({ depth: d })}>
                      {d === 1 ? "Direct" : `${d} steps`}
                    </button>
                  ))}
                </span>
              </Field>
            </>
          )}
          {(scope === "experiment" || scope === "run") && (
            <Field label="Experiment">
              <select value={experimentId ?? ""} onChange={(e) => set({ experiment_id: e.target.value || null, run_id: null })}>
                <option value="">Choose…</option>
                {experiments.data?.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {scope === "run" && (
            <Field label="Run">
              <select value={runId ?? ""} onChange={(e) => set({ run_id: e.target.value || null })}>
                <option value="">Choose…</option>
                {runs.data?.map((r) => (
                  <option key={r.id} value={r.id}>
                    #{r.id} · {r.started_at ? new Date(r.started_at).toLocaleString() : r.status}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {(scope === "location" || scope === "time") && (
            <>
              <Field label={scope === "location" ? "Site / location" : "Site / location (optional)"}>
                <select value={locationId ?? ""} onChange={(e) => set({ location_id: e.target.value || null })}>
                  <option value="">{scope === "location" ? "Choose…" : "Everywhere"}</option>
                  {locNodes.map((n) => (
                    <option key={n.id} value={n.id}>
                      {n.path}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Last">
                <select value={hours} onChange={(e) => set({ hours: e.target.value })}>
                  {HOURS.map((h) => (
                    <option key={h} value={h}>
                      {h < 24 ? `${h} h` : `${h / 24} day${h > 24 ? "s" : ""}`}
                    </option>
                  ))}
                </select>
              </Field>
            </>
          )}
          <label className="row small" style={{ gap: 4 }} title="Draw a recognized person's or vehicle's tracks as one node (viewers with recognition access)">
            <input type="checkbox" checked={project} onChange={(e) => set({ project: e.target.checked ? null : 0 })} /> Merge tracks into identities
          </label>
          <label className="row small" style={{ gap: 4 }} title="Cameras and locations from the location model">
            <input type="checkbox" checked={context} onChange={(e) => set({ context: e.target.checked ? null : 0 })} /> Location context
          </label>
        </div>
      </Panel>
      {q.isError && <ErrorNotice error={q.error} />}
      {!params && <div className="hint">Choose what to show.</div>}
      {q.isFetching && <div className="hint">Loading the graph…</div>}
      {q.data && q.data.edges.length === 0 && <div className="hint">No relationships in this scope yet.</div>}
      {g.model && <GraphWorkbench g={g} serverParams={serverParams} onRecenter={(k) => { setScope("entity"); set({ key: k, run_id: null, experiment_id: null }); }} />}
    </div>
  );
}
