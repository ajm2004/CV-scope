import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import { ErrorNotice, KV, Notice, Panel, Pill } from "../components/ui";
import { gb, num, pct } from "../lib/format";

export function RecommendationTiers({ compact = false }: { compact?: boolean }) {
  const q = useQuery({ queryKey: ["recommendations"], queryFn: api.hardware.recommendations });
  if (q.isError) return <ErrorNotice error={q.error} />;
  if (!q.data) return <div className="hint">Calculating recommendations…</div>;
  const r = q.data;
  return (
    <div className="stack">
      <div className="kv-inline">
        <KV
          items={[
            ["Workload class", <span>{r.workload_summary}</span>],
            ["Inference engine", <span>{r.runtime_label} <span className="muted">— {r.runtime_reason}</span></span>],
            ["Fallback order", r.fallback_chain.length ? r.fallback_chain.join(" → ") : "none"],
            ["Basis", r.benchmarked ? "Local benchmark available" : <span className="muted">Estimated from hardware; run a benchmark on the Models page to measure real throughput.</span>],
          ]}
        />
      </div>
      {r.warnings.map((w) => (
        <Notice key={w} tone="warn">
          {w}
        </Notice>
      ))}
      <table className="table">
        <thead>
          <tr>
            <th>Tier</th>
            <th>Detector</th>
            <th>Device</th>
            <th className="num">Inference size</th>
            <th>Status</th>
            {!compact && <th className="wrap">Why</th>}
          </tr>
        </thead>
        <tbody>
          {r.tiers.map((t) => (
            <tr key={t.tier}>
              <td>
                {t.title} {t.tier === r.default_tier && <Pill tone="accent">recommended</Pill>}
              </td>
              <td>{t.model_name}</td>
              <td className="mono">{t.device}</td>
              <td className="num">{t.image_size}px</td>
              <td>
                {!t.available ? <Pill tone="warn">{t.unavailable_reason}</Pill> : t.installed ? <Pill tone="ok">installed</Pill> : <Link to="/models">install</Link>}
              </td>
              {!compact && <td className="wrap">{t.reasons.join(" ")}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** What the licensed recognition modules cost on this machine (whether or not they are licensed). */
export function RecognitionImpactPanel() {
  const [faceStack, setFaceStack] = useState("opencv");
  const [fps, setFps] = useState(10);
  const q = useQuery({ queryKey: ["recognition-impact", faceStack, fps], queryFn: () => api.hardware.recognitionImpact({ face: true, plate: true, face_stack: faceStack, processing_fps: fps }) });
  const active = useQuery({ queryKey: ["recommendations"], queryFn: api.hardware.recommendations });
  const r = q.data;
  return (
    <Panel
      title="Recognition modules: effect on camera capacity"
      actions={
        <span className="row">
          <select value={faceStack} onChange={(e) => setFaceStack(e.target.value)} style={{ width: "auto" }}>
            <option value="opencv">Face stack: OpenCV (YuNet + SFace, CPU)</option>
            <option value="insightface">Face stack: InsightFace (SCRFD + ArcFace)</option>
          </select>
          <select value={fps} onChange={(e) => setFps(Number(e.target.value))} style={{ width: "auto" }}>
            {[5, 10, 15, 25].map((f) => (
              <option key={f} value={f}>
                {f} processed fps
              </option>
            ))}
          </select>
        </span>
      }
    >
      {q.isError && <ErrorNotice error={q.error} />}
      {r && (
        <>
          <KV
            items={[
              ["Full pipeline", r.components.join(" + ")],
              ["Streams without recognition", `about ${num(r.camera_capacity_without, 1)}`],
              ["Streams with face and plate recognition", `about ${num(r.camera_capacity_with, 1)} (${num(r.reduction_percent, 0)}% less)`],
              ["Where it runs", Object.entries(r.modules).map(([m, v]) => `${m}: ${v.stack} on ${v.device.toUpperCase()}`).join(" · ")],
              ["Basis", r.note],
            ]}
          />
          {r.warning && <Notice tone="warn">{r.warning}</Notice>}
          {active.data?.recognition?.warning && <Notice tone="warn">Currently active modules: {active.data.recognition.warning}</Notice>}
        </>
      )}
    </Panel>
  );
}

export default function HardwarePage() {
  const qc = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);
  const q = useQuery({ queryKey: ["hardware"], queryFn: () => api.hardware.get(false) });
  const load = useQuery({ queryKey: ["system-load"], queryFn: api.system.load, refetchInterval: 3000 });
  const refresh = async () => {
    setRefreshing(true);
    try {
      await api.hardware.get(true);
      await qc.invalidateQueries({ queryKey: ["hardware"] });
      await qc.invalidateQueries({ queryKey: ["recommendations"] });
    } finally {
      setRefreshing(false);
    }
  };
  if (q.isError) return <ErrorNotice error={q.error} />;
  if (!q.data) return <div className="hint">Probing hardware…</div>;
  const hw = q.data;
  const gpu = hw.gpus.find((g) => !g.integrated && g.vram_total_bytes) ?? hw.gpus[0];
  const acc = hw.acceleration;
  const util = (load.data?.utilization ?? {}) as { cpu_percent?: number; memory_percent?: number; gpus?: { index: number; utilization_percent: number; vram_used_bytes: number; vram_total_bytes: number }[] };
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Hardware</h1>
          <div className="sub">Detected on {hw.hostname} · probed {new Date(hw.probed_at * 1000).toLocaleTimeString()}</div>
        </div>
        <button className="btn" onClick={refresh} disabled={refreshing}>
          {refreshing ? "Probing…" : "Probe again"}
        </button>
      </div>

      <div className="grid-3">
        <Panel title="System">
          <KV
            items={[
              ["Operating system", `${hw.os} (${hw.os_version})`],
              ["Python", hw.python_version],
              ["CPU", hw.cpu.model],
              ["Cores / threads", `${hw.cpu.physical_cores ?? "?"} cores / ${hw.cpu.logical_cores ?? "?"} threads`],
              ["Max frequency", hw.cpu.max_frequency_mhz ? `${(hw.cpu.max_frequency_mhz / 1000).toFixed(2)} GHz` : "–"],
              ["SIMD", hw.cpu.flags.join(", ") || "–"],
              ["Memory", `${gb(hw.memory.total_bytes)} total · ${gb(hw.memory.available_bytes)} available`],
              ["Disk (data directory)", `${gb(hw.disk.free_bytes)} free of ${gb(hw.disk.total_bytes)}`],
            ]}
          />
        </Panel>
        <Panel title="GPU">
          {hw.gpus.length === 0 && <div className="muted">No GPU adapters were found.</div>}
          {hw.gpus.map((g) => (
            <div key={`${g.source}-${g.index}`} style={{ marginBottom: 10 }}>
              <div className="row">
                <strong>{g.name}</strong>
                {g.integrated && <Pill>integrated</Pill>}
                {g === gpu && hw.gpus.length > 1 && <Pill tone="accent">primary</Pill>}
              </div>
              <KV
                items={[
                  ["VRAM", g.vram_total_bytes ? `${gb(g.vram_total_bytes)}${g.vram_used_bytes !== null ? ` (${gb(g.vram_used_bytes)} in use)` : ""}` : "unknown"],
                  ["Driver", g.driver_version ?? "–"],
                  ["CUDA driver", g.cuda_driver_version ?? "–"],
                  ["Compute capability", g.compute_capability ?? "–"],
                  ["Detected via", g.source],
                ]}
              />
            </div>
          ))}
        </Panel>
        <Panel title="Acceleration">
          <KV
            items={[
              ["CUDA", acc.cuda_available ? <Pill tone="ok">available {acc.cuda_version}</Pill> : <Pill>not available</Pill>],
              ["cuDNN", acc.cudnn_version ?? "–"],
              ["ROCm", acc.rocm_available ? <Pill tone="ok">available {acc.rocm_version}</Pill> : <Pill>not available</Pill>],
              ["Apple Metal (MPS)", acc.mps_available ? <Pill tone="ok">available</Pill> : <Pill>not available</Pill>],
              ["TensorRT", acc.tensorrt_available ? <Pill tone="ok">available</Pill> : <Pill>not installed</Pill>],
              ["OpenVINO", acc.openvino_available ? <Pill tone="ok">available</Pill> : <Pill>not installed</Pill>],
              ["ONNX Runtime providers", acc.onnxruntime_providers.join(", ") || "onnxruntime not installed"],
            ]}
          />
        </Panel>
      </div>

      <Panel title="Recommended detectors for this system">
        <RecommendationTiers />
      </Panel>

      <RecognitionImpactPanel />


      <div className="grid-2">
        <Panel title="Inference runtimes">
          <table className="table">
            <thead>
              <tr>
                <th>Runtime</th>
                <th>Status</th>
                <th>Version</th>
                <th className="wrap">Detail</th>
              </tr>
            </thead>
            <tbody>
              {hw.runtimes.map((r) => (
                <tr key={r.id}>
                  <td>{r.label}</td>
                  <td>{r.available ? <Pill tone="ok">available</Pill> : <Pill>unavailable</Pill>}</td>
                  <td className="mono">{r.version ?? "–"}</td>
                  <td className="wrap muted">{r.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <div className="stack">
          <Panel title="Installed libraries">
            <KV items={Object.entries(hw.library_versions).map(([k, v]) => [k, v ?? <span className="muted">not installed</span>])} />
            <div className="hint" style={{ marginTop: 8 }}>
              Detector providers: {Object.entries(hw.providers).map(([k, v]) => `${k} ${v ? "✓" : "✗"}`).join(" · ")}
            </div>
          </Panel>
          <Panel title="Current load">
            <KV
              items={[
                ["CPU", pct(util.cpu_percent ?? null)],
                ["Memory", pct(util.memory_percent ?? null)],
                ...(util.gpus ?? []).map((g) => [`GPU ${g.index}`, `${pct(g.utilization_percent)} · VRAM ${gb(g.vram_used_bytes)} / ${gb(g.vram_total_bytes)}`] as [string, string]),
                ["Estimated pipeline load", load.data ? `${num((load.data.estimate as { gpu_percent: number }).gpu_percent, 0)}% GPU · ${num((load.data.estimate as { cpu_percent: number }).cpu_percent, 0)}% CPU (${(load.data.estimate as { basis: string }).basis})` : "–"],
              ]}
            />
          </Panel>
        </div>
      </div>
    </div>
  );
}
