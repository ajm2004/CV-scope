import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import type { AnomalyAssistantView, LocalJob } from "../api/types";
import { ErrorNotice, Notice, Panel, Pill, Progress } from "./ui";

const TIER_LABEL = { light: "Light", capable: "Capable", large: "Large" } as const;

function gb(bytes: number | null | undefined): string {
  return bytes ? `${(bytes / 1024 ** 3).toFixed(1)} GB` : "–";
}

/** Install Ollama, download vision models and pick one, without leaving the page. */
export function LocalModelSetup({ vramGb, gpuName, activeModel, warning, onUsed }: { vramGb: number | null; gpuName?: string; activeModel: string | null; warning: string; onUsed: (v: AnomalyAssistantView) => void }) {
  const qc = useQueryClient();
  const [custom, setCustom] = useState("");
  const status = useQuery({
    queryKey: ["anomaly-local"],
    queryFn: api.localModels.status,
    refetchInterval: (q) => (q.state.data?.jobs.some((j) => j.status === "running") ? 1000 : 5000),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["anomaly-local"] });
  const install = useMutation({ mutationFn: api.localModels.install, onSuccess: refresh });
  const start = useMutation({ mutationFn: api.localModels.start, onSuccess: refresh });
  const pull = useMutation({ mutationFn: (m: string) => api.localModels.pull(m), onSuccess: refresh });
  const remove = useMutation({ mutationFn: (m: string) => api.localModels.remove(m), onSuccess: refresh });
  const unload = useMutation({ mutationFn: (m: string) => api.localModels.unload(m), onSuccess: refresh });
  const use = useMutation({
    mutationFn: (m: string) => api.localModels.use(m),
    onSuccess: (v) => {
      onUsed(v);
      refresh();
    },
  });
  const s = status.data;
  const o = s?.ollama;
  const installed = new Map((o?.models ?? []).map((m) => [m.name, m]));
  const has = (name: string) => installed.has(name) || installed.has(`${name}:latest`);
  const loaded = new Map((o?.loaded ?? []).map((m) => [m.name, m]));
  const jobFor = (kind: string, target: string): LocalJob | undefined => s?.jobs.find((j) => j.kind === kind && j.target === target && (j.status === "running" || (j.ended && Date.now() / 1000 - j.ended < 30)));
  const installJob = jobFor("install", "ollama");
  const extras = (o?.models ?? []).filter((m) => !s?.catalog.some((c) => c.model === m.name || `${c.model}:latest` === m.name));
  const errors = [install.error, start.error, pull.error, remove.error, unload.error, use.error].filter(Boolean);

  const pullButton = (name: string) => {
    const job = jobFor("pull", name);
    if (job?.status === "running")
      return (
        <div style={{ minWidth: 150 }}>
          <Progress value={job.progress ?? 0} />
          <div className="hint">
            {job.message} {job.total ? `${gb(job.completed)} of ${gb(job.total)}` : ""}
          </div>
        </div>
      );
    return (
      <>
        {job?.status === "failed" && <div className="hint" style={{ color: "var(--err)" }}>{job.error}</div>}
        <button className="btn sm" disabled={!o?.running} title={o?.running ? undefined : "Start Ollama first"} onClick={() => pull.mutate(name)}>
          Download
        </button>
      </>
    );
  };

  const actions = (name: string) => (
    <div className="row wrap" style={{ gap: 4, justifyContent: "flex-end" }}>
      {activeModel === name ? (
        <Pill tone="ok">In use</Pill>
      ) : (
        <button className="btn sm primary" onClick={() => use.mutate(name)}>
          Use
        </button>
      )}
      {loaded.has(name) && (
        <button className="btn sm ghost" title="Free its GPU memory now (it loads again on the next event)" onClick={() => unload.mutate(name)}>
          Unload
        </button>
      )}
      <button className="btn sm ghost" onClick={() => window.confirm(`Delete ${name} from this computer?`) && remove.mutate(name)}>
        Delete
      </button>
    </div>
  );

  return (
    <Panel title="Local vision models" actions={o?.running ? <Pill tone="ok" dot>Ollama {o.version}</Pill> : o?.installed ? <Pill tone="warn">Ollama stopped</Pill> : <Pill>Ollama not installed</Pill>}>
      <div className="stack" style={{ gap: 8 }}>
        <Notice tone="warn">{warning}</Notice>
        {gpuName && (
          <div className="hint">
            This machine: {gpuName}, {vramGb?.toFixed(0)} GB of GPU memory, shared with the detector and the recognition modules.
          </div>
        )}
        {status.isError && <ErrorNotice error={status.error} />}
        {o && !o.running && (!o.installed || installJob?.status === "running") && (
          <Notice>
            Local models run in <a href="https://ollama.com" target="_blank" rel="noreferrer">Ollama</a>, a free runtime for this computer.{" "}
            {o.can_install ? (
              installJob?.status === "running" ? (
                <div style={{ marginTop: 6 }}>
                  <Progress value={installJob.progress ?? 0} />
                  <div className="hint">{installJob.message}</div>
                </div>
              ) : (
                <div className="row" style={{ marginTop: 6, gap: 8 }}>
                  <button className="btn sm primary" disabled={install.isPending} onClick={() => install.mutate()}>
                    Install Ollama
                  </button>
                  <span className="hint">Downloads the official installer (about 1 GB), checks that it is signed by Ollama and installs it for this Windows user. No administrator rights needed.</span>
                </div>
              )
            ) : (
              <>
                Install it in a terminal: <span className="mono">{o.install_command ?? "see ollama.com/download"}</span>, then come back to this page.
              </>
            )}
            {installJob?.status === "failed" && <div className="hint" style={{ color: "var(--err)" }}>Install failed: {installJob.error}</div>}
          </Notice>
        )}
        {o && o.installed && !o.running && installJob?.status !== "running" && (
          <Notice tone="warn">
            Ollama is installed but not running.{" "}
            <button className="btn sm" disabled={start.isPending} onClick={() => start.mutate()}>
              {start.isPending ? "Starting…" : "Start Ollama"}
            </button>
          </Notice>
        )}
        {errors.map((e, i) => (
          <ErrorNotice key={i} error={e} />
        ))}
        <table className="table">
          <thead>
            <tr>
              <th>Model</th>
              <th className="num">Download</th>
              <th className="num">GPU memory</th>
              <th className="right"></th>
            </tr>
          </thead>
          <tbody>
            {s?.catalog.map((m) => {
              const fits = vramGb == null ? null : m.vram_gb <= vramGb - 2;
              const name = installed.has(m.model) ? m.model : `${m.model}:latest`;
              const present = has(m.model);
              const live = loaded.get(installed.has(m.model) ? m.model : name);
              return (
                <tr key={m.model}>
                  <td style={{ whiteSpace: "normal" }}>
                    <span className="mono">{m.model}</span> <span className="hint">{TIER_LABEL[m.tier]}</span>
                    {present && <Pill tone="ok">downloaded</Pill>}
                    {live && <Pill tone="accent">loaded, {gb(live.size_vram)} GPU</Pill>}
                    <div className="hint">{m.note}</div>
                  </td>
                  <td className="num">{m.download_gb} GB</td>
                  <td className="num">
                    ~{m.vram_gb} GB
                    {fits != null && <div>{fits ? <Pill tone="ok">fits</Pill> : <Pill tone="err">too large</Pill>}</div>}
                  </td>
                  <td className="right">{present ? actions(installed.has(m.model) ? m.model : name) : pullButton(m.model)}</td>
                </tr>
              );
            })}
            {extras.map((m) => (
              <tr key={m.name}>
                <td>
                  <span className="mono">{m.name}</span> <Pill tone="ok">downloaded</Pill>
                  <div className="hint">
                    {m.parameter_size ?? ""} {m.quantization ?? ""} {m.families?.length ? `· ${m.families.join(", ")}` : ""}
                  </div>
                </td>
                <td className="num">{gb(m.size)}</td>
                <td className="num">{loaded.get(m.name) ? gb(loaded.get(m.name)!.size_vram) : "–"}</td>
                <td className="right">{actions(m.name)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="row" style={{ gap: 6 }}>
          <input type="text" placeholder="Another model from ollama.com/library, e.g. qwen3-vl:4b" value={custom} onChange={(e) => setCustom(e.target.value)} style={{ flex: 1 }} />
          {custom.trim() && jobFor("pull", custom.trim())?.status === "running" ? (
            pullButton(custom.trim())
          ) : (
            <button className="btn sm" disabled={!o?.running || !custom.trim()} onClick={() => pull.mutate(custom.trim())}>
              Download
            </button>
          )}
        </div>
        <div className="hint">
          Models are stored by Ollama in {o?.models_folder ?? "~/.ollama/models"}. Choose one that needs vision (images); sizes are for 4-bit models and a few pictures and grow with the context size. After “Use”, press Test at the top.
        </div>
      </div>
    </Panel>
  );
}
