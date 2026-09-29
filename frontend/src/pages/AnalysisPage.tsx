import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import { BarList, bucketsToSeries, StackedSeries } from "../components/charts";
import { Empty, ErrorNotice, Notice, Panel, Stat } from "../components/ui";
import { num, pct, seconds, speedUnit } from "../lib/format";

export function RouteDistribution({ routes }: { routes: Record<string, any> }) {
  const dist = (routes?.distribution ?? []) as { route: string; count: number; is_outcome: boolean; share_of_valid: number | null; mean_duration_s: number | null; median_duration_s: number | null; mean_speed: number | null }[];
  if (!dist.length) return <Empty>No route observations. Draw routes in the scene (start gate, optional checkpoints, end gate) to record them.</Empty>;
  return (
    <div className="stack">
      <div className="stat-row">
        <Stat value={routes.total_observations} label="Total observations" />
        <Stat value={routes.valid_observations} label="Valid (route completed)" />
        <Stat value={routes.unknown} label="Unknown" />
        <Stat value={routes.abandoned} label="Abandoned (timeout)" />
        <Stat value={routes.lost_track} label="Lost track" />
      </div>
      <BarList items={dist.map((d) => ({ label: d.route, value: d.count, muted: d.is_outcome }))} total={routes.total_observations} />
      <table className="table">
        <thead>
          <tr>
            <th>Route</th>
            <th className="num">Count</th>
            <th className="num">Share of valid</th>
            <th className="num">Mean duration</th>
            <th className="num">Median duration</th>
            <th className="num">Mean speed ({speedUnit(routes.speed_unit) || "–"})</th>
          </tr>
        </thead>
        <tbody>
          {dist.map((d) => (
            <tr key={d.route} className={d.is_outcome ? "muted" : ""}>
              <td>{d.route}</td>
              <td className="num">{d.count}</td>
              <td className="num">{d.share_of_valid != null ? pct(d.share_of_valid) : "–"}</td>
              <td className="num">{seconds(d.mean_duration_s, 2)}</td>
              <td className="num">{seconds(d.median_duration_s, 2)}</td>
              <td className="num">{num(d.mean_speed, 3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="grid-2">
        <div>
          <div className="section-title">Behavioural measurements</div>
          <table className="table">
            <tbody>
              <tr>
                <td>Mean decision time (start to the next line or zone passed)</td>
                <td className="num">{seconds(routes.mean_decision_time_s, 2)}</td>
              </tr>
              <tr>
                <td>Route switches (checkpoint of another route passed first)</td>
                <td className="num">{routes.route_switches}</td>
              </tr>
              <tr>
                <td>Same route as the previous observation</td>
                <td className="num">
                  {routes.following?.same_as_previous} of {routes.following?.with_previous} ({pct(routes.following?.same_share)})
                </td>
              </tr>
              {Object.entries((routes.occupancy_at_decision ?? {}) as Record<string, { mean: number; n: number }>).map(([r, v]) => (
                <tr key={r}>
                  <td>Mean route-group occupancy when choosing {r}</td>
                  <td className="num">
                    {num(v.mean, 2)} (n={v.n})
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <div className="section-title">Previous choice → this choice</div>
          {(routes.following?.pairs ?? []).length === 0 ? (
            <div className="hint">Needs at least two completed observations.</div>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Previous</th>
                  <th>Route</th>
                  <th className="num">Count</th>
                </tr>
              </thead>
              <tbody>
                {(routes.following.pairs as { previous: string; route: string; count: number }[]).map((p, i) => (
                  <tr key={i}>
                    <td>{p.previous}</td>
                    <td>{p.route}</td>
                    <td className="num">{p.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
      <Notice>These are observable movement measurements. Correlations with crowd level or previous choices describe the recorded scene; they are not evidence of psychological causes.</Notice>
    </div>
  );
}

export function CrossingsTable({ crossings }: { crossings: Record<string, any>[] }) {
  if (!crossings.length) return <div className="hint">No line crossings recorded.</div>;
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Line / gate</th>
          <th className="num">Total</th>
          <th className="num">Forward</th>
          <th className="num">Reverse</th>
          <th>By class</th>
        </tr>
      </thead>
      <tbody>
        {crossings.map((c) => (
          <tr key={c.object_id}>
            <td>{c.object_name || c.object_id}</td>
            <td className="num">
              <strong>{c.total}</strong>
            </td>
            <td className="num">{c.forward}</td>
            <td className="num">{c.reverse}</td>
            <td className="small muted">
              {Object.entries(c.by_class as Record<string, number>)
                .map(([k, v]) => `${k} ${v}`)
                .join(" · ")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ZonesTable({ zones }: { zones: Record<string, any>[] }) {
  if (!zones.length) return <div className="hint">No zone events recorded.</div>;
  const withHours = zones.filter((z) => (z.occupied_by_hour ?? []).length > 0);
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Zone</th>
              <th className="num" title="Time with at least one object inside">Occupied time</th>
              <th className="num" title="Sum of all visits (two people for 1 min = 2 min)">Total time, all objects</th>
              <th className="num">Visits</th>
              <th className="num">Mean visit</th>
              <th className="num">Median visit</th>
              <th className="num">Longest visit</th>
              <th className="num">Max occupancy</th>
              <th className="num">Long visits flagged</th>
            </tr>
          </thead>
          <tbody>
            {zones.map((z) => (
              <tr key={z.object_id}>
                <td>{z.object_name || z.object_id}</td>
                <td className="num">
                  <strong>{seconds(z.occupied_s, 0)}</strong>
                </td>
                <td className="num">{seconds(z.total_dwell_s, 0)}</td>
                <td className="num">{z.exits}</td>
                <td className="num">{seconds(z.mean_dwell_s, 1)}</td>
                <td className="num">{seconds(z.median_dwell_s, 1)}</td>
                <td className="num">{seconds(z.max_dwell_s, 1)}</td>
                <td className="num">{z.max_occupancy}</td>
                <td className="num">{z.dwell_exceeded}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {withHours.map((z) => (
        <div key={`h-${z.object_id}`}>
          <div className="section-title">{z.object_name || z.object_id}: occupied time per hour</div>
          <table className="table">
            <tbody>
              {(z.occupied_by_hour as { hour: string; seconds: number }[]).map((h) => (
                <tr key={h.hour}>
                  <td style={{ width: 220 }}>{new Date(h.hour).toLocaleString(undefined, { weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</td>
                  <td style={{ width: "100%" }}>
                    <div style={{ height: 10, background: "var(--surface-3)", borderRadius: 2 }}>
                      <div style={{ width: `${Math.min(100, (h.seconds / 3600) * 100)}%`, height: "100%", background: "var(--accent)", borderRadius: 2 }} />
                    </div>
                  </td>
                  <td className="num">{seconds(h.seconds, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      <div className="hint">A visit ends when the object leaves the zone for longer than the zone's <em>Ignore exits shorter than</em> time, when it has not been seen for the lost-track time, or when the run stops.</div>
    </div>
  );
}

export default function AnalysisPage({ projectId, embedded = false }: { projectId?: number; embedded?: boolean }) {
  const experiments = useQuery({ queryKey: ["experiments", projectId ?? "all"], queryFn: () => api.experiments.list(projectId ? { project_id: projectId } : {}) });
  const [selected, setSelected] = useState<number | "">("");
  const [compare, setCompare] = useState<number[]>([]);
  const summary = useQuery({ queryKey: ["experiment-summary", selected], queryFn: () => api.analytics.experiment(Number(selected)), enabled: selected !== "" });
  const cmp = useQuery({ queryKey: ["compare", compare], queryFn: () => api.analytics.compare(compare), enabled: compare.length > 1 });
  const s = summary.data;
  const hourly = s ? bucketsToSeries(s.hourly) : null;
  return (
    <div className="stack">
      {!embedded && (
        <div className="page-head">
          <div>
            <h1>Analysis</h1>
            <div className="sub">Route distribution, counts, dwell and time series per experiment, and side-by-side comparison of experiments.</div>
          </div>
        </div>
      )}
      <Panel title="Experiment">
        <div className="row wrap">
          <select value={selected} onChange={(e) => setSelected(e.target.value ? Number(e.target.value) : "")} style={{ maxWidth: 420 }}>
            <option value="">Select an experiment…</option>
            {experiments.data?.map((e) => (
              <option key={e.id} value={e.id}>
                {e.name} ({e.run_count} runs)
              </option>
            ))}
          </select>
          {selected !== "" && (
            <Link className="btn sm" to={`/experiments/${selected}`}>
              Open experiment
            </Link>
          )}
        </div>
      </Panel>
      {summary.isError && <ErrorNotice error={summary.error} />}
      {s && (
        <>
          <div className="stat-row">
            <Stat value={s.runs.length} label="Runs" />
            <Stat value={s.event_count} label="Events" />
            <Stat value={s.tracks.count ?? 0} label="Anonymous tracks" />
            <Stat value={seconds(s.tracks.mean_lifetime_s)} label="Mean track lifetime" />
            <Stat value={s.tracks.mean_speed != null ? `${num(s.tracks.mean_speed, 2)} ${speedUnit(s.tracks.speed_unit)}` : "–"} label="Mean speed" />
          </div>
          {new Set((s.runs as Record<string, any>[]).map((r) => r.scene_version).filter((v) => v != null)).size > 1 && (
            <Notice tone="warn">
              The runs of this experiment used different scene versions ({[...new Set((s.runs as Record<string, any>[]).map((r) => r.scene_version).filter((v) => v != null))].map((v) => `v${v}`).join(", ")}). Totals below combine them. Compare runs of one version, or pin a version on the experiment page.
            </Notice>
          )}
          <Panel title="Route distribution (all runs)">
            <RouteDistribution routes={s.routes} />
          </Panel>
          <div className="grid-2">
            <Panel title="Line crossings">
              <CrossingsTable crossings={s.crossings} />
            </Panel>
            <Panel title="Zones">
              <ZonesTable zones={s.zones} />
            </Panel>
          </div>
          <div className="grid-2">
            <Panel title="Events per hour (wall clock)">
              {hourly && <StackedSeries data={hourly.data} series={hourly.series} formatX={(x) => new Date(String(x)).toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit" })} />}
            </Panel>
            <Panel title="Routes by run">
              <table className="table">
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Status</th>
                    <th>Scene</th>
                    <th className="num">Events</th>
                    <th>Routes</th>
                  </tr>
                </thead>
                <tbody>
                  {(s.runs as Record<string, any>[]).map((r) => (
                    <tr key={r.id}>
                      <td>
                        <Link to={`/analysis/runs/${r.id}`}>#{r.id}</Link>
                      </td>
                      <td>{r.status}</td>
                      <td className="muted">{r.scene_version != null ? `v${r.scene_version}` : "–"}</td>
                      <td className="num">{r.events}</td>
                      <td className="small muted">
                        {((s.by_run_routes?.[r.id] ?? []) as { route: string; count: number }[]).map((d) => `${d.route} ${d.count}`).join(" · ") || "–"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          </div>
          <Panel title="Object classes">
            <BarList items={Object.entries((s.classes?.tracks ?? {}) as Record<string, number>).map(([k, v]) => ({ label: k, value: v }))} />
          </Panel>
        </>
      )}
      <Panel title="Compare experiments" actions={<span className="hint">Pick two or more</span>}>
        <div className="row wrap">
          {experiments.data?.map((e) => (
            <label key={e.id} className="check">
              <input type="checkbox" checked={compare.includes(e.id)} onChange={(ev) => setCompare(ev.target.checked ? [...compare, e.id] : compare.filter((x) => x !== e.id))} />
              {e.name}
            </label>
          ))}
        </div>
        {cmp.data && (
          <table className="table" style={{ marginTop: 10 }}>
            <thead>
              <tr>
                <th>Experiment</th>
                <th>Condition</th>
                <th className="num">Events</th>
                <th className="num">Observations</th>
                <th className="num">Valid</th>
                <th>Routes (share of valid)</th>
                <th className="num">Unknown</th>
                <th className="num">Mean decision time</th>
              </tr>
            </thead>
            <tbody>
              {cmp.data.experiments.map((x) => (
                <tr key={x.experiment_id}>
                  <td>{x.name}</td>
                  <td className="muted wrap">{x.condition_notes || "–"}</td>
                  <td className="num">{x.event_count}</td>
                  <td className="num">{x.routes.total_observations}</td>
                  <td className="num">{x.routes.valid_observations}</td>
                  <td className="small">
                    {(x.routes.distribution as { route: string; count: number; share_of_valid: number | null; is_outcome: boolean }[])
                      .filter((d) => !d.is_outcome)
                      .map((d) => `${d.route} ${d.count} (${pct(d.share_of_valid)})`)
                      .join(" · ") || "–"}
                  </td>
                  <td className="num">{x.routes.unknown + x.routes.abandoned + x.routes.lost_track}</td>
                  <td className="num">{seconds(x.routes.mean_decision_time_s, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
