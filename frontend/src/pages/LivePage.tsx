import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { api } from "../api/client";
import type { Counter } from "../api/types";
import { Empty, ErrorNotice, KV, Panel, Pill, Stat } from "../components/ui";
import { clock, eventLabel, num, pct, timeOnly } from "../lib/format";
import { useRecognitionAuth } from "../lib/recognitionToken";
import { entityLabel, useEntityNames } from "../recognition/useEntityNames";

interface ActiveRun {
  run_id: number;
  camera_id: number;
  camera_name: string | null;
  experiment_id: number;
  experiment_name: string | null;
  state: string;
  pipeline_fps: number | null;
  active_tracks: number | null;
  counters: Counter[] | null;
  zone_occupancy: Record<string, number> | null;
  progress: number | null;
  media_time_s: number | null;
  recording: { mode: string; active: boolean; files: number; bytes: number; dropped: number; error: string | null } | null;
  anomaly: { enabled: boolean; state: string; confirmed?: number; zones?: { id: string; name: string; state: string; confirmed: number; filtered: number }[] } | null;
  model: string;
  device: string;
  recent_events: Record<string, unknown>[];
}

export function CounterTable({ counters }: { counters: Counter[] }) {
  if (!counters.length) return <div className="hint">No counters configured in this scene.</div>;
  const groups = [...new Set(counters.map((c) => c.group))];
  return (
    <table className="table">
      <tbody>
        {groups.map((g) => (
          <>
            <tr key={g}>
              <td colSpan={2} className="muted" style={{ background: "var(--surface-2)", fontSize: "var(--fs-0)" }}>
                {g}
              </td>
            </tr>
            {counters
              .filter((c) => c.group === g)
              .map((c) => (
                <tr key={c.key}>
                  <td>{c.label}</td>
                  <td className="num">
                    <strong>{c.value}</strong>
                  </td>
                </tr>
              ))}
          </>
        ))}
      </tbody>
    </table>
  );
}

/** The name behind an event, for this viewer only. */
function EventIdentity({ context, names }: { context: Record<string, unknown> | undefined; names: ReturnType<typeof useEntityNames>["data"] }) {
  const label = entityLabel(context, names);
  if (!label || (!label.known && !label.possible)) return null;
  return (
    <span className={label.possible ? "warn-text" : "accent-text"}>
      {" "}
      {label.possible ? "? " : "= "}
      {label.text}
    </span>
  );
}

/**
 * Who the run recognizes at this moment. The list comes from the recognition
 * API, so it appears only for a browser with a recognition token; everyone
 * else sees the anonymous track numbers.
 */
function RecognizedNow({ runId, enabled }: { runId: number; enabled: boolean }) {
  const q = useQuery({
    queryKey: ["recognition-live-tracks", runId],
    queryFn: () => api.recognition.liveTracks(runId),
    refetchInterval: 1500,
    enabled,
    retry: 0,
  });
  if (!enabled || q.isError || !q.data) return null;
  const known = q.data.tracks.filter((t) => t.display_name || t.plate || t.vehicle_label);
  return (
    <>
      <div className="section-title">Recognized now</div>
      {known.length === 0 ? (
        <div className="hint">{q.data.tracks.length ? "Tracks are being checked; nobody recognized yet." : "No recognition on this run."}</div>
      ) : (
        <div className="event-feed">
          {known.map((t) => (
            <div key={t.track_id}>
              #{t.track_id} {t.object_class}{" "}
              <span className={t.status === "possible_match" ? "warn-text" : "accent-text"}>
                {t.status === "possible_match" ? "? " : "= "}
                {t.display_name ?? t.vehicle_label ?? t.plate}
              </span>
              {t.confidence != null ? <span className="muted small"> {num(t.confidence, 2)}</span> : null}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

export default function LivePage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["dashboard"], queryFn: api.analytics.dashboard, refetchInterval: 2000 });
  const load = useQuery({ queryKey: ["system-load"], queryFn: api.system.load, refetchInterval: 3000 });
  const stop = useMutation({ mutationFn: (id: number) => api.runs.stop(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["dashboard"] }) });
  const relearn = useMutation({ mutationFn: (id: number) => api.anomalies.rebaseline(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["dashboard"] }) });
  const rtoken = useRecognitionAuth((s) => s.token);
  const storedEvents = (q.data?.recent_events ?? []) as (Record<string, any> & { context?: Record<string, unknown> })[];
  const liveEvents = ((q.data?.active_runs ?? []) as ActiveRun[]).flatMap((r) => r.recent_events ?? []) as Record<string, unknown>[];
  const names = useEntityNames([...storedEvents, ...liveEvents] as { context?: Record<string, unknown> }[]);
  if (q.isError) return <ErrorNotice error={q.error} />;
  if (!q.data) return <div className="hint">Loading…</div>;
  const active = q.data.active_runs as ActiveRun[];
  const util = (load.data?.utilization ?? {}) as { cpu_percent?: number; memory_percent?: number; gpus?: { utilization_percent: number; vram_used_bytes: number; vram_total_bytes: number }[] };
  const est = (load.data?.estimate ?? {}) as { gpu_percent?: number; cpu_percent?: number; warning?: string | null; suggestions?: string[]; basis?: string };
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Live</h1>
          <div className="sub">Cameras that are currently being processed, with their counters and the newest events.</div>
        </div>
      </div>
      <div className="stat-row">
        <Stat value={active.length} label="Active runs" />
        <Stat value={active.reduce((a, r) => a + (r.active_tracks ?? 0), 0)} label="Objects currently tracked" />
        <Stat value={q.data.cameras} label="Cameras" />
        <Stat value={pct(util.cpu_percent ?? null, 0)} label="CPU" />
        <Stat value={util.gpus?.length ? pct(util.gpus[0].utilization_percent, 0) : "–"} label="GPU" />
        <Stat value={est.basis ? `${num(est.gpu_percent, 0)}% / ${num(est.cpu_percent, 0)}%` : "–"} label={`Pipeline load GPU / CPU (${est.basis ?? "estimate"})`} tone={est.warning ? "warn" : undefined} />
      </div>
      {est.warning && (
        <div className="notice warn">
          {est.warning} Options: {est.suggestions?.join(", ")}.
        </div>
      )}
      {active.length === 0 && (
        <Panel title="Active cameras">
          <Empty>
            Nothing is running. Start an experiment from the <Link to="/experiments">Experiments</Link> page or from a Scene Builder.
          </Empty>
        </Panel>
      )}
      {active.map((r) => (
        <Panel
          key={r.run_id}
          title={
            <span className="row">
              <Pill tone={r.state === "running" ? "ok" : r.state === "paused" ? "warn" : "accent"} dot>
                {r.state}
              </Pill>
              {r.camera_name ?? `Camera ${r.camera_id}`} — {r.experiment_name ?? `Experiment ${r.experiment_id}`}
              {r.recording && r.recording.mode !== "off" && (
                <span title={r.recording.error ? `Recording failed: ${r.recording.error}` : r.recording.mode === "events" ? "Records clips around events" : "Records the whole run"}>
                  <Pill tone={r.recording.error ? "err" : r.recording.active ? "err" : ""} dot={r.recording.active}>
                    {r.recording.error ? "Video failed" : r.recording.active ? "Recording" : "Video on"}
                    {r.recording.files ? ` · ${r.recording.files} saved` : ""}
                  </Pill>
                </span>
              )}
              {r.anomaly && (
                <Link to={`/anomalies?run=${r.run_id}`} title="Anomaly Assistant: open this run's anomalies">
                  <Pill tone={r.anomaly.state === "watching" ? ((r.anomaly.zones ?? []).some((z) => z.state === "active") ? "err" : "ok") : "accent"} dot={r.anomaly.state === "watching"}>
                    {r.anomaly.state === "watching" ? ((r.anomaly.zones ?? []).some((z) => z.state === "active") ? "Anomaly now" : "Watching for anomalies") : "Learning the normal picture"}
                    {r.anomaly.confirmed ? ` · ${r.anomaly.confirmed}` : ""}
                  </Pill>
                </Link>
              )}
            </span>
          }
          actions={
            <>
              <Link className="btn sm" to={`/scene/${r.camera_id}`}>
                Open scene
              </Link>
              <Link className="btn sm" to={`/analysis/runs/${r.run_id}`}>
                Analysis
              </Link>
              {r.anomaly && (
                <button className="btn sm" title="Learn the normal picture again from what the camera sees now" onClick={() => relearn.mutate(r.run_id)}>
                  Re-learn normal
                </button>
              )}
              <button className="btn sm danger" onClick={() => stop.mutate(r.run_id)}>
                Stop
              </button>
            </>
          }
        >
          <div className="grid-3" style={{ gridTemplateColumns: "minmax(280px, 1.4fr) minmax(220px, 1fr) minmax(220px, 1fr)" }}>
            <div className="video-stage" style={{ minHeight: 160 }}>
              <img src={`/api/runs/${r.run_id}/stream.mjpg${rtoken ? `?rtoken=${encodeURIComponent(rtoken)}` : ""}`} alt="Live preview" style={{ width: "100%", display: "block" }} />
            </div>
            <div>
              <KV
                items={[
                  ["Run", <Link to={`/analysis/runs/${r.run_id}`}>#{r.run_id}</Link>],
                  ["Detector", <span className="mono">{r.model} on {r.device}</span>],
                  ["Pipeline", `${num(r.pipeline_fps, 1)} fps`],
                  ["Tracked now", r.active_tracks ?? 0],
                  ["Media time", clock(r.media_time_s)],
                  ["Progress", r.progress != null ? pct(r.progress * 100, 0) : "live"],
                  ["Zone occupancy", r.zone_occupancy && Object.keys(r.zone_occupancy).length ? Object.values(r.zone_occupancy).join(", ") : "–"],
                ]}
              />
              <RecognizedNow runId={r.run_id} enabled={!!rtoken} />
              <div className="section-title">Recent events</div>
              <div className="event-feed">
                {(r.recent_events ?? []).slice(-8).reverse().map((e, i) => (
                  <div key={i}>
                    {clock(e.media_time_s as number)} {eventLabel(String(e.event_type))} {String(e.label ?? "")} #{String(e.track_id)}
                    <EventIdentity context={e.context as Record<string, unknown> | undefined} names={names.data} />
                  </div>
                ))}
              </div>
            </div>
            <div>
              <CounterTable counters={r.counters ?? []} />
            </div>
          </div>
        </Panel>
      ))}
      <div className="grid-2">
        <Panel title="Newest stored events" flush>
          {q.data.recent_events.length === 0 ? (
            <Empty>No events stored yet.</Empty>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Run</th>
                  <th>Event</th>
                  <th>Object</th>
                  <th>Route</th>
                  <th>Class</th>
                  <th className="num">Track</th>
                </tr>
              </thead>
              <tbody>
                {storedEvents.map((e) => (
                  <tr key={e.id}>
                    <td className="muted">{timeOnly(e.wall_time)}</td>
                    <td>
                      <Link to={`/analysis/runs/${e.run_id}`}>#{e.run_id}</Link>
                    </td>
                    <td>{eventLabel(e.event_type)}</td>
                    <td>{e.object_name ?? "–"}</td>
                    <td>{e.route ?? "–"}</td>
                    <td>{e.object_class}</td>
                    <td className="num">{e.track_id}</td>
                    {rtoken && (
                      <td>
                        {(() => {
                          const label = entityLabel(e.context, names.data);
                          if (!label || (!label.known && !label.possible)) return <span className="muted">–</span>;
                          return (
                            <Pill tone={label.possible ? "warn" : "accent"}>
                              {label.possible ? "? " : ""}
                              {label.text}
                            </Pill>
                          );
                        })()}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
        <Panel title="Recent runs" flush>
          <table className="table">
            <thead>
              <tr>
                <th>Run</th>
                <th>Experiment</th>
                <th>Status</th>
                <th className="num">Events</th>
                <th>Routes</th>
              </tr>
            </thead>
            <tbody>
              {(q.data.recent_runs as Record<string, any>[]).map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link to={`/analysis/runs/${r.id}`}>#{r.id}</Link>
                  </td>
                  <td>{r.experiment_name ?? r.experiment_id}</td>
                  <td>
                    <Pill tone={r.status === "running" ? "ok" : r.status === "failed" ? "err" : ""}>{r.status}</Pill>
                  </td>
                  <td className="num">{r.events}</td>
                  <td className="small muted">
                    {Object.entries(r.routes as Record<string, number>)
                      .map(([k, v]) => `${k} ${v}`)
                      .join(" · ") || "–"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>
    </div>
  );
}
