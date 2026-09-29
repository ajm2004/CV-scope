/* Relationship explorer: pick an entity, see what it is related to (list,
 * graph, history), filter by relationship type, time and confidence, and open
 * the evidence behind any relationship. */

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "../api/client";
import { Empty, ErrorNotice, Field, KV, Notice, Panel, Pill, Tabs } from "../components/ui";
import { dateTime } from "../lib/format";
import { useRecognitionAuth } from "../lib/recognitionToken";
import { download, rel, type EntityOut, type Filters, type RelatedGroup, type StateName } from "./api";
import { EntityLink, IdentityNotice, mediaClock, relDuration, StatePill, useMeta, useRelationLabels } from "./bits";
import Evidence, { type EvidenceRef } from "./Evidence";
import ExplorerGraph from "../locations/ExplorerGraph";
import "./relationships.css";

const TYPE_FILTERS: { id: string; label: string; identity?: boolean }[] = [
  { id: "", label: "All kinds" },
  { id: "person_track", label: "Person tracks" },
  { id: "vehicle_track", label: "Vehicle tracks" },
  { id: "object_track", label: "Other objects" },
  { id: "recognized_person", label: "Recognized people", identity: true },
  { id: "registered_vehicle", label: "Registered vehicles", identity: true },
  { id: "license_plate", label: "License plates", identity: true },
  { id: "zone,gate,route", label: "Places (zones, gates, routes)" },
  { id: "sensor", label: "Sensors" },
];

const RANGES: { id: string; label: string; hours?: number }[] = [
  { id: "", label: "Any time" },
  { id: "24", label: "Last 24 hours", hours: 24 },
  { id: "168", label: "Last 7 days", hours: 168 },
  { id: "720", label: "Last 30 days", hours: 720 },
];

export default function ExplorerPage() {
  const [search, setSearch] = useSearchParams();
  const key = search.get("key");
  const token = useRecognitionAuth((s) => s.token);
  const meta = useMeta();
  const labelFor = useRelationLabels();
  const [typeFilter, setTypeFilter] = useState("");
  const [q, setQ] = useState("");
  const [experiment, setExperiment] = useState<number | undefined>(undefined);
  const [relTypes, setRelTypes] = useState<string[]>([]);
  const [minState, setMinState] = useState<StateName>("possible");
  const [range, setRange] = useState("");
  const [tab, setTab] = useState("related");
  const [depth, setDepth] = useState(1);
  const [evidence, setEvidence] = useState<EvidenceRef | null>(null);
  const experiments = useQuery({ queryKey: ["experiments"], queryFn: () => api.experiments.list() });
  const viewer = meta.data?.viewer;

  const filters: Filters = useMemo(
    () => ({ types: relTypes.join(",") || undefined, min_state: minState, experiment_id: experiment, last_hours: RANGES.find((r) => r.id === range)?.hours }),
    [relTypes, minState, experiment, range],
  );
  const entities = useQuery({
    queryKey: ["rel-entities", typeFilter, q, experiment, token],
    queryFn: () => rel.entities({ type: typeFilter || undefined, q: q || undefined, experiment_id: experiment, limit: 80 }),
  });
  const overview = useQuery({ queryKey: ["rel-overview", experiment, token], queryFn: () => rel.overview({ experiment_id: experiment }), enabled: !key });
  const recent = useQuery({ queryKey: ["rel-correlated", experiment, token], queryFn: () => rel.correlated({ experiment_id: experiment, limit: 30 }), enabled: !key });
  const entity = useQuery({ queryKey: ["rel-entity", key, token], queryFn: () => rel.entity(key!), enabled: !!key, retry: 0 });
  const neighbors = useQuery({ queryKey: ["rel-neighbors", key, filters, token], queryFn: () => rel.neighbors(key!, filters), enabled: !!key && tab === "related" && entity.isSuccess });
  const history = useQuery({ queryKey: ["rel-history", key, experiment, token], queryFn: () => rel.history(key!, { experiment_id: experiment }), enabled: !!key && tab === "history" && entity.isSuccess });

  const select = (k: string | null) => {
    const next = new URLSearchParams(search);
    if (k) next.set("key", k);
    else next.delete("key");
    setSearch(next);
    setEvidence(null);
  };
  const [exportError, setExportError] = useState<unknown>(null);
  const exportCsv = async (identities: boolean) => {
    setExportError(null);
    try {
      await download(rel.exportUrl({ ...filters, format: "csv", identities }), `relationships${identities ? "-with-identities" : ""}.csv`);
    } catch (e) {
      setExportError(e);
    }
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Relationships</h1>
          <div className="sub">How tracked people, vehicles, identities and places relate over time. Every relationship comes from a rule, a measurement, a recognition result or a sensor, with its confidence and evidence.</div>
        </div>
        <div className="row wrap">
          <Link className="btn" to="/relationships/timeline">
            Timeline
          </Link>
          <Link className="btn" to="/relationships/search">
            Search
          </Link>
          <Link className="btn" to="/relationships/rules">
            Rules
          </Link>
          {viewer?.can.export && (
            <button className="btn" onClick={() => exportCsv(false)}>
              Export CSV
            </button>
          )}
          {viewer?.can.export_identity && viewer.sees_identities && (
            <button className="btn" onClick={() => exportCsv(true)}>
              Export with identities
            </button>
          )}
        </div>
      </div>
      <ErrorNotice error={exportError} />
      <IdentityNotice sees={viewer?.sees_identities} />
      <div className="rel-layout">
        <Panel title="Entities" flush className="rel-finder">
          <div className="stack" style={{ gap: 8, padding: 10 }}>
            <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} aria-label="Kind of entity">
              {TYPE_FILTERS.filter((t) => !t.identity || viewer?.sees_identities).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
            </select>
            <select value={experiment ?? ""} onChange={(e) => setExperiment(e.target.value ? Number(e.target.value) : undefined)} aria-label="Experiment">
              <option value="">All experiments</option>
              {experiments.data?.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                </option>
              ))}
            </select>
            <input type="search" placeholder="Search by label" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          {entities.isError && <ErrorNotice error={entities.error} />}
          <ul className="rel-entity-list">
            {entities.data?.map((e) => (
              <li key={e.key ?? e.label} className={e.key === key ? "selected" : ""}>
                <button onClick={() => e.key && select(e.key)} disabled={!e.key}>
                  <EntityLabel e={e} />
                  <span className="hint">
                    {e.run_id ? `run #${e.run_id} · ` : ""}
                    {e.last_seen ? dateTime(e.last_seen) : e.type_label}
                  </span>
                </button>
              </li>
            ))}
            {entities.data && entities.data.length === 0 && <li className="hint" style={{ padding: 10 }}>Nothing yet. Turn on relationships for an experiment and run it, or analyse a finished run again.</li>}
          </ul>
        </Panel>
        <div className="stack" style={{ minWidth: 0 }}>
          {!key && <Overview overview={overview.data} recent={recent.data} onOpen={setEvidence} labelFor={labelFor} />}
          {key && entity.isError && <ErrorNotice error={entity.error} />}
          {key && entity.data && (
            <>
              <Panel>
                <div className="row wrap" style={{ justifyContent: "space-between" }}>
                  <div>
                    <h2 style={{ margin: 0 }}>
                      <EntityLink e={entity.data} showType />
                    </h2>
                    <div className="hint">
                      {entity.data.type_label}
                      {entity.data.first_seen && ` · first seen ${dateTime(entity.data.first_seen)}`}
                      {entity.data.last_seen && ` · last seen ${dateTime(entity.data.last_seen)}`}
                      {entity.data.run_id && (
                        <>
                          {" · "}
                          <Link to={`/analysis/runs/${entity.data.run_id}`}>run #{entity.data.run_id}</Link>
                        </>
                      )}
                    </div>
                  </div>
                  <div className="row">
                    <Link className="btn sm" to={`/relationships/timeline?key=${encodeURIComponent(key)}`}>
                      Timeline
                    </Link>
                    <button className="btn sm ghost" onClick={() => select(null)}>
                      Overview
                    </button>
                  </div>
                </div>
              </Panel>
              <Panel>
                <div className="row wrap" style={{ gap: 12 }}>
                  <Field label="Relationship types">
                    <select
                      multiple
                      value={relTypes}
                      onChange={(e) => setRelTypes([...e.target.selectedOptions].map((o) => o.value))}
                      style={{ minWidth: 220, height: 84 }}
                    >
                      {meta.data?.relation_types.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.id}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <div className="stack" style={{ gap: 6 }}>
                    <Field label="At least">
                      <select value={minState} onChange={(e) => setMinState(e.target.value as StateName)}>
                        <option value="confirmed">Confirmed by rule</option>
                        <option value="likely">Likely</option>
                        <option value="possible">Possible</option>
                        <option value="insufficient">Everything (incl. insufficient evidence)</option>
                      </select>
                    </Field>
                    <Field label="Time">
                      <select value={range} onChange={(e) => setRange(e.target.value)}>
                        {RANGES.map((r) => (
                          <option key={r.id} value={r.id}>
                            {r.label}
                          </option>
                        ))}
                      </select>
                    </Field>
                  </div>
                  {relTypes.length > 0 && (
                    <button className="btn sm ghost" onClick={() => setRelTypes([])}>
                      Clear types
                    </button>
                  )}
                </div>
              </Panel>
              <Tabs
                tabs={[
                  { id: "related", label: "Related entities" },
                  { id: "graph", label: "Graph" },
                  { id: "history", label: "History" },
                ]}
                active={tab}
                onChange={setTab}
              />
              {tab === "related" && (
                <Panel title={neighbors.data ? `${neighbors.data.related.length} related · ${neighbors.data.count} relationships` : "Related"}>
                  {neighbors.isError && <ErrorNotice error={neighbors.error} />}
                  {neighbors.data?.aliases && neighbors.data.aliases.length > 0 && (
                    <div className="hint" style={{ marginBottom: 8 }}>
                      Through {neighbors.data.aliases.length} observed track{neighbors.data.aliases.length === 1 ? "" : "s"} identified as this entity (the tracks are kept).
                    </div>
                  )}
                  {neighbors.data && neighbors.data.related.length === 0 && <Empty>No relationships match these filters.</Empty>}
                  <div className="stack" style={{ gap: 8 }}>
                    {neighbors.data?.related.map((g) => (
                      <RelatedCard key={(g.entity.key ?? g.entity.label) + g.relationships[0]?.id} g={g} onOpen={setEvidence} labelFor={labelFor} />
                    ))}
                  </div>
                </Panel>
              )}
              {tab === "graph" && (
                <Panel
                  title="Graph"
                  actions={
                    <span className="btn-group">
                      <button className={`btn sm ${depth === 1 ? "active" : ""}`} onClick={() => setDepth(1)}>
                        Direct
                      </button>
                      <button className={`btn sm ${depth === 2 ? "active" : ""}`} onClick={() => setDepth(2)}>
                        Two steps
                      </button>
                    </span>
                  }
                >
                  {entity.isSuccess && <ExplorerGraph entityKey={key} depth={depth} filters={filters} onOpen={(k) => select(k)} onEdge={(e) => setEvidence({ kind: "relationship", id: e.ids[e.ids.length - 1] })} />}
                </Panel>
              )}
              {tab === "history" && <HistoryPanel h={history.data} error={history.error} labelFor={labelFor} />}
            </>
          )}
        </div>
        <div className="rel-evidence">{evidence ? <Evidence target={evidence} onOpen={setEvidence} onClose={() => setEvidence(null)} /> : <Panel><Empty>Select a relationship to see its evidence.</Empty></Panel>}</div>
      </div>
    </div>
  );
}

function EntityLabel({ e }: { e: EntityOut }) {
  return (
    <span className="rel-entity-label">
      <span className={`rel-ent rel-ent-${e.category}`} aria-hidden>
        {e.category === "identity" ? "◆" : e.category === "place" ? "▭" : e.category === "track" ? "◯" : "◇"}
      </span>{" "}
      {e.label}
      {e.identity && <span className="hint"> → {e.identity.label}</span>}
    </span>
  );
}

function RelatedCard({ g, onOpen, labelFor }: { g: RelatedGroup; onOpen: (r: EvidenceRef) => void; labelFor: (t: string) => string }) {
  const [open, setOpen] = useState(false);
  const rels = open ? g.relationships : g.relationships.slice(0, 3);
  return (
    <div className="rel-card">
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <strong>
          <EntityLink e={g.entity} showType />
        </strong>
        <span className="row wrap" style={{ gap: 4 }}>
          {Object.entries(g.types).map(([t, n]) => (
            <Pill key={t}>
              {t}
              {n > 1 ? ` ×${n}` : ""}
            </Pill>
          ))}
          {g.sessions > 1 && <Pill tone="accent">{g.sessions} sessions</Pill>}
        </span>
      </div>
      <table className="table rel-table">
        <tbody>
          {rels.map((r) => (
            <tr key={r.id} className="clickable" onClick={() => onOpen({ kind: "relationship", id: r.id })}>
              <td style={{ width: "34%" }}>
                {r.direction === "incoming" ? "← " : ""}
                {labelFor(r.type)}
                {r.via && <div className="hint">via {r.via.label}</div>}
              </td>
              <td className="muted nowrap">
                {dateTime(r.start_at)}
                {relDuration(r) && <span className="hint"> · {relDuration(r)}</span>}
                {r.run_id && r.start_media_s != null && <div className="hint">run #{r.run_id} at {mediaClock(r.start_media_s)}</div>}
              </td>
              <td>
                <StatePill state={r.state} confidence={r.confidence} />
              </td>
              <td className="hint">{r.calibration.measure === "scene-relative" ? "frame widths" : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {g.relationships.length > 3 && (
        <button className="btn sm ghost" onClick={() => setOpen(!open)}>
          {open ? "Show fewer" : `Show all ${g.relationships.length}`}
        </button>
      )}
    </div>
  );
}

function Overview({ overview, recent, onOpen, labelFor }: { overview?: Awaited<ReturnType<typeof rel.overview>>; recent?: Awaited<ReturnType<typeof rel.correlated>>; onOpen: (r: EvidenceRef) => void; labelFor: (t: string) => string }) {
  const types = Object.entries(overview?.relationships ?? {}).sort((a, b) => b[1] - a[1]);
  return (
    <>
      <Panel title="In the graph">
        {overview && types.length === 0 ? (
          <Notice>
            No relationships yet. Turn on <strong>Relationships</strong> in an <Link to="/experiments">experiment</Link> (built-in place and identity relationships need no rules), add rules on the <Link to="/relationships/rules">Rules</Link> page, and start a
            run — or analyse a finished run again from its analysis page.
          </Notice>
        ) : (
          <div className="rel-counts">
            {types.map(([t, n]) => (
              <div key={t} className="rel-count">
                <span className="num">{n}</span>
                <span className="small muted">{labelFor(t)}</span>
                <span className="hint mono">{t}</span>
              </div>
            ))}
          </div>
        )}
        {overview && (
          <div className="hint" style={{ marginTop: 8 }}>
            {overview.analyses} analys{overview.analyses === 1 ? "is" : "es"} · {overview.rules} rule{overview.rules === 1 ? "" : "s"} · {overview.correlated.correlated ?? 0} correlated events · {overview.correlated.deviation ?? 0} pattern deviations
          </div>
        )}
      </Panel>
      <Panel title="Recent correlated events and deviations" flush>
        {recent && recent.length === 0 ? (
          <Empty>None yet.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <tbody>
                {[...(recent ?? [])].reverse().map((c) => (
                  <tr key={c.id} className="clickable" onClick={() => onOpen({ kind: "correlated", id: c.id })}>
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
        )}
      </Panel>
    </>
  );
}

function HistoryPanel({ h, error, labelFor }: { h?: Awaited<ReturnType<typeof rel.history>>; error: unknown; labelFor: (t: string) => string }) {
  if (error) return <ErrorNotice error={error} />;
  if (!h) return <Panel title="History"><div className="hint">Loading…</div></Panel>;
  const places = (title: string, items: { entity: EntityOut; count: number }[]) =>
    items.length > 0 && (
      <div>
        <div className="section-title">{title}</div>
        <ul className="list-plain">
          {items.map((p) => (
            <li key={p.entity.key ?? p.entity.label}>
              <EntityLink e={p.entity} /> <span className="hint">× {p.count}</span>
            </li>
          ))}
        </ul>
      </div>
    );
  return (
    <Panel title="History">
      <div className="stack" style={{ gap: 10 }}>
        <KV
          items={[
            ["Observed in", `${h.sessions} session${h.sessions === 1 ? "" : "s"} (runs)${h.tracks > 1 ? ` · ${h.tracks} tracks` : ""}`],
            ["First seen", dateTime(h.first_seen)],
            ["Last seen", dateTime(h.last_seen)],
          ]}
        />
        {h.associated.length > 0 && (
          <div>
            <div className="section-title">Observed with</div>
            <ul className="list-plain">
              {h.associated.map((a) => (
                <li key={a.entity.key ?? a.entity.label}>
                  <EntityLink e={a.entity} showType /> <span className="hint">{Object.keys(a.types).map(labelFor).join(", ")} · {a.sessions} session{a.sessions === 1 ? "" : "s"}</span>
                </li>
              ))}
            </ul>
            <div className="hint">Observed together by rules — not ownership and not a personal relationship.</div>
          </div>
        )}
        {places("Common entries", h.entries)}
        {places("Common parking", h.parking)}
        {places("Common routes", h.routes)}
        {places("Where it stays", h.stays)}
        {h.moves.length > 0 && (
          <div>
            <div className="section-title">Common movements</div>
            <ul className="list-plain">
              {h.moves.map((m, i) => (
                <li key={i}>
                  <EntityLink e={m.from} /> → <EntityLink e={m.to} /> <span className="hint">× {m.count}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Panel>
  );
}
