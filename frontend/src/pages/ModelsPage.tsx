import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ModelInfo } from "../api/types";
import { ConfirmButton, ErrorNotice, KV, Modal, Notice, Panel, Pill, Progress } from "../components/ui";
import { bytes, num } from "../lib/format";
import { RecommendationTiers } from "./HardwarePage";

function Dots({ n }: { n: number }) {
  return (
    <span className="mono" title={`${n} of 5`} style={{ letterSpacing: 1 }}>
      {"●".repeat(n)}
      <span style={{ color: "var(--line-strong)" }}>{"●".repeat(5 - n)}</span>
    </span>
  );
}

function suitability(s: string) {
  const tone = s === "good" ? "ok" : s === "fair" ? "warn" : "";
  return <Pill tone={tone as "ok" | "warn" | ""}>{s}</Pill>;
}

const RECOGNITION_TASK: Record<string, string> = {
  face_detection: "Face detector",
  face_embedding: "Face embedding",
  plate_detection: "Plate detector",
  plate_ocr: "Plate OCR",
};

export default function ModelsPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["models"], queryFn: api.models.list, refetchInterval: (query) => (query.state.data?.models.some((m) => m.job && (m.job.status === "running" || m.job.status === "queued")) ? 1500 : false) });
  const benchmarks = useQuery({ queryKey: ["benchmarks"], queryFn: api.models.benchmarks });
  const jobs = useQuery({ queryKey: ["model-jobs"], queryFn: api.models.jobs, refetchInterval: 2000 });
  const [detail, setDetail] = useState<ModelInfo | null>(null);
  const [benchTarget, setBenchTarget] = useState<ModelInfo | null>(null);
  const [benchDevice, setBenchDevice] = useState("auto");
  const [benchTracker, setBenchTracker] = useState("bytetrack");
  const [benchAppearance, setBenchAppearance] = useState("none");
  const [benchSize, setBenchSize] = useState<number | "">("");
  const [error, setError] = useState<unknown>(null);

  const install = useMutation({ mutationFn: (id: string) => api.models.install(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["models"] }), onError: setError });
  const remove = useMutation({ mutationFn: (id: string) => api.models.remove(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["models"] }), onError: setError });
  const bench = useMutation({
    mutationFn: (m: ModelInfo) =>
      api.models.benchmark(m.id, {
        device: benchDevice,
        image_size: benchSize === "" ? null : Number(benchSize),
        tracker_id: benchTracker,
        tracker_settings: benchTracker === "botsort" && benchAppearance !== "none" ? { appearance: benchAppearance } : {},
      }),
    onSuccess: () => {
      setBenchTarget(null);
      qc.invalidateQueries({ queryKey: ["model-jobs"] });
    },
    onError: setError,
  });

  const benchJobs = (jobs.data?.benchmark ?? []) as { id: string; model_id: string; status: string; progress: number; message: string; error: string | null }[];
  const running = benchJobs.filter((j) => j.status === "running" || j.status === "queued");
  useEffect(() => {
    if (running.length === 0) {
      qc.invalidateQueries({ queryKey: ["benchmarks"] });
      qc.invalidateQueries({ queryKey: ["models"] });
      qc.invalidateQueries({ queryKey: ["recommendations"] });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running.length]);

  if (q.isError) return <ErrorNotice error={q.error} />;
  if (!q.data) return <div className="hint">Loading model catalog…</div>;
  const models = q.data.models.filter((m) => m.task === "detection");
  const appearanceModels = q.data.models.filter((m) => m.task === "appearance");
  const recognitionModels = q.data.models.filter((m) => !!m.module);
  const appearanceOptions = q.data.trackers.find((t) => t.id === "botsort")?.settings.find((s) => s.key === "appearance")?.options ?? [];
  const providers = [...new Set(models.map((m) => m.provider))];

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Models</h1>
          <div className="sub">Detectors are downloaded into the models directory on demand. Published accuracy figures are shown for comparison only; run a benchmark for real numbers on this machine.</div>
        </div>
      </div>
      {error ? <ErrorNotice error={error} /> : null}
      <Panel title="Recommended for this system">
        <RecommendationTiers compact />
      </Panel>

      {running.length > 0 && (
        <Notice>
          Benchmark running: {running.map((j) => `${j.model_id} — ${j.message} (${Math.round(j.progress * 100)}%)`).join("; ")}
        </Notice>
      )}

      <Panel title="Detector catalog" flush>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Model</th>
                <th>Family</th>
                <th>Provider</th>
                <th>Runtime</th>
                <th className="num">Params</th>
                <th className="num">Size</th>
                <th className="num">Min VRAM</th>
                <th>CPU</th>
                <th>GPU</th>
                <th>Accuracy</th>
                <th>Speed</th>
                <th className="num">Ref. mAP</th>
                <th>Licence</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {models.map((m) => {
                const job = m.job;
                const busy = job && (job.status === "running" || job.status === "queued");
                return (
                  <tr key={m.id}>
                    <td>
                      <a href="#" onClick={(e) => { e.preventDefault(); setDetail(m); }}>{m.name}</a>
                      {m.recommended_tier && <Pill tone="accent">{m.recommended_tier}</Pill>}
                    </td>
                    <td className="mono">{m.family}</td>
                    <td>{m.provider}{!m.provider_available && <Pill tone="warn">package missing</Pill>}</td>
                    <td className="muted small">{m.runtimes.join(", ")}</td>
                    <td className="num">{m.parameters_m ? `${m.parameters_m}M` : "–"}</td>
                    <td className="num">{m.size_mb ? `${num(m.size_mb, 0)} MB` : "–"}</td>
                    <td className="num">{m.min_vram_gb ? `${m.min_vram_gb} GB` : "–"}</td>
                    <td>{suitability(m.cpu_suitability)}</td>
                    <td>{suitability(m.gpu_suitability)}</td>
                    <td><Dots n={m.relative_accuracy} /></td>
                    <td><Dots n={m.relative_speed} /></td>
                    <td className="num">{m.reference_map ?? "–"}</td>
                    <td><Pill tone={m.license.startsWith("AGPL") ? "warn" : ""}>{m.license}</Pill></td>
                    <td>
                      {busy ? (
                        <div style={{ minWidth: 120 }}>
                          <div className="small">{job!.message}</div>
                          <Progress value={job!.progress} />
                        </div>
                      ) : job && job.status === "failed" ? (
                        <Pill tone="err">failed</Pill>
                      ) : m.installed ? (
                        <Pill tone="ok">installed{m.installed_size_bytes ? ` · ${bytes(m.installed_size_bytes, 0)}` : ""}</Pill>
                      ) : (
                        <Pill>not installed</Pill>
                      )}
                    </td>
                    <td className="row" style={{ gap: 4 }}>
                      {!m.installed && !busy && (
                        <button className="btn sm" disabled={!m.provider_available || (m.export_from ? !m.export_source_installed && !m.provider_available : false)} onClick={() => install.mutate(m.id)}>
                          {m.export_from ? "Export" : "Install"}
                        </button>
                      )}
                      {m.installed && (
                        <>
                          <button className="btn sm" onClick={() => { setBenchTarget(m); setBenchSize(""); }}>Benchmark</button>
                          {m.provider !== "torchvision" && <ConfirmButton label="Remove" confirm="Remove?" onConfirm={() => remove.mutate(m.id)} className="btn sm ghost" />}
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      <div className="grid-2">
        <Panel title="Benchmarks on this machine" flush>
          {!benchmarks.data?.length ? (
            <div className="empty">No benchmark has been run yet. Install a model and choose Benchmark.</div>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Tracker</th>
                    <th>Device</th>
                    <th className="num">Size</th>
                    <th className="num">Detector ms</th>
                    <th className="num">Tracker ms</th>
                    <th className="num">Pre ms</th>
                    <th className="num">Pipeline FPS</th>
                    <th className="num">CPU %</th>
                    <th className="num">RSS</th>
                    <th className="num">VRAM peak</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {(benchmarks.data as { id: number; model_id: string; device: string; results: Record<string, any>; created_at: string }[]).map((b) => (
                    <tr key={b.id}>
                      <td>{b.results.model_name ?? b.model_id}</td>
                      <td className="small">
                        {b.results.tracker?.name ?? "ByteTrack"}
                        {b.results.tracker?.appearance ? ` + ${b.results.tracker.appearance.label}` : ""}
                      </td>
                      <td className="mono">{b.device}</td>
                      <td className="num">{b.results.inference_resolution}px</td>
                      <td className="num">{num(b.results.detector_ms?.median)}</td>
                      <td className="num">{num(b.results.tracker_ms?.median)}</td>
                      <td className="num">{num(b.results.preprocess_ms?.median)}</td>
                      <td className="num"><strong>{num(b.results.pipeline_fps, 1)}</strong></td>
                      <td className="num">{num(b.results.cpu_percent_mean, 0)}</td>
                      <td className="num">{num(b.results.process_rss_mb, 0)} MB</td>
                      <td className="num">{b.results.vram_used_mb_peak != null ? `${num(b.results.vram_used_mb_peak, 0)} MB` : "–"}</td>
                      <td className="muted small">{String(b.results.source ?? "").split(/[\\/]/).pop()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        <Panel title="Trackers">
          <table className="table">
            <thead>
              <tr>
                <th>Tracker</th>
                <th>Status</th>
                <th>Licence</th>
                <th className="wrap">Description</th>
              </tr>
            </thead>
            <tbody>
              {q.data.trackers.map((t) => (
                <tr key={t.id}>
                  <td>{t.name}</td>
                  <td>{t.available ? <Pill tone="ok">available</Pill> : <Pill tone="warn" >{t.unavailable_reason ?? "unavailable"}</Pill>}</td>
                  <td className="small">{t.license}</td>
                  <td className="wrap muted">{t.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="section-title" style={{ marginTop: 10 }}>Appearance models for BoT-SORT</div>
          <table className="table">
            <tbody>
              {appearanceModels.map((m) => {
                const job = m.job;
                const busy = job && (job.status === "running" || job.status === "queued");
                return (
                  <tr key={m.id}>
                    <td>
                      <a href="#" onClick={(e) => { e.preventDefault(); setDetail(m); }}>{m.name}</a>
                    </td>
                    <td className="num">{m.size_mb ? `${num(m.size_mb, 0)} MB` : "–"}</td>
                    <td className="small">{m.license}</td>
                    <td>
                      {busy ? (
                        <div style={{ minWidth: 120 }}>
                          <div className="small">{job!.message}</div>
                          <Progress value={job!.progress} />
                        </div>
                      ) : m.installed ? (
                        <Pill tone="ok">installed</Pill>
                      ) : (
                        <button className="btn sm" disabled={!m.provider_available} onClick={() => install.mutate(m.id)}>
                          Install
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
              <tr>
                <td>Colour histogram</td>
                <td className="num">–</td>
                <td className="small">built in</td>
                <td>
                  <Pill tone="ok">no download</Pill>
                </td>
              </tr>
            </tbody>
          </table>
          <div className="hint" style={{ marginTop: 6 }}>
            A custom re-identification model can be added as an ONNX file in the models/reid folder; it then appears as a BoT-SORT appearance option. CV-Scope does not ship person re-identification weights because the public ones are trained on research-only datasets.
          </div>
          <div className="hint" style={{ marginTop: 8 }}>Providers installed: {providers.join(", ")}.</div>
        </Panel>
      </div>

      <Panel title="Recognition models (licensed face and plate modules)" flush>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Model</th>
                <th>Task</th>
                <th>Module</th>
                <th>Backend</th>
                <th className="num">VRAM</th>
                <th className="num">RAM</th>
                <th>CPU</th>
                <th>GPU</th>
                <th className="num">Size</th>
                <th>Licence</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {recognitionModels.map((m) => {
                const job = m.job;
                const busy = job && (job.status === "running" || job.status === "queued");
                return (
                  <tr key={m.id}>
                    <td>
                      <a href="#" onClick={(e) => { e.preventDefault(); setDetail(m); }}>{m.name}</a>
                    </td>
                    <td className="small">{RECOGNITION_TASK[m.task] ?? m.task}</td>
                    <td>{m.module}</td>
                    <td className="muted small">{m.runtimes.join(", ")}</td>
                    <td className="num">{m.min_vram_gb ? `${m.min_vram_gb} GB` : "–"}</td>
                    <td className="num">{m.min_ram_gb} GB</td>
                    <td>{suitability(m.cpu_suitability)}</td>
                    <td>{suitability(m.gpu_suitability)}</td>
                    <td className="num">{m.size_mb ? `${num(m.size_mb, 1)} MB` : "–"}{m.archive_member ? <span className="hint"> (275 MB pack)</span> : null}</td>
                    <td><Pill tone={m.license.startsWith("Non-commercial") ? "warn" : ""}>{m.license}</Pill></td>
                    <td>
                      {busy ? (
                        <div style={{ minWidth: 120 }}>
                          <div className="small">{job!.message}</div>
                          <Progress value={job!.progress} />
                        </div>
                      ) : job && job.status === "failed" ? (
                        <Pill tone="err" >failed</Pill>
                      ) : m.installed ? (
                        <Pill tone="ok">installed</Pill>
                      ) : (
                        <Pill>not installed</Pill>
                      )}
                    </td>
                    <td className="row" style={{ gap: 4 }}>
                      {!m.installed && !busy && (
                        <button className="btn sm" disabled={!m.provider_available} onClick={() => install.mutate(m.id)}>
                          Install
                        </button>
                      )}
                      {m.installed && <ConfirmButton label="Remove" confirm="Remove?" onConfirm={() => remove.mutate(m.id)} className="btn sm ghost" />}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="hint" style={{ padding: 8 }}>
          Weights are downloaded and cached locally; camera footage never leaves this machine. The OpenCV Zoo and fast-plate-ocr / open-image-models files are MIT or Apache-2.0. The InsightFace pack (SCRFD, ArcFace) is for non-commercial research use only; only its detector and embedding files are extracted, never its gender/age model. Timings on this machine: Recognition → Settings → Benchmark. Capacity effect: Hardware page.
        </div>
      </Panel>

      {detail && (
        <Modal title={detail.name} onClose={() => setDetail(null)} width={640}>
          <KV
            items={[
              ["Family", detail.family],
              ["Task", detail.task],
              ["Provider", `${detail.provider} (${detail.requires_package})`],
              ["Supported runtimes", detail.runtimes.join(", ")],
              ["Object classes", `${detail.classes.length} classes; trackable in CV-Scope: ${detail.trackable_classes.join(", ")}`],
              ["Parameters", detail.parameters_m ? `${detail.parameters_m} M` : "–"],
              ["Download size", detail.size_mb ? `${detail.size_mb} MB` : "–"],
              ["Approx. memory", `${detail.min_vram_gb ?? "–"} GB VRAM on GPU · ${detail.min_ram_gb} GB RAM`],
              ["Compute class", detail.compute_class],
              ["CPU / GPU suitability", `${detail.cpu_suitability} / ${detail.gpu_suitability}`],
              ["Relative accuracy / speed", <span><Dots n={detail.relative_accuracy} /> / <Dots n={detail.relative_speed} /></span>],
              ["Reference accuracy", detail.reference_map ? `${detail.reference_map} mAP50-95 — ${detail.reference_note}` : "not published"],
              ["Default inference size", `${detail.default_image_size}px`],
              ["Licence", <span>{detail.license}. {detail.license_note}</span>],
              ["Source", <a href={detail.source_url} target="_blank" rel="noreferrer">{detail.source_url}</a>],
              ["Installed", detail.installed ? `yes${detail.path ? ` — ${detail.path}` : ""}` : "no"],
              ["Notes", detail.notes || "–"],
            ]}
          />
        </Modal>
      )}

      {benchTarget && (
        <Modal
          title={`Benchmark ${benchTarget.name}`}
          onClose={() => setBenchTarget(null)}
          footer={
            <>
              <button className="btn" onClick={() => setBenchTarget(null)}>Cancel</button>
              <button className="btn primary" onClick={() => bench.mutate(benchTarget)} disabled={bench.isPending}>Run benchmark</button>
            </>
          }
        >
          <p className="small muted">Runs about 120 frames of the most recently uploaded video (or synthetic frames if none) through the detector and tracker, and records timing, CPU, memory and VRAM.</p>
          <div className="form-grid">
            <div className="field">
              <label>Device</label>
              <select value={benchDevice} onChange={(e) => setBenchDevice(e.target.value)}>
                <option value="auto">Auto</option>
                <option value="cuda">CUDA GPU</option>
                <option value="mps">Apple MPS</option>
                <option value="cpu">CPU</option>
              </select>
            </div>
            <div className="field">
              <label>Inference size (px)</label>
              <input type="number" placeholder={String(benchTarget.default_image_size)} value={benchSize} onChange={(e) => setBenchSize(e.target.value === "" ? "" : Number(e.target.value))} />
            </div>
            <div className="field">
              <label>Tracker</label>
              <select value={benchTracker} onChange={(e) => setBenchTracker(e.target.value)}>
                {q.data.trackers.filter((t) => t.available).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </div>
            {benchTracker === "botsort" && (
              <div className="field">
                <label>Appearance</label>
                <select value={benchAppearance} onChange={(e) => setBenchAppearance(e.target.value)}>
                  {appearanceOptions.map((o) => (
                    <option key={o.value} value={o.value} disabled={o.available === false}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>
        </Modal>
      )}
    </div>
  );
}
