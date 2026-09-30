import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";
import { api } from "../api/client";
import type { SampleVideo, SourceType, Video } from "../api/types";
import { ErrorNotice, Field, KV, Notice, Panel, Pill, Progress } from "../components/ui";
import { gb } from "../lib/format";
import { VideoPicker } from "./CamerasPage";
import { RecommendationTiers } from "./HardwarePage";
import { useGuideState } from "../guides/state";

const STEPS = ["System check", "Hardware", "Model recommendation", "Detector", "Camera or video", "Project", "Scene Builder"];

export default function SetupPage() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [step, setStep] = useState(0);
  const status = useQuery({ queryKey: ["system-status"], queryFn: api.system.status, refetchInterval: 5000 });
  const hw = useQuery({ queryKey: ["hardware"], queryFn: () => api.hardware.get(false) });
  const models = useQuery({ queryKey: ["models"], queryFn: api.models.list, refetchInterval: 2000 });
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings.get });
  const samples = useQuery({ queryKey: ["video-samples"], queryFn: api.videos.samples });
  const [chosenModel, setChosenModel] = useState<string>("");
  const [sourceType, setSourceType] = useState<SourceType>("file");
  const [videoId, setVideoId] = useState<number | null>(null);
  const [video, setVideo] = useState<Video | undefined>();
  const [uri, setUri] = useState("");
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [projectName, setProjectName] = useState("");
  const [cameraName, setCameraName] = useState("CAM-01");
  const [error, setError] = useState<unknown>(null);
  const openGuide = useGuideState((g) => g.openPanel);

  const install = useMutation({ mutationFn: (id: string) => api.models.install(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["models"] }), onError: setError });
  const finish = useMutation({
    mutationFn: async () => {
      const p = await api.projects.create({ name: projectName.trim() || "My first project" });
      const cam = await api.cameras.create({ project_id: p.id, name: cameraName || "CAM-01", source_type: sourceType, source_uri: sourceType === "file" ? "" : uri, video_id: sourceType === "file" ? videoId : null });
      if (chosenModel) await api.settings.update({ default_model_id: chosenModel });
      await api.system.setupComplete();
      return cam;
    },
    onSuccess: (cam) => {
      qc.invalidateQueries();
      nav(`/scene/${cam.id}`);
    },
    onError: setError,
  });

  const recs = models.data?.recommendations;
  const defaultTier = recs?.tiers.find((t) => t.tier === recs.default_tier);
  const modelId = chosenModel || defaultTier?.model_id || "";
  const model = models.data?.models.find((m) => m.id === modelId);
  const installedAny = models.data?.models.some((m) => m.task === "detection" && m.installed && m.provider_available) ?? false;
  const canProceedSource = sourceType === "file" ? videoId !== null : uri.trim().length > 0;

  const pickSample = async (s: SampleVideo) => {
    setError(null);
    try {
      const v = s.video_id !== null ? await api.videos.get(s.video_id) : await api.videos.register(s.path);
      await qc.invalidateQueries({ queryKey: ["videos"] });
      await qc.invalidateQueries({ queryKey: ["video-samples"] });
      setVideoId(v.id);
      setVideo(v);
    } catch (e) {
      setError(e);
    }
  };

  const testConnection = async () => {
    setTestResult(null);
    try {
      setTestResult(await api.cameras.testConnection({ source_type: sourceType, source_uri: uri }));
    } catch (e) {
      setTestResult({ ok: false, message: String(e) });
    }
  };

  return (
    <div className="stack" style={{ maxWidth: 1000 }}>
      <div className="page-head">
        <div>
          <h1>First-run setup</h1>
          <div className="sub">Seven short steps from an empty install to a scene you can draw on. Everything can be changed later.</div>
        </div>
        <button className="btn ghost sm" onClick={() => nav("/projects")}>
          Skip setup
        </button>
      </div>
      <div className="steps">
        {STEPS.map((s, i) => (
          <div key={s} className={i < step ? "done" : i === step ? "current" : ""}>
            {i + 1}. {s}
          </div>
        ))}
      </div>
      {error ? <ErrorNotice error={error} /> : null}

      {step === 0 && (
        <Panel title="System check">
          {status.isError && <Notice tone="err">The API is not reachable. Start the backend (see README) and reload this page.</Notice>}
          {status.data && (
            <KV
              items={[
                ["API", <Pill tone="ok">connected, version {status.data.version}</Pill>],
                ["Database", status.data.database.ok ? <Pill tone="ok">{status.data.database.dialect} ready</Pill> : <Pill tone="err">{status.data.database.error}</Pill>],
                ["Data directory", <span className="mono">{status.data.data_dir}</span>],
                ["Models directory", <span className="mono">{status.data.models_dir}</span>],
                ["Detector providers", hw.data ? Object.entries(hw.data.providers).map(([k, v]) => `${k}: ${v ? "installed" : "missing"}`).join(" · ") : "…"],
              ]}
            />
          )}
          {hw.data && !Object.values(hw.data.providers).some(Boolean) && <Notice tone="warn">No detector provider is installed. Install ultralytics, torchvision or onnxruntime (docs/installation.md) before continuing.</Notice>}
        </Panel>
      )}
      {step === 1 && (
        <Panel title="Hardware detected">
          {hw.data ? (
            <KV
              items={[
                ["Operating system", hw.data.os],
                ["CPU", `${hw.data.cpu.model} — ${hw.data.cpu.physical_cores} cores / ${hw.data.cpu.logical_cores} threads`],
                ["Memory", `${gb(hw.data.memory.total_bytes)} total, ${gb(hw.data.memory.available_bytes)} available`],
                ["GPU", hw.data.gpus.length ? hw.data.gpus.map((g) => `${g.name}${g.vram_total_bytes ? ` (${gb(g.vram_total_bytes)} VRAM)` : ""}${g.integrated ? " integrated" : ""}`).join("; ") : "none detected"],
                ["CUDA", hw.data.acceleration.cuda_available ? `available (${hw.data.acceleration.cuda_version})` : "not available"],
                ["Apple Metal", hw.data.acceleration.mps_available ? "available" : "not available"],
                ["Disk free", gb(hw.data.disk.free_bytes)],
              ]}
            />
          ) : (
            <div className="hint">Probing…</div>
          )}
        </Panel>
      )}
      {step === 2 && (
        <Panel title="Recommended detectors for this system">
          <RecommendationTiers compact />
        </Panel>
      )}
      {step === 3 && (
        <Panel title="Download a detector">
          <div className="form-grid">
            <Field label="Detector" help="The recommended tier is preselected. You can install more later on the Models page.">
              <select value={modelId} onChange={(e) => setChosenModel(e.target.value)}>
                {models.data?.models.filter((m) => m.task === "detection" && m.provider_available).map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name} — {m.provider}, {m.license}
                    {m.recommended_tier ? ` (${m.recommended_tier})` : ""}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          {model && (
            <div style={{ marginTop: 10 }}>
              {model.installed ? (
                <Pill tone="ok">Installed</Pill>
              ) : model.job && (model.job.status === "running" || model.job.status === "queued") ? (
                <div style={{ maxWidth: 360 }}>
                  <div className="small">{model.job.message}</div>
                  <Progress value={model.job.progress} />
                </div>
              ) : (
                <button className="btn primary" onClick={() => install.mutate(model.id)}>
                  Download {model.name} ({model.size_mb ? `${model.size_mb} MB` : "size unknown"})
                </button>
              )}
              <div className="hint" style={{ marginTop: 6 }}>{model.license_note}</div>
            </div>
          )}
          {!installedAny && !model?.installed && <div className="hint" style={{ marginTop: 8 }}>You need at least one installed detector to run an experiment.</div>}
        </Panel>
      )}
      {step === 4 && (
        <Panel title="Add a camera or a sample video">
          <Field label="Source">
            <select value={sourceType} onChange={(e) => setSourceType(e.target.value as SourceType)} style={{ maxWidth: 300 }}>
              <option value="file">Video file (upload or local file)</option>
              <option value="usb">USB / built-in camera</option>
              <option value="rtsp">RTSP stream</option>
              <option value="http">HTTP / IP camera stream</option>
            </select>
          </Field>
          <div style={{ marginTop: 10 }}>
            {sourceType === "file" && (
              <>
                <VideoPicker value={videoId} onChange={(id, v) => { setVideoId(id); setVideo(v); }} />
                {samples.data && samples.data.length > 0 ? (
                  <div className="row" style={{ marginTop: 8, flexWrap: "wrap", gap: 8 }}>
                    <span className="small">Or start with a sample clip:</span>
                    {samples.data.map((s) => (
                      <button key={s.path} type="button" className="btn" onClick={() => pickSample(s)}>
                        {s.name}
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="hint" style={{ marginTop: 6 }}>
                    No sample clips yet. Choose "Sample videos" in the Windows installer or run <code>python scripts/download_samples.py</code>; they then appear here.
                  </div>
                )}
              </>
            )}
            {sourceType !== "file" && (
              <div className="stack">
                <Field label={sourceType === "usb" ? "Device index" : "Stream address"}>
                  <input type="text" value={uri} onChange={(e) => setUri(e.target.value)} placeholder={sourceType === "usb" ? "0" : "rtsp://user:password@192.168.1.20:554/stream1"} />
                </Field>
                <div className="row">
                  <button className="btn" onClick={testConnection} disabled={!uri.trim()}>
                    Test connection
                  </button>
                  {testResult && <Pill tone={testResult.ok ? "ok" : "err"}>{testResult.message}</Pill>}
                </div>
              </div>
            )}
          </div>
          {video && <div className="hint" style={{ marginTop: 6 }}>{video.filename}: {video.width}×{video.height}, {video.fps?.toFixed(1)} fps</div>}
        </Panel>
      )}
      {step === 5 && (
        <Panel title="Create the first project">
          <div className="form-grid">
            <Field label="Project name">
              <input type="text" value={projectName} onChange={(e) => setProjectName(e.target.value)} placeholder="Pedestrian route behaviour study" />
            </Field>
            <Field label="Camera name">
              <input type="text" value={cameraName} onChange={(e) => setCameraName(e.target.value)} />
            </Field>
          </div>
          <div className="hint" style={{ marginTop: 8 }}>More cameras and experiments can be added later from the project page.</div>
        </Panel>
      )}
      {step === 6 && (
        <Panel title="Open the Scene Builder">
          <p>CV-Scope will create the project and camera, remember the detector you chose, and open the Scene Builder so you can draw gates, zones and routes over the first frame.</p>
          <KV
            items={[
              ["Project", projectName || "My first project"],
              ["Camera", `${cameraName} (${sourceType === "file" ? video?.filename ?? "video" : uri})`],
              ["Detector", model ? `${model.name}${model.installed ? "" : " (not installed yet)"}` : "recommended"],
            ]}
          />
          {!installedAny && <Notice tone="warn">No detector is installed yet; you can still draw the scene, but starting a run needs an installed detector (Models page).</Notice>}
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn sm" onClick={() => openGuide("02-count-a-line")}>
              Open guide 02 beside the app
            </button>
            <span className="hint">It walks through drawing a counting line and reading the results. All guides are under Help, Guides.</span>
          </div>
        </Panel>
      )}

      <div className="row" style={{ justifyContent: "space-between" }}>
        <button className="btn" onClick={() => setStep(Math.max(0, step - 1))} disabled={step === 0}>
          Back
        </button>
        {step < STEPS.length - 1 ? (
          <button className="btn primary" onClick={() => setStep(step + 1)} disabled={(step === 0 && !status.data?.database.ok) || (step === 4 && !canProceedSource) || (step === 5 && !projectName.trim())}>
            Continue
          </button>
        ) : (
          <button className="btn primary" onClick={() => finish.mutate()} disabled={finish.isPending}>
            Create and open Scene Builder
          </button>
        )}
      </div>
      {settings.data && settings.data.values.setup_completed === true && <div className="hint">Setup was already completed on this installation; running it again only adds a new project and camera.</div>}
    </div>
  );
}
