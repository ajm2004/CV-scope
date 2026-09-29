import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { FaceTrackDiagnostics, PlateTrackDiagnostics, RecognitionEvent } from "../api/types";
import { ConfirmButton, Empty, ErrorNotice, Field, KV, Modal, Notice, Panel, Pill } from "../components/ui";
import { clock, dateTime, num } from "../lib/format";
import { roleAtLeast } from "../lib/recognitionToken";
import { EVENT_KIND_LABEL, RESULT_LABEL, usePrincipal } from "./hooks";
import RecognitionGate from "./RecognitionGate";

function subject(e: RecognitionEvent): string {
  if (e.module === "face") return e.display_name ?? (e.person_id ? `(deleted profile)` : "–");
  const plate = e.plate_normalized ?? "–";
  return e.vehicle_label ? `${plate} · ${e.vehicle_label}` : plate;
}

function resultPill(result: string) {
  const tone = result === "recognized" ? "ok" : result === "possible_match" ? "warn" : result === "insufficient_quality" ? "err" : "";
  return <Pill tone={tone}>{RESULT_LABEL[result] ?? result}</Pill>;
}

function FaceDiagnostics({ tracks, model, stats }: { tracks: FaceTrackDiagnostics[]; model: Record<string, unknown>; stats: Record<string, number> }) {
  const m = model as { stack?: string; embedder?: { model_version?: string }; detector?: { model_version?: string } };
  return (
    <div>
      <div className="row wrap small muted" style={{ marginBottom: 6 }}>
        <span>Model: {m.detector?.model_version} + {m.embedder?.model_version} ({m.stack})</span>
        <span>attempts {stats.attempts} · faces {stats.faces_detected} · usable {stats.usable} · decisions {stats.decisions} · recognized {stats.recognized} · unknown {stats.unknown} · insufficient {stats.insufficient}</span>
      </div>
      {tracks.length === 0 ? (
        <div className="hint">No person track observed yet.</div>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th className="num">Track</th>
              <th>Face detected</th>
              <th>Face quality</th>
              <th>Observations</th>
              <th>Best frame</th>
              <th>Candidate</th>
              <th className="num">Similarity</th>
              <th className="num">Runner-up</th>
              <th>Result</th>
              <th>Identity</th>
            </tr>
          </thead>
          <tbody>
            {tracks.map((t) => (
              <tr key={t.track_id}>
                <td className="num">#{t.track_id}</td>
                <td>{t.face_detected ? <Pill tone="ok">yes</Pill> : <Pill>no</Pill>}</td>
                <td className="small">
                  {t.quality ? `${num(t.quality.score, 2)}${t.quality.reasons?.length ? ` (${t.quality.reasons.join(", ")})` : ""}` : "–"}
                </td>
                <td className="small">{t.observations} seen · {t.usable} usable · {t.kept} kept</td>
                <td className="num">{t.best_frame ?? "–"}</td>
                <td>{t.candidate ?? "–"}</td>
                <td className="num">{t.similarity != null ? num(t.similarity, 3) : "–"}</td>
                <td className="num">{t.second_similarity != null && t.second_similarity > -1 ? num(t.second_similarity, 3) : "–"}</td>
                <td>{resultPill(t.result)}</td>
                <td>{t.identity ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function PlateDiagnostics({ tracks, model, stats, vehicles }: { tracks: PlateTrackDiagnostics[]; model: Record<string, unknown>; stats: Record<string, number>; vehicles: number }) {
  const m = model as { detector?: { model_version?: string }; ocr?: { model_version?: string } };
  return (
    <div>
      <div className="row wrap small muted" style={{ marginBottom: 6 }}>
        <span>Model: {m.detector?.model_version} + {m.ocr?.model_version} · {vehicles} registered vehicles</span>
        <span>attempts {stats.attempts} · plates {stats.plates_detected} · usable reads {stats.usable} · plates read {stats.plates_read} · registered {stats.registered} · unknown {stats.unknown}</span>
      </div>
      {tracks.length === 0 ? (
        <div className="hint">No vehicle track observed yet.</div>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th className="num">Vehicle track</th>
              <th>Plate detected</th>
              <th>Raw OCR (last)</th>
              <th>Temporal consensus</th>
              <th>Normalized</th>
              <th className="num">Confidence</th>
              <th>Reads</th>
              <th>Vehicle</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            {tracks.map((t) => (
              <tr key={t.track_id}>
                <td className="num">#{t.track_id}</td>
                <td>{t.plate_detected ? <Pill tone="ok">yes</Pill> : <Pill>no</Pill>}</td>
                <td className="mono">{t.raw_ocr ?? "–"}</td>
                <td className="mono">{t.consensus ? `${t.consensus.text} (${t.consensus.n_observations} reads${t.consensus.complete ? "" : ", incomplete"})` : "–"}</td>
                <td className="mono">{t.normalized ?? "–"}{t.format ? <span className="hint"> {t.format}</span> : null}</td>
                <td className="num">{t.confidence != null ? num(t.confidence, 2) : "–"}</td>
                <td className="small">{t.reads} · {t.usable} usable</td>
                <td>{t.vehicle ?? "–"}</td>
                <td>{resultPill(t.result)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function DiagnosticsPanel() {
  const runs = useQuery({ queryKey: ["recognition-active-runs"], queryFn: api.recognition.activeRuns, refetchInterval: 3000 });
  const [runId, setRunId] = useState<number | null>(null);
  const chosen = runId ?? runs.data?.[0]?.run_id ?? null;
  const diag = useQuery({ queryKey: ["recognition-diagnostics", chosen], queryFn: () => api.recognition.diagnostics(chosen!), enabled: chosen !== null, refetchInterval: 2000, retry: 0 });
  return (
    <Panel
      title="Diagnostics of active runs"
      actions={
        runs.data && runs.data.length > 1 ? (
          <select value={chosen ?? ""} onChange={(e) => setRunId(Number(e.target.value))} style={{ width: "auto" }}>
            {runs.data.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                Run #{r.run_id} (camera {r.camera_id})
              </option>
            ))}
          </select>
        ) : undefined
      }
    >
      {runs.data && runs.data.length === 0 && <div className="hint">No run is active. Start an experiment whose camera sees people or vehicles; recognition diagnostics appear here while it runs, so researchers can see why a recognition succeeded or failed.</div>}
      {diag.data && diag.data.modules.length === 0 && <Notice>This run has no active recognition module (not licensed, disabled, or no tracked class needs it).</Notice>}
      {diag.data?.recognition && diag.data.recognition.length > 0 && (
        <Notice tone="warn">
          {diag.data.recognition.map((w) => (
            <div key={w}>{w}</div>
          ))}
        </Notice>
      )}
      {diag.data?.diagnostics?.face && (
        <>
          <div className="section-title">Faces</div>
          <FaceDiagnostics tracks={diag.data.diagnostics.face.tracks} model={diag.data.diagnostics.face.model} stats={diag.data.diagnostics.face.stats} />
        </>
      )}
      {diag.data?.diagnostics?.plate && (
        <>
          <div className="section-title">Plates</div>
          <PlateDiagnostics tracks={diag.data.diagnostics.plate.tracks} model={diag.data.diagnostics.plate.model} stats={diag.data.diagnostics.plate.stats} vehicles={diag.data.diagnostics.plate.vehicles} />
        </>
      )}
      {diag.data && diag.data.modules.length > 0 && !diag.data.diagnostics && <div className="hint">Waiting for the first diagnostics message…</div>}
    </Panel>
  );
}

export default function RecognitionEventsPage() {
  const qc = useQueryClient();
  const me = usePrincipal();
  const isAdmin = roleAtLeast(me.data?.role, "admin");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [page, setPage] = useState(1);
  const [detail, setDetail] = useState<RecognitionEvent | null>(null);
  const params = { ...filters, page, page_size: 50 };
  const q = useQuery({ queryKey: ["recognition-events", params], queryFn: () => api.recognition.events(params), enabled: !!me.data, refetchInterval: 5000 });
  const people = useQuery({ queryKey: ["recognition-people"], queryFn: api.recognition.people, enabled: !!me.data });
  const vehicles = useQuery({ queryKey: ["recognition-vehicles"], queryFn: api.recognition.vehicles, enabled: !!me.data });
  const remove = useMutation({
    mutationFn: (id: number) => api.recognition.deleteEvent(id),
    onSuccess: () => {
      setDetail(null);
      qc.invalidateQueries({ queryKey: ["recognition-events"] });
    },
  });
  const set = (k: string, v: string) => {
    setFilters({ ...filters, [k]: v });
    setPage(1);
  };
  const total = q.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / 50));
  return (
    <RecognitionGate title="Recognition events" sub="Every recognition decision with its similarity or confidence, image quality, observations, model version, camera, track and frame. Kept apart from ordinary events and visible only with a recognition token.">
      <DiagnosticsPanel />
      <Panel title="Filters">
        <div className="form-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
          <Field label="Module">
            <select value={filters.module ?? ""} onChange={(e) => set("module", e.target.value)}>
              <option value="">All</option>
              <option value="face">Face</option>
              <option value="plate">Plate</option>
            </select>
          </Field>
          <Field label="Kind">
            <select value={filters.kind ?? ""} onChange={(e) => set("kind", e.target.value)}>
              <option value="">All</option>
              {Object.entries(EVENT_KIND_LABEL).map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Person">
            <select value={filters.person_id ?? ""} onChange={(e) => set("person_id", e.target.value)}>
              <option value="">Any</option>
              {people.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Vehicle">
            <select value={filters.vehicle_id ?? ""} onChange={(e) => set("vehicle_id", e.target.value)}>
              <option value="">Any</option>
              {vehicles.data?.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.plate} {v.description ? `· ${v.description}` : ""}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Plate">
            <input type="text" value={filters.plate ?? ""} onChange={(e) => set("plate", e.target.value)} placeholder="ABC12345" />
          </Field>
          <Field label="Run">
            <input type="number" value={filters.run_id ?? ""} onChange={(e) => set("run_id", e.target.value)} placeholder="any" />
          </Field>
        </div>
        <div className="row" style={{ marginTop: 10, justifyContent: "space-between" }}>
          <span className="hint">{q.data ? `${num(total, 0)} events` : ""}</span>
          <span className="row">
            <button className="btn sm" onClick={() => { setFilters({}); setPage(1); }}>
              Clear filters
            </button>
            {isAdmin && (
              <>
                <span className="divider" />
                <span className="small muted">Export (audited)</span>
                <a className="btn sm" href={api.recognition.exportUrl({ ...filters, format: "csv" })}>
                  CSV
                </a>
                <a className="btn sm" href={api.recognition.exportUrl({ ...filters, format: "json" })}>
                  JSON
                </a>
              </>
            )}
          </span>
        </div>
      </Panel>
      <Panel title="Events" flush>
        {q.isError && <ErrorNotice error={q.error} />}
        {q.data && q.data.items.length === 0 && <Empty>No recognition events match these filters.</Empty>}
        {q.data && q.data.items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Run</th>
                  <th>Camera</th>
                  <th className="num">Track</th>
                  <th>Module</th>
                  <th>Kind</th>
                  <th>Identity / plate</th>
                  <th className="num">Similarity / confidence</th>
                  <th className="num">Quality</th>
                  <th>Observations</th>
                  <th>Model</th>
                </tr>
              </thead>
              <tbody>
                {q.data.items.map((e) => (
                  <tr key={e.id} className="clickable" onClick={() => setDetail(e)}>
                    <td className="muted">{dateTime(e.wall_time)}</td>
                    <td>{e.run_id != null ? <Link to={`/analysis/runs/${e.run_id}`} onClick={(ev) => ev.stopPropagation()}>#{e.run_id}</Link> : "–"}</td>
                    <td>{e.camera_id != null ? `#${e.camera_id}` : "–"}</td>
                    <td className="num">{e.track_id}</td>
                    <td>{e.module}</td>
                    <td>{EVENT_KIND_LABEL[e.kind] ?? e.kind}</td>
                    <td>{subject(e)}</td>
                    <td className="num">{e.module === "face" ? (e.similarity != null ? num(e.similarity, 3) : "–") : e.confidence != null ? `${num(e.confidence * 100, 0)}%` : "–"}</td>
                    <td className="num">{e.quality != null ? num(e.quality, 2) : "–"}</td>
                    <td className="small muted">{e.usable_observations} of {e.n_observations}{e.best_frame_index != null ? ` · best ${e.best_frame_index}` : ""}</td>
                    <td className="small muted">{e.model_version}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="row" style={{ padding: 8 }}>
          <button className="btn sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Previous
          </button>
          <span className="small muted">
            Page {page} of {pages}
          </span>
          <button className="btn sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>
            Next
          </button>
        </div>
      </Panel>
      {detail && (
        <Modal title={`Recognition event #${detail.id}`} onClose={() => setDetail(null)} width={720}>
          <div className="stack">
            {detail.has_crop && roleAtLeast(me.data?.role, "operator") && (
              <div className="camera-view" style={{ height: 140 }}>
                <img src={api.recognition.eventCropUrl(detail.id)} alt="best crop" style={{ maxHeight: 140 }} />
              </div>
            )}
            <KV
              items={[
                ["Kind", EVENT_KIND_LABEL[detail.kind] ?? detail.kind],
                ["Subject", subject(detail)],
                ["Status", resultPill(detail.status)],
                ["Similarity", detail.similarity != null ? `${num(detail.similarity, 3)} (runner-up ${num(detail.second_similarity, 3)})` : "–"],
                ["Confidence", detail.confidence != null ? num(detail.confidence, 3) : "–"],
                ["Image quality", detail.quality != null ? num(detail.quality, 2) : "–"],
                ["Observations", `${detail.usable_observations} usable of ${detail.n_observations}; best frame ${detail.best_frame_index ?? "–"}`],
                ["Plate", detail.plate_raw ? `${detail.plate_raw} → ${detail.plate_normalized} (${detail.plate_format ?? "?"}${detail.plate_region ? `, ${detail.plate_region}` : ""})` : "–"],
                ["Model", detail.model_version],
                ["Where", `run ${detail.run_id ?? "–"}, camera ${detail.camera_id ?? "–"}, track ${detail.track_id}, frame ${detail.frame_index}, ${clock(detail.media_time_s)}`],
                ["Timestamp", dateTime(detail.wall_time)],
                ["Context", <pre className="mono small" style={{ whiteSpace: "pre-wrap", margin: 0 }}>{JSON.stringify(detail.context, null, 1)}</pre>],
              ]}
            />
            {isAdmin && (
              <div className="row">
                <ConfirmButton label="Delete this recognition event" confirm="Delete?" onConfirm={() => remove.mutate(detail.id)} />
              </div>
            )}
          </div>
        </Modal>
      )}
    </RecognitionGate>
  );
}
