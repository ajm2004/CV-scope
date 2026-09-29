import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api } from "../api/client";
import type { Camera, CameraInput, SourceType, Video } from "../api/types";
import { ConfirmButton, Empty, ErrorNotice, Field, Notice, Panel, Pill } from "../components/ui";
import { bytes, seconds, SOURCE_LABEL } from "../lib/format";

/** ISO time -> the value of a local datetime-local input (seconds included), and back. */
const toLocalInput = (iso: string | null | undefined) => {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
};
const fromLocalInput = (v: string) => (v ? new Date(v).toISOString() : null);

export function VideoPicker({ value, onChange }: { value: number | null; onChange: (id: number | null, v?: Video) => void }) {
  const qc = useQueryClient();
  const videos = useQuery({ queryKey: ["videos"], queryFn: api.videos.list });
  const [uploading, setUploading] = useState(false);
  const [path, setPath] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const upload = async (file: File) => {
    setUploading(true);
    setErr(null);
    try {
      const v = await api.videos.upload(file);
      await qc.invalidateQueries({ queryKey: ["videos"] });
      onChange(v.id, v);
    } catch (e) {
      setErr(e);
    } finally {
      setUploading(false);
    }
  };
  const register = async () => {
    setErr(null);
    try {
      const v = await api.videos.register(path.trim());
      await qc.invalidateQueries({ queryKey: ["videos"] });
      onChange(v.id, v);
      setPath("");
    } catch (e) {
      setErr(e);
    }
  };
  return (
    <div className="stack" style={{ gap: 8 }}>
      <Field label="Video">
        <select value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null, videos.data?.find((v) => v.id === Number(e.target.value)))}>
          <option value="">Choose an uploaded video…</option>
          {videos.data?.map((v) => (
            <option key={v.id} value={v.id}>
              {v.filename} — {v.width}×{v.height}, {seconds(v.duration_s)}
            </option>
          ))}
        </select>
      </Field>
      <div className="inline-form">
        <Field label="Upload a video file">
          <input type="file" accept="video/*,.mkv,.avi,.mov,.mp4" disabled={uploading} onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        </Field>
        <Field label="Or use a file already on this computer" help="Absolute path, e.g. C:\\videos\\entrance.mp4 or /data/entrance.mp4">
          <div className="row">
            <input type="text" value={path} onChange={(e) => setPath(e.target.value)} placeholder="Full path to the video file" />
            <button type="button" className="btn" onClick={register} disabled={!path.trim()}>
              Use file
            </button>
          </div>
        </Field>
      </div>
      {uploading && <div className="hint">Uploading…</div>}
      {err ? <ErrorNotice error={err} /> : null}
    </div>
  );
}

const emptyForm = (projectId: number | null): CameraInput => ({ project_id: projectId ?? 0, name: "", location: "", source_type: "file", source_uri: "", video_id: null, rotation: 0, crop: null, processing_fps: null, requested_fps: null, width: null, height: null, reconnect: {}, enabled: true, notes: "" });

export function CameraForm({ initial, projectId, onSaved, onCancel }: { initial?: Camera | null; projectId?: number | null; onSaved: (c: Camera) => void; onCancel?: () => void }) {
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects.list });
  const [form, setForm] = useState<CameraInput>(initial ? { ...initial, video_id: initial.video_id } : emptyForm(projectId ?? null));
  const [advanced, setAdvanced] = useState(false);
  const [test, setTest] = useState<{ ok: boolean; message: string; width?: number; height?: number; fps?: number } | null>(null);
  const [testing, setTesting] = useState(false);
  const devices = useQuery({ queryKey: ["usb-devices"], queryFn: api.cameras.devices, enabled: form.source_type === "usb" });
  const set = (patch: Partial<CameraInput>) => setForm((f) => ({ ...f, ...patch }));
  // A new camera goes into the most recently used project unless one is chosen.
  useEffect(() => {
    if (!initial && !form.project_id && projects.data?.length) set({ project_id: projects.data[0].id });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects.data]);
  // Keep the stored device index in step with what the list shows.
  useEffect(() => {
    const first = devices.data?.usb[0];
    if (form.source_type === "usb" && !form.source_uri && first) set({ source_uri: String(first.index) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [devices.data, form.source_type]);
  const save = useMutation({
    mutationFn: () => (initial ? api.cameras.update(initial.id, form) : api.cameras.create(form)),
    onSuccess: onSaved,
  });
  const runTest = async () => {
    setTesting(true);
    setTest(null);
    try {
      const uri = form.source_type === "file" ? "" : form.source_uri ?? "";
      setTest((await api.cameras.testConnection({ source_type: form.source_type, source_uri: uri })) as typeof test);
    } catch (e) {
      setTest({ ok: false, message: String(e) });
    } finally {
      setTesting(false);
    }
  };
  const crop = form.crop ?? { x: 0, y: 0, w: 1, h: 1 };
  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <div className="form-grid">
        <Field label="Camera name">
          <input type="text" value={form.name} onChange={(e) => set({ name: e.target.value })} placeholder="CAM-01" required />
        </Field>
        <Field label="Location">
          <input type="text" value={form.location ?? ""} onChange={(e) => set({ location: e.target.value })} placeholder="Main entrance, facing north" />
        </Field>
        <Field label="Project">
          <select value={form.project_id || ""} onChange={(e) => set({ project_id: Number(e.target.value) })} required>
            <option value="">Select…</option>
            {projects.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Connection type">
          <select value={form.source_type} onChange={(e) => set({ source_type: e.target.value as SourceType, source_uri: "" })}>
            {(Object.keys(SOURCE_LABEL) as SourceType[]).map((k) => (
              <option key={k} value={k}>
                {SOURCE_LABEL[k]}
              </option>
            ))}
          </select>
        </Field>
      </div>

      {form.source_type === "file" && <VideoPicker value={form.video_id ?? null} onChange={(id, v) => set({ video_id: id, width: v?.width ?? null, height: v?.height ?? null, requested_fps: v?.fps ?? null })} />}
      {form.source_type === "file" && (
        <Field
          label="Recorded at (optional)"
          help="When the video's first frame was recorded. A run then dates everything it finds by the recording time instead of the time of the analysis, so the videos of several cameras line up for cross-camera moves. Leave empty to use the time of the analysis."
        >
          <input type="datetime-local" step="1" value={toLocalInput(form.recorded_at)} onChange={(e) => set({ recorded_at: fromLocalInput(e.target.value) })} style={{ maxWidth: 240 }} />
        </Field>
      )}
      {form.source_type === "usb" && (
        <div className="form-grid">
          <Field label="Camera device" help="Devices found on this computer. Probing takes a moment.">
            <select value={form.source_uri || "0"} onChange={(e) => set({ source_uri: e.target.value })}>
              {(devices.data?.usb ?? []).length === 0 && <option value="0">Device 0</option>}
              {devices.data?.usb.map((d) => (
                <option key={d.index} value={String(d.index)}>
                  Device {d.index} — {d.width}×{d.height}
                  {d.in_use ? ` (in use: ${d.in_use})` : ""}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Requested resolution">
            <div className="row">
              <input type="number" placeholder="width" value={form.width ?? ""} onChange={(e) => set({ width: e.target.value ? Number(e.target.value) : null })} />
              <span>×</span>
              <input type="number" placeholder="height" value={form.height ?? ""} onChange={(e) => set({ height: e.target.value ? Number(e.target.value) : null })} />
            </div>
          </Field>
          <Field label="Requested FPS">
            <input type="number" value={form.requested_fps ?? ""} onChange={(e) => set({ requested_fps: e.target.value ? Number(e.target.value) : null })} />
          </Field>
        </div>
      )}
      {(form.source_type === "rtsp" || form.source_type === "http") && (
        <Field label="Stream address" help="For RTSP: rtsp://user:password@camera-ip:554/stream. Credentials stay on this computer.">
          <input type="text" value={form.source_uri ?? ""} onChange={(e) => set({ source_uri: e.target.value })} placeholder="rtsp://…" required />
        </Field>
      )}
      {form.source_type !== "file" && (
        <div className="row">
          <button type="button" className="btn" onClick={runTest} disabled={testing}>
            {testing ? "Testing…" : "Test connection"}
          </button>
          {test && (
            <span className={`pill ${test.ok ? "ok" : "err"}`}>
              {test.message}
              {test.ok && test.width ? ` — ${test.width}×${test.height} @ ${test.fps?.toFixed(0)} fps` : ""}
            </span>
          )}
        </div>
      )}

      <Field label="Processing frame rate" help="How many frames per second are analysed. Leave empty to analyse every frame (recorded video) or the camera rate (live).">
        <input type="number" step="0.5" min="0.5" value={form.processing_fps ?? ""} onChange={(e) => set({ processing_fps: e.target.value ? Number(e.target.value) : null })} placeholder="every frame" style={{ maxWidth: 160 }} />
      </Field>

      <label className="check">
        <input type="checkbox" checked={advanced} onChange={(e) => setAdvanced(e.target.checked)} />
        Advanced settings
      </label>
      {advanced && (
        <div className="form-grid">
          <Field label="Rotation">
            <select value={form.rotation ?? 0} onChange={(e) => set({ rotation: Number(e.target.value) })}>
              {[0, 90, 180, 270].map((r) => (
                <option key={r} value={r}>
                  {r}°
                </option>
              ))}
            </select>
          </Field>
          <Field label="Crop (x, y, width, height as fractions)" help="Applied after rotation. Scene geometry refers to the cropped frame.">
            <div className="row">
              {(["x", "y", "w", "h"] as const).map((k) => (
                <input key={k} type="number" step="0.01" min="0" max="1" value={crop[k]} onChange={(e) => set({ crop: { ...crop, [k]: Number(e.target.value) } })} />
              ))}
              <button type="button" className="btn sm" onClick={() => set({ crop: null })}>
                Reset
              </button>
            </div>
          </Field>
          <Field label="Inference resolution (px)" help="Overrides the model default for this camera.">
            <input type="number" value={form.inference_size ?? ""} onChange={(e) => set({ inference_size: e.target.value ? Number(e.target.value) : null })} placeholder="model default" />
          </Field>
          {form.source_type !== "file" && (
            <>
              <Field label="Reconnect on stream loss">
                <label className="check">
                  <input type="checkbox" checked={(form.reconnect?.enabled as boolean | undefined) ?? true} onChange={(e) => set({ reconnect: { ...form.reconnect, enabled: e.target.checked } })} />
                  Enabled
                </label>
              </Field>
              <Field label="Reconnect delay (s, initial / max)">
                <div className="row">
                  <input type="number" value={(form.reconnect?.initial_delay_s as number | undefined) ?? 1} onChange={(e) => set({ reconnect: { ...form.reconnect, initial_delay_s: Number(e.target.value) } })} />
                  <input type="number" value={(form.reconnect?.max_delay_s as number | undefined) ?? 30} onChange={(e) => set({ reconnect: { ...form.reconnect, max_delay_s: Number(e.target.value) } })} />
                </div>
              </Field>
            </>
          )}
          <Field label="Notes" className="span-2">
            <textarea value={form.notes ?? ""} onChange={(e) => set({ notes: e.target.value })} />
          </Field>
        </div>
      )}
      {save.isError && <ErrorNotice error={save.error} />}
      <div className="row">
        <button className="btn primary" type="submit" disabled={save.isPending || !form.name || !form.project_id}>
          {initial ? "Save camera" : "Add camera"}
        </button>
        {onCancel && (
          <button className="btn" type="button" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

export default function CamerasPage() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const { cameraId } = useParams();
  const q = useQuery({ queryKey: ["cameras"], queryFn: () => api.cameras.list() });
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects.list });
  const [creating, setCreating] = useState(false);
  const selected = q.data?.find((c) => c.id === Number(cameraId)) ?? null;
  const [snapshotKey, setSnapshotKey] = useState(0);
  useEffect(() => setSnapshotKey((k) => k + 1), [selected?.id]);
  const remove = useMutation({
    mutationFn: (id: number) => api.cameras.remove(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cameras"] });
      nav("/cameras");
    },
  });
  const projectName = (id: number) => projects.data?.find((p) => p.id === id)?.name ?? `#${id}`;
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Cameras</h1>
          <div className="sub">Video files, USB cameras and network streams. Each camera has its own scene and can run one experiment at a time.</div>
        </div>
        <button className="btn primary" onClick={() => { setCreating(true); nav("/cameras"); }}>
          Add camera
        </button>
      </div>
      <div className="grid-2" style={{ gridTemplateColumns: "minmax(0, 1.2fr) minmax(360px, 1fr)" }}>
        <Panel title="Cameras" flush>
          {q.isError && <ErrorNotice error={q.error} />}
          {q.data && q.data.length === 0 && <Empty>No cameras yet. Add a video file, a USB camera or an RTSP stream.</Empty>}
          {q.data && q.data.length > 0 && (
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Project</th>
                  <th>Source</th>
                  <th>Resolution</th>
                  <th>Scene</th>
                  <th>State</th>
                </tr>
              </thead>
              <tbody>
                {q.data.map((c) => (
                  <tr key={c.id} className={`clickable ${selected?.id === c.id ? "selected" : ""}`} onClick={() => { setCreating(false); nav(`/cameras/${c.id}`); }}>
                    <td>{c.name}</td>
                    <td className="muted">{projectName(c.project_id)}</td>
                    <td>
                      {SOURCE_LABEL[c.source_type]}
                      <div className="hint mono" style={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis" }}>
                        {c.source_type === "file" ? c.video?.filename ?? c.source_uri : c.source_uri}
                      </div>
                    </td>
                    <td className="num">{c.width && c.height ? `${c.width}×${c.height}` : "–"}</td>
                    <td>{c.latest_scene_version ? `v${c.latest_scene_version}` : <span className="muted">none</span>}</td>
                    <td>{c.active_run_id ? <Pill tone="ok" dot>running</Pill> : c.enabled ? <Pill>idle</Pill> : <Pill tone="warn">disabled</Pill>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
        <div className="stack">
          {creating && (
            <Panel title="New camera">
              <CameraForm
                onSaved={(c) => {
                  setCreating(false);
                  qc.invalidateQueries({ queryKey: ["cameras"] });
                  nav(`/cameras/${c.id}`);
                }}
                onCancel={() => setCreating(false)}
              />
            </Panel>
          )}
          {selected && !creating && (
            <>
              <Panel
                title={selected.name}
                actions={
                  <>
                    <Link className="btn sm primary" to={`/scene/${selected.id}`}>
                      Open scene builder
                    </Link>
                    <ConfirmButton label="Delete" confirm="Delete camera?" onConfirm={() => remove.mutate(selected.id)} className="btn sm ghost" />
                  </>
                }
              >
                <div style={{ background: "var(--stage)", borderRadius: 3, minHeight: 120, display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 10 }}>
                  {selected.source_type === "file" ? (
                    <img key={snapshotKey} src={api.cameras.snapshotUrl(selected.id, 0)} alt="Camera snapshot" style={{ maxWidth: "100%", maxHeight: 300, display: "block" }} onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} />
                  ) : (
                    <img key={`live-${selected.id}-${snapshotKey}`} src={api.cameras.previewUrl(selected.id)} alt="Live camera view" style={{ maxWidth: "100%", maxHeight: 300, display: "block" }} />
                  )}
                </div>
                <div className="row" style={{ marginBottom: 8 }}>
                  {selected.source_type === "file" ? (
                    <button className="btn sm" onClick={() => setSnapshotKey((k) => k + 1)}>
                      Refresh snapshot
                    </button>
                  ) : (
                    <span className="hint">Live view. The camera stays on while this page shows it.</span>
                  )}
                  {selected.video && (
                    <span className="hint">
                      {selected.video.filename} · {bytes(selected.video.size_bytes)} · {seconds(selected.video.duration_s)} · {selected.video.fps?.toFixed(1)} fps
                    </span>
                  )}
                </div>
                <CameraForm
                  key={selected.id}
                  initial={selected}
                  onSaved={() => {
                    qc.invalidateQueries({ queryKey: ["cameras"] });
                    setSnapshotKey((k) => k + 1);
                  }}
                />
              </Panel>
            </>
          )}
          {!selected && !creating && <Notice>Select a camera to edit it, or add a new one.</Notice>}
        </div>
      </div>
    </div>
  );
}
