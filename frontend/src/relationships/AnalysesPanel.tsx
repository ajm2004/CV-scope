/* The relationship analyses of one run: the live one and any re-analyses with
 * other rule versions. One is current; the others are kept for comparison. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { ConfirmButton, Empty, ErrorNotice, Panel, Pill, Progress } from "../components/ui";
import { dateTime } from "../lib/format";
import { useRecognitionAuth } from "../lib/recognitionToken";
import { rel } from "./api";
import { useMeta } from "./bits";

export default function AnalysesPanel({ runId, active }: { runId: number; active: boolean }) {
  const qc = useQueryClient();
  const token = useRecognitionAuth((s) => s.token);
  const meta = useMeta();
  const list = useQuery({
    queryKey: ["relationship-analyses", runId, token],
    queryFn: () => rel.analyses({ run_id: runId }),
    refetchInterval: (q) => (q.state.data?.some((a) => a.status === "running") ? 1500 : false),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["relationship-analyses", runId] });
  const analyse = useMutation({ mutationFn: () => rel.analyse(runId, null), onSuccess: refresh });
  const current = useMutation({ mutationFn: (id: number) => rel.makeCurrent(id), onSuccess: refresh });
  const remove = useMutation({ mutationFn: (id: number) => rel.removeAnalysis(id), onSuccess: refresh });
  const can = meta.data?.viewer.can;

  return (
    <Panel
      title="Relationship analyses"
      actions={
        <span className="row">
          <Link className="btn sm" to={`/relationships/timeline?run=${runId}`}>
            Timeline
          </Link>
          {can?.rules && (
            <button className="btn sm" disabled={active || analyse.isPending} onClick={() => analyse.mutate()} title={active ? "Wait until the run has ended" : "Replay the stored trajectories with the experiment's current rule versions"}>
              Analyse again
            </button>
          )}
        </span>
      }
      flush
    >
      {(list.error || analyse.error || current.error || remove.error) && <ErrorNotice error={list.error || analyse.error || current.error || remove.error} />}
      {list.isLoading && <div className="hint" style={{ padding: 10 }}>Loading…</div>}
      {list.data && list.data.length === 0 && (
        <Empty>
          No relationship analysis for this run. Turn on Relationships in the experiment for new runs, or analyse this run now (it needs stored trajectories).
        </Empty>
      )}
      {list.data && list.data.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>#</th>
                <th>Kind</th>
                <th>Rules (version)</th>
                <th>Measured in</th>
                <th className="num">Relationships</th>
                <th className="num">Correlated</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((a) => (
                <tr key={a.id}>
                  <td className="num">{a.id}</td>
                  <td>
                    {a.source === "live" ? "live run" : "re-analysis"}
                    <div className="hint">{dateTime(a.started_at)}</div>
                  </td>
                  <td className="small">{a.rules.length ? a.rules.map((r) => `${r.name || r.key} v${r.version}`).join(", ") : <span className="hint">built-in only</span>}</td>
                  <td className="small">{a.calibration.measure === "physical" ? "metres" : a.calibration.measure === "scene-relative" ? "frame widths (uncalibrated)" : "–"}</td>
                  <td className="num">{String(a.stats.relationships ?? "–")}</td>
                  <td className="num">
                    {String(a.stats.correlated ?? "–")}
                    {Number(a.stats.deviations ?? 0) > 0 && <div className="hint">{String(a.stats.deviations)} deviations</div>}
                  </td>
                  <td>
                    {a.status === "running" ? (
                      <>
                        <Pill tone="accent">running</Pill>
                        {a.job && <Progress value={a.job.progress} />}
                      </>
                    ) : a.status === "failed" ? (
                      <Pill tone="err">failed</Pill>
                    ) : a.current ? (
                      <Pill tone="ok">current</Pill>
                    ) : (
                      <Pill>kept</Pill>
                    )}
                    {a.error && <div className="hint">{a.error}</div>}
                  </td>
                  <td className="nowrap">
                    {a.status === "done" && !a.current && can?.rules && (
                      <button className="btn sm ghost" onClick={() => current.mutate(a.id)}>
                        Make current
                      </button>
                    )}
                    {a.status !== "running" && can?.delete && <ConfirmButton label="Delete" confirm="Delete analysis?" onConfirm={() => remove.mutate(a.id)} className="btn sm ghost" />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="hint" style={{ padding: 10 }}>
        The current analysis is what the explorer, timeline and search show. Earlier interpretations stay available (for example with a stricter distance) and are never overwritten.
      </div>
    </Panel>
  );
}
