import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api } from "../api/client";
import type { Camera, Experiment, ExperimentInput, InferenceSettings, Rule, Scene } from "../api/types";
import { CameraView } from "../components/CameraView";
import { ClassPicker, ConfirmButton, ErrorNotice, Field, KV, Notice, Panel, Pill } from "../components/ui";
import { CLASS_OPTIONS, dateTime, RUN_STATE_CLASS, seconds, SOURCE_LABEL } from "../lib/format";
import { AnomalyPanel, DEFAULT_ANOMALY } from "../components/AnomalySettings";
import { DEFAULT_RECORDING, RecordingPanel } from "../components/RecordingSettings";
import { DEFAULT_RELATIONS, RelationsPanel } from "../relationships/RelationsPanel";
import { TrackerSettingsFields } from "../components/TrackerSettings";
import { useRecognitionAuth } from "../lib/recognitionToken";
import RuleBuilder from "../rule-builder/RuleBuilder";

const DEFAULT_INFERENCE: InferenceSettings = { preset: "auto", provider: "auto", device: "auto", image_size: null, confidence: 0.25, iou: 0.5, half: null, processing_fps: null, frame_skip: 0, realtime: false };

export default function ExperimentPage() {
  const { experimentId } = useParams();
  const id = Number(experimentId);
  const qc = useQueryClient();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["experiment", id], queryFn: () => api.experiments.get(id), refetchInterval: 4000 });
  const runs = useQuery({ queryKey: ["runs", id], queryFn: () => api.experiments.runs(id), refetchInterval: 4000 });
  const models = useQuery({ queryKey: ["models"], queryFn: api.models.list });
  // Every camera is offered, grouped by project: a camera added under another
  // project can be used here and moved with one click.
  const cameras = useQuery({ queryKey: ["cameras", "all"], queryFn: () => api.cameras.list() });
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects.list });
  const [form, setForm] = useState<ExperimentInput | null>(null);
  const chosenCameraId = form ? form.camera_id : q.data?.camera_id;
  const scenes = useQuery({ queryKey: ["scenes", chosenCameraId], queryFn: () => api.cameras.scenes(chosenCameraId!), enabled: !!chosenCameraId });
  const [advanced, setAdvanced] = useState(false);
  // scene objects a rule refers to (hovered in the rule builder), highlighted on the camera view
  const [ruleFocus, setRuleFocus] = useState<string[]>([]);
  // Licensed recognition modules: the rule builder offers identities and vehicles when a token is present
  const rtoken = useRecognitionAuth((s) => s.token);
  const recStatus = useQuery({ queryKey: ["recognition-status"], queryFn: api.recognition.status, retry: 0, staleTime: 30_000 });
  const recPeople = useQuery({ queryKey: ["recognition-people"], queryFn: api.recognition.people, enabled: !!rtoken, retry: 0 });
  const recVehicles = useQuery({ queryKey: ["recognition-vehicles"], queryFn: api.recognition.vehicles, enabled: !!rtoken, retry: 0 });
  const recGroups = useQuery({ queryKey: ["recognition-vehicle-groups"], queryFn: api.recognition.vehicleGroups, enabled: !!rtoken, retry: 0 });
  useEffect(() => {
    setForm(null); // another experiment, for example the copy made by Duplicate
  }, [id]);
  useEffect(() => {
    if (q.data && q.data.id === id && !form) setForm(toForm(q.data));
  }, [q.data, form, id]);
  const save = useMutation({
    mutationFn: () => api.experiments.update(id, form!),
    onSuccess: (e) => {
      setForm(toForm(e));
      qc.invalidateQueries({ queryKey: ["experiment", id] });
      qc.invalidateQueries({ queryKey: ["experiments"] });
    },
  });
  const start = useMutation({
    mutationFn: () => api.experiments.start(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["runs", id] });
      qc.invalidateQueries({ queryKey: ["experiment", id] });
    },
  });
  const stop = useMutation({ mutationFn: (runId: number) => api.runs.stop(runId), onSuccess: () => qc.invalidateQueries({ queryKey: ["runs", id] }) });
  const duplicate = useMutation({ mutationFn: () => api.experiments.duplicate(id), onSuccess: (e) => nav(`/experiments/${e.id}`) });
  const remove = useMutation({ mutationFn: () => api.experiments.remove(id), onSuccess: () => nav("/experiments") });
  const removeRun = useMutation({ mutationFn: (runId: number) => api.runs.remove(runId), onSuccess: () => qc.invalidateQueries({ queryKey: ["runs", id] }) });
  const moveCamera = useMutation({
    mutationFn: (cameraId: number) => api.cameras.update(cameraId, { project_id: q.data!.project_id }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cameras"] });
      qc.invalidateQueries({ queryKey: ["camera"] });
    },
  });

  if (q.isError) return <ErrorNotice error={q.error} />;
  if (!q.data || !form) return <div className="hint">Loading experiment…</div>;
  const e = q.data;
  const activeRun = runs.data?.find((r) => r.live && !["completed", "stopped", "failed"].includes(r.status));
  const dirty = JSON.stringify(form) !== JSON.stringify(toForm(e));
  const inf = { ...DEFAULT_INFERENCE, ...(form.inference ?? {}) };
  const setInf = (patch: Partial<InferenceSettings>) => setForm({ ...form, inference: { ...inf, ...patch } });
  const installed = models.data?.models.filter((m) => m.task === "detection" && m.installed && m.provider_available) ?? [];
  const tracker = models.data?.trackers.find((t) => t.id === (form.tracker_id || "bytetrack"));
  const allCameras: Camera[] = cameras.data ?? [];
  const ownCameras = allCameras.filter((c) => c.project_id === e.project_id);
  const otherCameras = allCameras.filter((c) => c.project_id !== e.project_id);
  const projectName = (pid: number) => projects.data?.find((p) => p.id === pid)?.name ?? `project ${pid}`;
  const selectedCamera = allCameras.find((c) => c.id === form.camera_id);
  const latestScene: Scene | undefined = scenes.data?.[0];
  const chosenScene = scenes.data?.find((s) => s.id === form.scene_config_id) ?? latestScene;
  const sceneObjects = chosenScene?.document.objects ?? [];

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>{e.name}</h1>
          <div className="sub">
            <Link to={`/projects/${e.project_id}`}>Project</Link> · created {dateTime(e.created_at)} · {e.run_count} run{e.run_count === 1 ? "" : "s"}
          </div>
        </div>
        <div className="row">
          {activeRun ? (
            <button className="btn danger" onClick={() => stop.mutate(activeRun.id)}>
              Stop run #{activeRun.id}
            </button>
          ) : (
            <button className="btn ok" disabled={!e.camera_id || dirty || start.isPending} title={dirty ? "Save changes first" : undefined} onClick={() => start.mutate()}>
              Start
            </button>
          )}
          {e.camera_id && (
            <Link className="btn" to={`/scene/${e.camera_id}?experiment=${e.id}`}>
              Scene builder
            </Link>
          )}
          <button className="btn" onClick={() => duplicate.mutate()}>
            Duplicate
          </button>
          <button className="btn primary" disabled={!dirty || save.isPending || !!activeRun} onClick={() => save.mutate()}>
            Save
          </button>
        </div>
      </div>
      {start.isError && <ErrorNotice error={start.error} />}
      {save.isError && <ErrorNotice error={save.error} />}
      {activeRun && <Notice>A run is active. Configuration changes are locked until it stops, so results stay comparable.</Notice>}

      <div className="grid-2" style={{ gridTemplateColumns: "minmax(0, 1.1fr) minmax(0, 1fr)" }}>
        <div className="stack">
          <Panel title="Experiment">
            <div className="form-grid">
              <Field label="Name" className="span-2">
                <input type="text" value={form.name} onChange={(ev) => setForm({ ...form, name: ev.target.value })} />
              </Field>
              <Field label="Description" className="span-2">
                <textarea value={form.description ?? ""} onChange={(ev) => setForm({ ...form, description: ev.target.value })} />
              </Field>
              <Field label="Research notes" className="span-2" help="Hypothesis, protocol, anything a colleague needs to reproduce the study.">
                <textarea value={form.notes ?? ""} onChange={(ev) => setForm({ ...form, notes: ev.target.value })} />
              </Field>
              <Field label="Environmental condition notes" className="span-2" help="Signage, lighting, weather, time of day. Stored with the experiment and shown when experiments are compared.">
                <textarea value={form.condition_notes ?? ""} onChange={(ev) => setForm({ ...form, condition_notes: ev.target.value })} />
              </Field>
              <Field label="Tags (comma separated)" className="span-2">
                <input type="text" value={(form.tags ?? []).join(", ")} onChange={(ev) => setForm({ ...form, tags: ev.target.value.split(",").map((t) => t.trim()).filter(Boolean) })} />
              </Field>
            </div>
          </Panel>
          <Panel title="Camera and scene">
            <div className="form-grid">
              <Field label="Camera">
                <select value={form.camera_id ?? ""} onChange={(ev) => setForm({ ...form, camera_id: ev.target.value ? Number(ev.target.value) : null, scene_config_id: null })}>
                  <option value="">Select…</option>
                  {ownCameras.length > 0 && (
                    <optgroup label="In this project">
                      {ownCameras.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name} ({SOURCE_LABEL[c.source_type] ?? c.source_type})
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {otherCameras.length > 0 && (
                    <optgroup label="Other projects">
                      {otherCameras.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}, in {projectName(c.project_id)}
                        </option>
                      ))}
                    </optgroup>
                  )}
                </select>
              </Field>
              <Field label="Scene version" help="Latest follows your scene edits. Each run records the version it used. Pick a version to keep every run on the same scene.">
                <select value={form.scene_config_id ?? ""} onChange={(ev) => setForm({ ...form, scene_config_id: ev.target.value ? Number(ev.target.value) : null })}>
                  <option value="">Latest{latestScene ? ` (v${latestScene.version})` : ""}</option>
                  {scenes.data?.map((s) => (
                    <option key={s.id} value={s.id}>
                      v{s.version} — {s.name} {s.frozen ? "(used by a run)" : ""}
                    </option>
                  ))}
                </select>
              </Field>
              {cameras.isSuccess && allCameras.length === 0 && (
                <div style={{ gridColumn: "1 / -1" }}>
                  <Notice>
                    There are no cameras yet. <Link to="/cameras">Add a camera</Link> (a USB webcam, a network stream or a video file), then choose it here.
                  </Notice>
                </div>
              )}
              {selectedCamera && selectedCamera.project_id !== e.project_id && (
                <div style={{ gridColumn: "1 / -1" }}>
                  <Notice>
                    {selectedCamera.name} belongs to the project “{projectName(selectedCamera.project_id)}”. It works in this experiment as it is. Move it to list it with this project’s cameras.
                    <div className="row" style={{ marginTop: 6 }}>
                      <button className="btn sm" disabled={moveCamera.isPending} onClick={() => moveCamera.mutate(selectedCamera.id)}>
                        Move camera to this project
                      </button>
                    </div>
                  </Notice>
                </div>
              )}
              {moveCamera.isError && (
                <div style={{ gridColumn: "1 / -1" }}>
                  <ErrorNotice error={moveCamera.error} />
                </div>
              )}
              <Field label="Objects to track" className="span-2">
                <ClassPicker value={form.object_classes ?? []} onChange={(v) => setForm({ ...form, object_classes: v })} options={CLASS_OPTIONS} />
              </Field>
            </div>
            {selectedCamera && (
              <div style={{ marginTop: 10 }}>
                <CameraView
                  camera={selectedCamera}
                  scene={chosenScene && chosenScene.camera_id === selectedCamera.id ? chosenScene.document : null}
                  sceneLabel={chosenScene ? `scene v${chosenScene.version}${form.scene_config_id ? "" : ", latest"}` : undefined}
                  highlight={ruleFocus}
                />
              </div>
            )}
          </Panel>
          <Panel title="Detection and tracking">
            <div className="form-grid">
              <Field label="Detector">
                <select value={form.model_id ?? ""} onChange={(ev) => setForm({ ...form, model_id: ev.target.value })}>
                  <option value="">Recommended for this system (AUTO)</option>
                  {installed.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name} — {m.provider}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Preset">
                <select value={inf.preset} onChange={(ev) => setInf({ preset: ev.target.value as InferenceSettings["preset"] })}>
                  <option value="auto">AUTO — recommended settings for this hardware</option>
                  <option value="fast">FAST — smaller model, more streams</option>
                  <option value="balanced">BALANCED</option>
                  <option value="accurate">ACCURATE — larger model, lower FPS</option>
                  <option value="custom">CUSTOM — set everything below</option>
                </select>
              </Field>
              <Field label="Tracker">
                <select value={form.tracker_id ?? "bytetrack"} onChange={(ev) => setForm({ ...form, tracker_id: ev.target.value, tracker_settings: {} })}>
                  {models.data?.trackers.map((t) => (
                    <option key={t.id} value={t.id} disabled={!t.available}>
                      {t.name}
                      {t.available ? "" : " (not available)"}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Playback" help="Recorded video is processed as fast as possible unless real-time pacing is on.">
                <label className="check">
                  <input type="checkbox" checked={inf.realtime} onChange={(ev) => setInf({ realtime: ev.target.checked })} />
                  Pace at the source frame rate
                </label>
              </Field>
              {tracker && (
                <div className="hint" style={{ gridColumn: "1 / -1" }}>
                  {tracker.name}: {tracker.description}
                </div>
              )}
            </div>
            <label className="check" style={{ marginTop: 8 }}>
              <input type="checkbox" checked={advanced || inf.preset === "custom"} onChange={(ev) => setAdvanced(ev.target.checked)} />
              Advanced settings
            </label>
            {(advanced || inf.preset === "custom") && (
              <div className="form-grid" style={{ marginTop: 8 }}>
                <Field label="Device">
                  <select value={inf.device} onChange={(ev) => setInf({ device: ev.target.value })}>
                    <option value="auto">Auto</option>
                    <option value="cuda">CUDA GPU</option>
                    <option value="mps">Apple MPS</option>
                    <option value="cpu">CPU</option>
                  </select>
                </Field>
                <Field label="Inference resolution (px)">
                  <input type="number" value={inf.image_size ?? ""} placeholder="model default" onChange={(ev) => setInf({ image_size: ev.target.value ? Number(ev.target.value) : null })} />
                </Field>
                <Field label="Confidence threshold">
                  <input type="number" step="0.05" min="0.01" max="0.99" value={inf.confidence} onChange={(ev) => setInf({ confidence: Number(ev.target.value) })} />
                </Field>
                <Field label="Box overlap threshold (IoU)">
                  <input type="number" step="0.05" min="0.05" max="0.95" value={inf.iou} onChange={(ev) => setInf({ iou: Number(ev.target.value) })} />
                </Field>
                <Field label="Processing FPS" help="Empty = camera setting / every frame">
                  <input type="number" step="0.5" value={inf.processing_fps ?? ""} onChange={(ev) => setInf({ processing_fps: ev.target.value ? Number(ev.target.value) : null })} />
                </Field>
                <Field label="Frame skipping" help="Skip N frames after each processed frame">
                  <input type="number" min="0" value={inf.frame_skip} onChange={(ev) => setInf({ frame_skip: Number(ev.target.value) })} />
                </Field>
                {tracker && (
                  <>
                    <div className="section-title" style={{ gridColumn: "1 / -1" }}>
                      {tracker.name} settings
                    </div>
                    <TrackerSettingsFields tracker={tracker} values={(form.tracker_settings ?? {}) as Record<string, unknown>} onChange={(v) => setForm({ ...form, tracker_settings: v })} />
                  </>
                )}
              </div>
            )}
          </Panel>
          <RecordingPanel value={form.recording ?? DEFAULT_RECORDING} onChange={(recording) => setForm({ ...form, recording })} sourceType={selectedCamera?.source_type} />
          <AnomalyPanel value={form.anomaly ?? DEFAULT_ANOMALY} onChange={(anomaly) => setForm({ ...form, anomaly })} sceneObjects={sceneObjects} classes={form.object_classes ?? []} />
          <RelationsPanel
            value={form.relations ?? DEFAULT_RELATIONS}
            onChange={(relations) => setForm({ ...form, relations })}
            sceneObjects={sceneObjects}
            recognition={{ status: recStatus.data, people: recPeople.data ?? [], vehicles: recVehicles.data ?? [], groups: recGroups.data ?? [], hasToken: !!rtoken }}
          />
        </div>
        <div className="stack">
          <Panel title="Rules" actions={<span className="hint">Lines, zones and routes drawn in the scene already count and record on their own. Add rules for sequences, dwell thresholds and custom labels.</span>}>
            {!form.camera_id ? (
              <Notice>Choose a camera to build rules on its scene objects.</Notice>
            ) : (
              <RuleBuilder
                rules={(form.rules ?? []) as Rule[]}
                objects={sceneObjects}
                classes={form.object_classes ?? []}
                onChange={(rules) => setForm({ ...form, rules })}
                recognition={{ status: recStatus.data, people: recPeople.data ?? [], vehicles: recVehicles.data ?? [], groups: recGroups.data ?? [], hasToken: !!rtoken }}
                relationsEnabled={!!form.relations?.enabled}
                onHighlight={setRuleFocus}
              />
            )}
          </Panel>
          <Panel title="Runs" flush>
            {runs.data && runs.data.length === 0 && <div className="empty">No runs yet. Click Start to begin.</div>}
            {runs.data && runs.data.length > 0 && (
              <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Status</th>
                    <th>Started</th>
                    <th>Duration</th>
                    <th className="num">Events</th>
                    <th>Scene</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {runs.data.map((r) => {
                    const live = r.live && !["completed", "stopped", "failed"].includes(r.status);
                    const dur = r.started_at && r.ended_at ? (new Date(r.ended_at).getTime() - new Date(r.started_at).getTime()) / 1000 : null;
                    return (
                      <tr key={r.id}>
                        <td>
                          <Link to={`/analysis/runs/${r.id}`}>#{r.id}</Link>
                        </td>
                        <td>
                          <Pill tone={(RUN_STATE_CLASS[r.status] ?? "") as "" | "ok" | "warn" | "err" | "accent"} dot={!!live}>
                            {r.status}
                          </Pill>
                          {r.error && <div className="hint" style={{ color: "var(--err)", maxWidth: 260, whiteSpace: "normal" }}>{r.error}</div>}
                        </td>
                        <td className="muted">{dateTime(r.started_at)}</td>
                        <td className="muted">{live ? `${Math.round(((r.live?.progress ?? 0) * 100))}%` : seconds(dur)}</td>
                        <td className="num">{(r.stats?.written_events as number | undefined) ?? (live ? "…" : 0)}</td>
                        <td className="muted">v{String(r.snapshot?.scene_version ?? "?")}</td>
                        <td className="row" style={{ gap: 4 }}>
                          {live ? (
                            <button className="btn sm danger" onClick={() => stop.mutate(r.id)}>
                              Stop
                            </button>
                          ) : (
                            <>
                              <Link className="btn sm" to={`/analysis/runs/${r.id}`}>
                                Results
                              </Link>
                              <Link className="btn sm" to={`/review/${r.id}`} title={videoFiles(r) ? "Watch the video recorded during this run" : "Events and stored paths of this run"}>
                                {videoFiles(r) ? `Video (${videoFiles(r)})` : "Review"}
                              </Link>
                              <a className="btn sm" href={api.events.exportUrl({ run_id: r.id, format: "csv" })}>
                                CSV
                              </a>
                              <ConfirmButton label="Delete" confirm="Delete run?" onConfirm={() => removeRun.mutate(r.id)} className="btn sm ghost" />
                            </>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              </div>
            )}
          </Panel>
          <Panel title="Resolved configuration">
            <KV
              items={[
                ["Detector", e.model_id || "AUTO (hardware recommendation)"],
                ["Preset", e.inference?.preset ?? "auto"],
                ["Tracker", e.tracker_id],
                ["Objects", e.object_classes.join(", ") || "all"],
                ["Rules", `${e.rules.length}${e.rules.some((r) => r.subject && r.subject.mode !== "any") ? " (with recognition conditions)" : ""}`],
                ["Anomaly Assistant", e.anomaly?.enabled ? <Link to={`/anomalies?experiment=${e.id}`}>{watchedAreas(e)} · see anomalies</Link> : "off"],
                ["Last run", e.last_run ? `#${e.last_run.id} — ${String(e.last_run.snapshot?.resolution ?? e.last_run.status)}` : "–"],
                ...(e.last_run?.snapshot?.recognition
                  ? ([[
                      "Recognition (last run)",
                      (() => {
                        const r = e.last_run!.snapshot!.recognition as { modules: string[]; warnings?: string[] };
                        return `${r.modules.length ? r.modules.join(", ") : "none"}${r.warnings?.length ? ` — ${r.warnings.join(" ")}` : ""}`;
                      })(),
                    ]] as [string, string][])
                  : []),
              ]}
            />
            <div className="row" style={{ marginTop: 10 }}>
              <ConfirmButton label="Delete experiment" confirm="Delete experiment and all its runs?" onConfirm={() => remove.mutate()} className="btn sm danger" />
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}

function toForm(e: Experiment): ExperimentInput {
  return {
    project_id: e.project_id,
    camera_id: e.camera_id,
    scene_config_id: e.scene_config_id,
    name: e.name,
    description: e.description,
    notes: e.notes,
    condition_notes: e.condition_notes,
    tags: e.tags,
    object_classes: e.object_classes,
    model_id: e.model_id,
    tracker_id: e.tracker_id,
    inference: { ...DEFAULT_INFERENCE, ...(e.inference ?? {}) },
    tracker_settings: e.tracker_settings ?? {},
    rules: e.rules ?? [],
    recording: { ...DEFAULT_RECORDING, ...(e.recording ?? {}) },
    anomaly: { ...DEFAULT_ANOMALY, ...(e.anomaly ?? {}) },
    relations: { ...DEFAULT_RELATIONS, ...(e.relations ?? {}) },
  };
}

function watchedAreas(e: Experiment): string {
  const n = e.anomaly.zones.filter((z) => z.enabled).length;
  return `${n} area${n === 1 ? "" : "s"} watched`;
}

/** Video files recorded during a run (from its final statistics). */
function videoFiles(r: { stats?: Record<string, unknown> }): number {
  const rec = r.stats?.recording as { files?: number } | undefined;
  return rec?.files ?? 0;
}
