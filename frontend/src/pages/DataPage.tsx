import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { EventRecord } from "../api/types";
import { Empty, ErrorNotice, Field, Modal, Panel, Pill } from "../components/ui";
import { clock, dateTime, eventLabel, num, speedUnit } from "../lib/format";
import { useRecognitionAuth } from "../lib/recognitionToken";
import { entityLabel, useEntityNames } from "../recognition/useEntityNames";

const COLUMNS: { key: string; label: string; num?: boolean; render: (e: EventRecord) => React.ReactNode }[] = [
  { key: "wall_time", label: "Timestamp", render: (e) => <span className="muted">{dateTime(e.wall_time)}</span> },
  { key: "media_time_s", label: "Media time", num: true, render: (e) => clock(e.media_time_s) },
  { key: "experiment", label: "Experiment", render: (e) => <Link to={`/experiments/${e.experiment_id}`}>#{e.experiment_id}</Link> },
  { key: "run", label: "Run", render: (e) => <Link to={`/analysis/runs/${e.run_id}`}>#{e.run_id}</Link> },
  { key: "camera", label: "Camera", render: (e) => (e.camera_id != null ? `#${e.camera_id}` : "–") },
  { key: "track_id", label: "Track", num: true, render: (e) => e.track_id },
  { key: "object_class", label: "Object class", render: (e) => e.object_class },
  { key: "event_type", label: "Event", render: (e) => eventLabel(e.event_type) },
  { key: "object", label: "Scene object", render: (e) => e.object_name ?? "–" },
  {
    key: "direction",
    label: "Direction",
    // A doorway line counted someone who disappeared or appeared at it
    render: (e) => (e.direction ? `${e.direction}${e.context?.inferred ? " (doorway)" : ""}` : "–"),
  },
  { key: "route", label: "Route / label", render: (e) => e.route ?? (e.context?.label as string | undefined) ?? "–" },
  { key: "duration_s", label: "Duration", num: true, render: (e) => (e.duration_s != null ? `${num(e.duration_s, 2)} s` : "–") },
  { key: "avg_speed", label: "Speed", num: true, render: (e) => (e.avg_speed != null ? `${num(e.avg_speed, 2)} ${speedUnit(e.speed_unit)}` : "–") },
  { key: "confidence", label: "Confidence", num: true, render: (e) => (e.confidence != null ? num(e.confidence, 2) : "–") },
];

/** The recognized person or vehicle behind the event's opaque entity id. */
function IdentityCell({ e, names }: { e: EventRecord; names: ReturnType<typeof useEntityNames>["data"] }) {
  const label = entityLabel(e.context, names);
  if (!label) return <span className="muted">–</span>;
  if (!label.known && !label.possible) return <span className="muted">{label.text}</span>;
  return (
    <Pill tone={label.possible ? "warn" : label.known ? "accent" : ""}>
      {label.possible ? "? " : ""}
      {label.text}
    </Pill>
  );
}

export default function DataPage({ projectId, embedded = false, runId }: { projectId?: number; embedded?: boolean; runId?: number }) {
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [sort, setSort] = useState("id");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [detail, setDetail] = useState<EventRecord | null>(null);
  const params = { ...filters, project_id: projectId, run_id: runId ?? filters.run_id, page, page_size: pageSize, sort, order };
  const q = useQuery({ queryKey: ["events", params], queryFn: () => api.events.list(params) });
  const facets = useQuery({ queryKey: ["facets", projectId, runId, filters.experiment_id], queryFn: () => api.events.facets({ project_id: projectId, run_id: runId, experiment_id: filters.experiment_id }) });
  const experiments = useQuery({ queryKey: ["experiments", projectId ?? "all"], queryFn: () => api.experiments.list(projectId ? { project_id: projectId } : {}) });
  // Names are resolved here, for this viewer only: the stored events and every
  // export keep the opaque ids.
  const items = (q.data?.items ?? []) as EventRecord[];
  const names = useEntityNames(items);
  // Within one run, an event that has video gets a link straight to its clip.
  const recordings = useQuery({ queryKey: ["recordings", runId], queryFn: () => api.recordings.forRun(runId!), enabled: !!runId });
  const clips = recordings.data ?? [];
  const clipAt = (t: number) => clips.find((r) => t >= r.media_start_s - 0.05 && t <= r.media_end_s + 0.05);
  // The column exists only for a browser holding a recognition token; the
  // stored events carry the opaque id either way.
  const rtoken = useRecognitionAuth((s) => s.token);
  const showIdentity = !!rtoken && items.some((e) => !!(e.context?.entity as unknown));
  const set = (k: string, v: string) => {
    setFilters({ ...filters, [k]: v });
    setPage(1);
  };
  const toggleSort = (key: string) => {
    if (sort === key) setOrder(order === "asc" ? "desc" : "asc");
    else {
      setSort(key);
      setOrder("desc");
    }
  };
  const exportParams = { ...filters, project_id: projectId, run_id: runId ?? filters.run_id };
  const total = q.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="stack">
      {!embedded && (
        <div className="page-head">
          <div>
            <h1>Data</h1>
            <div className="sub">Every stored event with its anonymous track id. Filter, sort and export as CSV, JSON or Parquet.</div>
          </div>
        </div>
      )}
      <Panel title="Filters">
        <div className="form-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
          {!runId && (
            <Field label="Experiment">
              <select value={filters.experiment_id ?? ""} onChange={(e) => set("experiment_id", e.target.value)}>
                <option value="">All</option>
                {experiments.data?.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {!runId && (
            <Field label="Run">
              <input type="number" value={filters.run_id ?? ""} onChange={(e) => set("run_id", e.target.value)} placeholder="any" />
            </Field>
          )}
          <Field label="Event type">
            <select value={filters.event_type ?? ""} onChange={(e) => set("event_type", e.target.value)}>
              <option value="">All</option>
              {facets.data?.event_type.map((f) => (
                <option key={f.value} value={f.value}>
                  {eventLabel(f.value)} ({f.count})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Route">
            <select value={filters.route ?? ""} onChange={(e) => set("route", e.target.value)}>
              <option value="">All</option>
              {facets.data?.route.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.value} ({f.count})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Object class">
            <select value={filters.object_class ?? ""} onChange={(e) => set("object_class", e.target.value)}>
              <option value="">All</option>
              {facets.data?.object_class.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.value} ({f.count})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Track id">
            <input type="number" value={filters.track_id ?? ""} onChange={(e) => set("track_id", e.target.value)} placeholder="any" />
          </Field>
          <Field label="Media time from / to (s)">
            <div className="row">
              <input type="number" value={filters.from_s ?? ""} onChange={(e) => set("from_s", e.target.value)} />
              <input type="number" value={filters.to_s ?? ""} onChange={(e) => set("to_s", e.target.value)} />
            </div>
          </Field>
          <Field label="Date from">
            <input type="datetime-local" value={filters.from_time ?? ""} onChange={(e) => set("from_time", e.target.value)} />
          </Field>
          <Field label="Date to">
            <input type="datetime-local" value={filters.to_time ?? ""} onChange={(e) => set("to_time", e.target.value)} />
          </Field>
          <Field label="Search">
            <input type="search" value={filters.search ?? ""} onChange={(e) => set("search", e.target.value)} placeholder="object, route, rule…" />
          </Field>
        </div>
        <div className="row" style={{ marginTop: 10, justifyContent: "space-between" }}>
          <span className="hint">{q.data ? `${num(total, 0)} events` : ""}</span>
          <span className="row">
            <button className="btn sm" onClick={() => { setFilters({}); setPage(1); }}>
              Clear filters
            </button>
            <span className="divider" />
            <span className="small muted">Export</span>
            <a className="btn sm" href={api.events.exportUrl({ ...exportParams, format: "csv" })}>
              CSV
            </a>
            <a className="btn sm" href={api.events.exportUrl({ ...exportParams, format: "json" })}>
              JSON
            </a>
            <a className="btn sm" href={api.events.exportUrl({ ...exportParams, format: "parquet" })}>
              Parquet
            </a>
          </span>
        </div>
      </Panel>
      <Panel title="Events" flush>
        {q.isError && <ErrorNotice error={q.error} />}
        {q.data && q.data.items.length === 0 && <Empty>No events match these filters.</Empty>}
        {q.data && q.data.items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  {COLUMNS.map((c) => (
                    <th key={c.key} className={`${c.num ? "num" : ""} sortable`} onClick={() => toggleSort(c.key)}>
                      {c.label}
                      {sort === c.key ? (order === "asc" ? " ▲" : " ▼") : ""}
                    </th>
                  ))}
                  {showIdentity && <th title="Only shown to browsers with a recognition token; the stored event holds the id only.">Identity</th>}
                  {clips.length > 0 && <th>Video</th>}
                </tr>
              </thead>
              <tbody>
                {items.map((e) => (
                  <tr key={e.id} className="clickable" onClick={() => setDetail(e)}>
                    {COLUMNS.map((c) => (
                      <td key={c.key} className={c.num ? "num" : ""}>
                        {c.render(e)}
                      </td>
                    ))}
                    {showIdentity && (
                      <td>
                        <IdentityCell e={e} names={names.data} />
                      </td>
                    )}
                    {clips.length > 0 && (
                      <td onClick={(ev) => ev.stopPropagation()}>
                        {clipAt(e.media_time_s) ? (
                          <Link className="btn sm" to={`/review/${e.run_id}?event=${e.id}&t=${e.media_time_s}`}>
                            Watch
                          </Link>
                        ) : (
                          <span className="hint">no video</span>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="row" style={{ padding: 8, justifyContent: "space-between" }}>
          <span className="row">
            <button className="btn sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
              Previous
            </button>
            <span className="small muted">
              Page {page} of {pages}
            </span>
            <button className="btn sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>
              Next
            </button>
          </span>
          <select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }} style={{ width: "auto" }}>
            {[25, 50, 100, 250, 500].map((n) => (
              <option key={n} value={n}>
                {n} per page
              </option>
            ))}
          </select>
        </div>
      </Panel>
      {detail && (
        <Modal title={`Event #${detail.id}`} onClose={() => setDetail(null)} width={640}>
          <table className="table">
            <tbody>
              {Object.entries(detail).map(([k, v]) => (
                <tr key={k}>
                  <td className="muted">{k}</td>
                  <td className="wrap mono small">{typeof v === "object" ? JSON.stringify(v, null, 1) : String(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row" style={{ marginTop: 8 }}>
            <Link className="btn sm" to={`/review/${detail.run_id}?t=${detail.media_time_s}&event=${detail.id}`}>
              Jump to video
            </Link>
          </div>
        </Modal>
      )}
    </div>
  );
}
