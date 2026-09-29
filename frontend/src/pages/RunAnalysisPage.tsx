import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { api } from "../api/client";
import type { EventRecord } from "../api/types";
import { BarList, bucketsToSeries, Heatmap, StackedSeries } from "../components/charts";
import { ErrorNotice, Field, KV, Notice, Panel, Pill, Stat, Tabs } from "../components/ui";
import { clock, dateTime, eventLabel, num, pct, seconds, speedUnit } from "../lib/format";
import { CrossingsTable, RouteDistribution, ZonesTable } from "./AnalysisPage";
import RunVideo from "../components/RunVideo";
import AnalysesPanel from "../relationships/AnalysesPanel";
import DataPage from "./DataPage";

const VERDICTS = [
  { id: "correct", label: "Correct" },
  { id: "incorrect", label: "Incorrect" },
  { id: "wrong_route", label: "Wrong route" },
  { id: "wrong_class", label: "Wrong object class" },
  { id: "tracking_error", label: "Tracking error" },
];

function EvaluationWorkspace({ runId, sceneObjects }: { runId: number; sceneObjects: { id: string; name: string; type: string }[] }) {
  const qc = useQueryClient();
  const events = useQuery({ queryKey: ["eval-events", runId], queryFn: () => api.events.list({ run_id: runId, event_type: "route,crossing,zone_entry,zone_exit,dwell,sequence,rule", page_size: 500, sort: "media_time_s", order: "asc" }) });
  const evals = useQuery({ queryKey: ["evaluations", runId], queryFn: () => api.evaluations.list(runId) });
  const metrics = useQuery({ queryKey: ["eval-metrics", runId], queryFn: () => api.evaluations.metrics(runId) });
  const gts = useQuery({ queryKey: ["ground-truth", runId], queryFn: () => api.evaluations.groundTruth(runId) });
  const [missedNote, setMissedNote] = useState("");
  const [gtObject, setGtObject] = useState("");
  const [gtCount, setGtCount] = useState<number | "">("");
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["evaluations", runId] });
    qc.invalidateQueries({ queryKey: ["eval-metrics", runId] });
    qc.invalidateQueries({ queryKey: ["ground-truth", runId] });
  };
  const mark = useMutation({ mutationFn: (b: { event_id?: number; verdict: string; note?: string }) => api.evaluations.create({ run_id: runId, ...b }), onSuccess: invalidate });
  const unmark = useMutation({ mutationFn: (id: number) => api.evaluations.remove(id), onSuccess: invalidate });
  const setGt = useMutation({ mutationFn: () => api.evaluations.setGroundTruth({ run_id: runId, object_id: gtObject, label: sceneObjects.find((o) => o.id === gtObject)?.name ?? gtObject, count: Number(gtCount) }), onSuccess: invalidate });
  const byEvent = new Map((evals.data ?? []).filter((e) => e.event_id != null).map((e) => [e.event_id!, e]));
  const m = metrics.data;
  return (
    <div className="stack">
      <Notice>Mark a subset of events as correct or incorrect after watching the video. Metrics below use only your verdicts and the ground-truth counts you enter; nothing is estimated.</Notice>
      {m && (
        <div className="stat-row">
          <Stat value={m.reviewed_events} label="Events reviewed" />
          <Stat value={m.route_classification_accuracy_percent != null ? pct(m.route_classification_accuracy_percent) : "–"} label={`Route classification accuracy (${m.route_reviews} reviewed)`} />
          <Stat value={m.precision_percent != null ? pct(m.precision_percent) : "–"} label="Precision (reviewed)" />
          <Stat value={m.recall_percent != null ? pct(m.recall_percent) : "–"} label="Recall (needs missed events)" />
          <Stat value={m.tracking_errors} label="Tracking errors" />
          <Stat value={m.verdicts?.missed ?? 0} label="Missed events logged" />
        </div>
      )}
      <div className="grid-2" style={{ gridTemplateColumns: "minmax(0, 1.5fr) minmax(0, 1fr)" }}>
        <Panel title="Events to review" flush>
          <div className="table-wrap" style={{ maxHeight: 480 }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Event</th>
                  <th>Object</th>
                  <th>Route</th>
                  <th className="num">Track</th>
                  <th>Verdict</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {(events.data?.items as EventRecord[] | undefined)?.map((e) => {
                  const v = byEvent.get(e.id);
                  return (
                    <tr key={e.id}>
                      <td>
                        <Link to={`/review/${runId}?t=${e.media_time_s}&event=${e.id}`}>{clock(e.media_time_s)}</Link>
                      </td>
                      <td>{eventLabel(e.event_type)}</td>
                      <td>{e.object_name ?? "–"}</td>
                      <td>{e.route ?? "–"}</td>
                      <td className="num">{e.track_id}</td>
                      <td>{v ? <Pill tone={v.verdict === "correct" ? "ok" : "err"}>{v.verdict.replace("_", " ")}</Pill> : <span className="muted">not reviewed</span>}</td>
                      <td>
                        <select value={v?.verdict ?? ""} onChange={(ev) => (ev.target.value ? mark.mutate({ event_id: e.id, verdict: ev.target.value }) : v && unmark.mutate(v.id))} style={{ width: 150 }}>
                          <option value="">—</option>
                          {VERDICTS.map((o) => (
                            <option key={o.id} value={o.id}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>
        <div className="stack">
          <Panel title="Missed events">
            <p className="small muted">Log an event the system should have recorded but did not. Counts towards recall.</p>
            <div className="inline-form">
              <Field label="Note (what happened, when)">
                <input type="text" value={missedNote} onChange={(e) => setMissedNote(e.target.value)} placeholder="Person crossed Exit Left at 00:41" />
              </Field>
              <button className="btn" onClick={() => { mark.mutate({ verdict: "missed", note: missedNote }); setMissedNote(""); }} disabled={!missedNote.trim()}>
                Log missed event
              </button>
            </div>
            <ul className="list-plain" style={{ marginTop: 8 }}>
              {(evals.data ?? []).filter((e) => e.verdict === "missed").map((e) => (
                <li key={e.id} className="row">
                  <span className="grow">{e.note}</span>
                  <button className="btn sm ghost" onClick={() => unmark.mutate(e.id)}>
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          </Panel>
          <Panel title="Manual counts (counting error)">
            <div className="inline-form">
              <Field label="Line or zone">
                <select value={gtObject} onChange={(e) => setGtObject(e.target.value)}>
                  <option value="">Select…</option>
                  {sceneObjects.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name} ({o.type})
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Your count">
                <input type="number" min="0" value={gtCount} onChange={(e) => setGtCount(e.target.value === "" ? "" : Number(e.target.value))} style={{ width: 90 }} />
              </Field>
              <button className="btn" onClick={() => setGt.mutate()} disabled={!gtObject || gtCount === ""}>
                Save count
              </button>
            </div>
            {(m?.counting?.length ?? 0) > 0 && (
              <table className="table" style={{ marginTop: 8 }}>
                <thead>
                  <tr>
                    <th>Object</th>
                    <th className="num">Manual</th>
                    <th className="num">System</th>
                    <th className="num">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {((m?.counting ?? []) as Record<string, any>[]).map((c) => (
                    <tr key={c.object_id}>
                      <td>{c.label || c.object_id}</td>
                      <td className="num">{c.ground_truth}</td>
                      <td className="num">{c.system}</td>
                      <td className="num">
                        {c.error > 0 ? "+" : ""}
                        {c.error} {c.error_percent != null ? `(${pct(c.error_percent)})` : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {gts.data && gts.data.length === 0 && <div className="hint" style={{ marginTop: 6 }}>No manual counts entered yet.</div>}
          </Panel>
        </div>
      </div>
    </div>
  );
}

export default function RunAnalysisPage() {
  const { runId } = useParams();
  const id = Number(runId);
  const run = useQuery({ queryKey: ["run", id], queryFn: () => api.runs.get(id), refetchInterval: (q) => (q.state.data?.live ? 3000 : false) });
  const summary = useQuery({ queryKey: ["run-summary", id], queryFn: () => api.analytics.run(id), refetchInterval: run.data?.live ? 5000 : false });
  const heat = useQuery({ queryKey: ["heatmap", id], queryFn: () => api.analytics.heatmap(id, 64) });
  const scene = useQuery({ queryKey: ["scene", run.data?.scene_config_id], queryFn: () => api.scenes.get(run.data!.scene_config_id!), enabled: !!run.data?.scene_config_id });
  const experiment = useQuery({ queryKey: ["experiment", run.data?.experiment_id], queryFn: () => api.experiments.get(run.data!.experiment_id), enabled: !!run.data });
  const [tab, setTab] = useState("summary");
  if (run.isError) return <ErrorNotice error={run.error} />;
  if (!run.data) return <div className="hint">Loading run…</div>;
  const r = run.data;
  const s = summary.data;
  const series = s ? bucketsToSeries(s.media_series) : null;
  const stats = (s?.stats ?? r.stats ?? {}) as Record<string, any>;
  const aspect = scene.data ? scene.data.document.frame_width / scene.data.document.frame_height : 16 / 9;
  const sceneObjects = (scene.data?.document.objects ?? []).filter((o) => o.type !== "ignore").map((o) => ({ id: o.id, name: o.name, type: o.type }));
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>
            Run #{r.id} {experiment.data ? `— ${experiment.data.name}` : ""}
          </h1>
          <div className="sub">
            <Pill tone={r.status === "running" ? "ok" : r.status === "failed" ? "err" : ""}>{r.status}</Pill> started {dateTime(r.started_at)} · ended {dateTime(r.ended_at)} · scene v{String(r.snapshot?.scene_version ?? "?")} · {String(r.snapshot?.resolution ?? "")}
          </div>
        </div>
        <div className="row">
          <Link className="btn" to={`/review/${r.id}`}>
            Video review
          </Link>
          <Link className="btn" to={`/experiments/${r.experiment_id}`}>
            Experiment
          </Link>
          <a className="btn" href={api.events.exportUrl({ run_id: r.id, format: "csv" })}>
            Export CSV
          </a>
        </div>
      </div>
      {r.error && <Notice tone="err">{r.error}</Notice>}
      <Tabs
        tabs={[
          { id: "summary", label: "Summary" },
          { id: "events", label: "Events" },
          { id: "video", label: "Video" },
          { id: "tracks", label: "Tracks and heatmap" },
          { id: "evaluation", label: "Evaluation" },
          { id: "relationships", label: "Relationships" },
          { id: "diagnostics", label: "Diagnostics" },
        ]}
        active={tab}
        onChange={setTab}
      />
      {tab === "summary" && s && (
        <div className="stack">
          <div className="stat-row">
            <Stat value={s.event_count} label="Events" />
            <Stat value={s.tracks.count ?? 0} label="Anonymous tracks" />
            <Stat value={clock(s.media_span_s)} label="Media analysed" />
            <Stat value={s.crossings_per_hour_media != null ? num(s.crossings_per_hour_media, 0) : "–"} label="Crossings per hour (media time)" />
            <Stat value={s.tracks.mean_speed != null ? `${num(s.tracks.mean_speed, 2)} ${speedUnit(s.tracks.speed_unit)}` : "–"} label="Mean track speed" />
          </div>
          <Panel title="Routes">
            <RouteDistribution routes={s.routes} />
          </Panel>
          <div className="grid-2">
            <Panel title="Line crossings">
              <CrossingsTable crossings={s.crossings} />
            </Panel>
            <Panel title="Zones (occupancy and dwell)">
              <ZonesTable zones={s.zones} />
            </Panel>
          </div>
          <div className="grid-2">
            <Panel title="Events over media time (per minute)">{series && <StackedSeries data={series.data} series={series.series} formatX={(x) => clock(Number(x))} xLabel="media time" />}</Panel>
            <Panel title="Object classes (tracks)">
              <BarList items={Object.entries((s.classes?.tracks ?? {}) as Record<string, number>).map(([k, v]) => ({ label: k, value: v }))} />
              <div className="section-title">Events by type</div>
              <BarList items={Object.entries((s.events_by_type ?? {}) as Record<string, number>).map(([k, v]) => ({ label: eventLabel(k), value: v }))} />
            </Panel>
          </div>
        </div>
      )}
      {tab === "events" && <DataPage runId={id} embedded />}
      {tab === "video" && <RunVideo runId={id} isFile={String(r.snapshot?.source_type ?? "") === "file"} />}
      {tab === "tracks" && (
        <div className="grid-2">
          <Panel title="Trajectory heatmap (sampled ground positions)">
            {heat.data && heat.data.samples > 0 ? <Heatmap cells={heat.data.cells} grid={heat.data.grid} width={560} aspect={aspect} /> : <div className="empty">No trajectories stored for this run (trajectory storage may be disabled in Settings).</div>}
            <div className="hint" style={{ marginTop: 6 }}>{heat.data?.samples ?? 0} samples</div>
          </Panel>
          <Panel title="Track statistics">
            {s && (
              <KV
                items={[
                  ["Tracks", s.tracks.count ?? 0],
                  ["Mean lifetime", seconds(s.tracks.mean_lifetime_s)],
                  ["Median lifetime", seconds(s.tracks.median_lifetime_s)],
                  ["Lost and reacquired", s.tracks.lost_reacquired ?? 0],
                  ["Still active at end", s.tracks.active_at_end ?? 0],
                  ["Mean detection confidence", num(s.tracks.mean_confidence, 2)],
                ]}
              />
            )}
            <div className="section-title">Tracker</div>
            <KV
              items={Object.entries((stats.tracker ?? {}) as Record<string, number>).map(([k, v]) => [k.replace(/_/g, " "), String(v)])}
            />
          </Panel>
        </div>
      )}
      {tab === "evaluation" && <EvaluationWorkspace runId={id} sceneObjects={sceneObjects} />}
      {tab === "relationships" && <AnalysesPanel runId={id} active={r.status === "running" || r.status === "starting" || r.status === "queued"} />}
      {tab === "diagnostics" && (
        <div className="grid-2">
          <Panel title="Pipeline">
            <KV
              items={[
                ["Frames read / processed", `${stats.read_frames ?? "–"} / ${stats.processed_frames ?? "–"}`],
                ["Pipeline FPS (last)", num(stats.pipeline_fps, 1)],
                ["Stream reconnects", stats.reconnects ?? 0],
                ...Object.entries((stats.timings_ms ?? {}) as Record<string, number>).map(([k, v]) => [`${k} ms (last frame)`, num(v, 2)] as [string, string]),
              ]}
            />
            <div className="section-title">Rule engine</div>
            <KV items={Object.entries((stats.rule_stats ?? {}) as Record<string, number>).map(([k, v]) => [k.replace(/_/g, " "), String(v)])} />
          </Panel>
          <Panel title="Configuration snapshot">
            <pre className="mono small" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
              {JSON.stringify(r.snapshot, null, 2)}
            </pre>
          </Panel>
        </div>
      )}
    </div>
  );
}
