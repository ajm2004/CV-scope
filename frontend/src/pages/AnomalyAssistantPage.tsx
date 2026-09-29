import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { LLMSettings } from "../api/types";
import { LocalModelSetup } from "../components/LocalModelSetup";
import { ErrorNotice, Field, KV, Notice, Panel, Pill } from "../components/ui";

/** One vision language model for the whole installation, or none. */
export default function AnomalyAssistantPage() {
  const qc = useQueryClient();
  const view = useQuery({ queryKey: ["anomaly-assistant"], queryFn: api.anomalyAssistant.get, refetchInterval: 10_000 });
  const hardware = useQuery({ queryKey: ["hardware"], queryFn: () => api.hardware.get(), staleTime: 300_000 });
  const [form, setForm] = useState<LLMSettings | null>(null);
  const [key, setKey] = useState("");
  const [extra, setExtra] = useState("{}");
  const [extraError, setExtraError] = useState<string | null>(null);
  useEffect(() => {
    if (view.data && !form) {
      setForm(view.data.settings);
      setExtra(JSON.stringify(view.data.settings.extra_body ?? {}, null, 0));
    }
  }, [view.data, form]);
  const save = useMutation({
    mutationFn: (body: LLMSettings & { api_key?: string | null }) => api.anomalyAssistant.save(body),
    onSuccess: (v) => {
      qc.setQueryData(["anomaly-assistant"], v);
      setForm(v.settings);
      setKey("");
    },
  });
  const test = useMutation({ mutationFn: api.anomalyAssistant.test });
  const models = useMutation({ mutationFn: api.anomalyAssistant.models });

  if (view.isError) return <ErrorNotice error={view.error} />;
  if (!view.data || !form) return <div className="hint">Loading…</div>;
  const v = view.data;
  const info = v.providers.find((p) => p.id === form.provider)!;
  const keyState = v.keys[form.provider];
  const dirty = JSON.stringify(form) !== JSON.stringify(v.settings) || key !== "" || extra !== JSON.stringify(v.settings.extra_body ?? {}, null, 0);
  const set = (patch: Partial<LLMSettings>) => setForm({ ...form, ...patch });
  const suggestions = [...new Set([...(models.data?.models ?? []), ...info.models])];
  const gpu = hardware.data?.gpus.find((g) => !g.integrated && g.vram_total_bytes);
  const vramGb = gpu?.vram_total_bytes ? gpu.vram_total_bytes / 1024 ** 3 : null;

  const submit = (extraKey?: string | null) => {
    let extraBody: Record<string, unknown> = {};
    try {
      extraBody = extra.trim() ? JSON.parse(extra) : {};
      if (typeof extraBody !== "object" || Array.isArray(extraBody)) throw new Error("not an object");
      setExtraError(null);
    } catch {
      setExtraError('Extra request fields must be a JSON object, for example {"keep_alive": "10m"}.');
      return;
    }
    save.mutate({ ...form, extra_body: extraBody, ...(extraKey !== undefined ? { api_key: extraKey } : key ? { api_key: key } : {}) });
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Anomaly Assistant</h1>
          <div className="sub">
            One vision language model describes, and where an area asks for it confirms, the anomalies the computer vision found. Everything works without one. <Link to="/anomalies">See anomalies</Link>
          </div>
        </div>
        <div className="row">
          <button className="btn" disabled={dirty || form.provider === "none" || test.isPending} title={dirty ? "Save first" : undefined} onClick={() => test.mutate()}>
            {test.isPending ? "Testing…" : "Test"}
          </button>
          <button className="btn primary" disabled={!dirty || save.isPending} onClick={() => submit()}>
            Save
          </button>
        </div>
      </div>
      {save.isError && <ErrorNotice error={save.error} />}
      {test.isError && <ErrorNotice error={test.error} />}
      {test.data && (
        <Notice tone={test.data.result.verdict === "confirmed" ? "ok" : "warn"}>
          {info.name} · {test.data.result.model} answered in {(test.data.result.latency_ms / 1000).toFixed(1)} s with {test.data.result.images_sent} picture{test.data.result.images_sent === 1 ? "" : "s"}: <strong>{test.data.result.verdict}</strong> — “{test.data.result.description}”. Expected: {test.data.expected}.
        </Notice>
      )}
      <div className="grid-2" style={{ gridTemplateColumns: "minmax(0, 1.1fr) minmax(0, 1fr)", alignItems: "start" }}>
        <div className="stack">
          <Panel title="Model">
            <div className="form-grid">
              <Field label="Provider" className="span-2">
                <select value={form.provider} onChange={(e) => set({ provider: e.target.value as LLMSettings["provider"], model: "", base_url: "" })}>
                  {v.providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </Field>
              <div className="hint" style={{ gridColumn: "1 / -1" }}>
                {info.note}
              </div>
              {form.provider !== "none" && (
                <>
                  <Field label="Model" help={info.default_model ? `Empty: ${info.default_model}` : "The model name as the server lists it."}>
                    <input type="text" list="anomaly-models" placeholder={info.default_model} value={form.model} onChange={(e) => set({ model: e.target.value })} />
                    <datalist id="anomaly-models">
                      {suggestions.map((m) => (
                        <option key={m} value={m} />
                      ))}
                    </datalist>
                  </Field>
                  <Field label="Base URL" help={info.base_url ? `Empty: ${info.base_url}` : "Up to /v1, for example http://my-gateway:8080/v1"}>
                    <input type="text" placeholder={info.base_url} value={form.base_url} onChange={(e) => set({ base_url: e.target.value })} />
                  </Field>
                  {info.protocol === "openai" && (
                    <div style={{ gridColumn: "1 / -1" }}>
                      <button className="btn sm" disabled={dirty || models.isPending} title={dirty ? "Save first" : undefined} onClick={() => models.mutate()}>
                        {models.isPending ? "Asking the server…" : "List the server's models"}
                      </button>
                      {models.data && <span className="hint"> {models.data.models.length} models: pick one in the Model field.</span>}
                      {models.isError && <ErrorNotice error={models.error} />}
                    </div>
                  )}
                  {(info.needs_key || form.provider === "custom" || form.provider === "local") && (
                    <Field label={info.needs_key ? "API key" : "API key (if the server wants one)"} className="span-2" help={`Stored in the data folder, never in the database and never shown again. ${info.key_env.length ? `The environment variable ${info.key_env[0]} or PATHSCOPE_LLM_API_KEY wins over it.` : "PATHSCOPE_LLM_API_KEY wins over it."}`}>
                      <div className="row" style={{ gap: 6 }}>
                        <input type="password" autoComplete="off" placeholder={keyState?.set ? `Stored (${keyState.hint}) — type to replace` : "Paste the key"} value={key} onChange={(e) => setKey(e.target.value)} style={{ flex: 1 }} />
                        {keyState?.set && keyState.source === "file" && (
                          <button className="btn sm ghost" onClick={() => submit("")}>
                            Remove key
                          </button>
                        )}
                      </div>
                      {keyState?.source?.startsWith("env:") && <div className="hint">Using the key from {keyState.source.slice(4)}.</div>}
                    </Field>
                  )}
                </>
              )}
            </div>
          </Panel>
          {form.provider !== "none" && (
            <Panel title="What is sent, and how often">
              <div className="form-grid">
                <label className="check" style={{ gridColumn: "1 / -1" }}>
                  <input type="checkbox" checked={form.send_images} disabled={!info.vision} onChange={(e) => set({ send_images: e.target.checked })} />
                  Send the evidence pictures {info.vision ? "" : "(this provider reads text only)"}
                </label>
                <label className="check" style={{ gridColumn: "1 / -1" }}>
                  <input type="checkbox" checked={form.include_crops} onChange={(e) => set({ include_crops: e.target.checked })} />
                  Include close-ups of the changed area (up to 4 pictures per event instead of 2)
                </label>
                <Field label="Picture size (longer side, px)" help="Larger shows more detail and costs more tokens or GPU time.">
                  <input type="number" min={256} max={2048} step={64} value={form.image_max_px} onChange={(e) => set({ image_max_px: Number(e.target.value) })} />
                </Field>
                <Field label="Calls per hour at most" help="Across all cameras. Beyond it, events keep their computer-vision summary.">
                  <input type="number" min={1} step={1} value={form.max_calls_per_hour} onChange={(e) => set({ max_calls_per_hour: Number(e.target.value) })} />
                </Field>
                <Field label="Calls at the same time" help="Keep 1 for a local GPU.">
                  <input type="number" min={1} max={8} step={1} value={form.max_concurrent} onChange={(e) => set({ max_concurrent: Number(e.target.value) })} />
                </Field>
                <Field label="Events waiting at most">
                  <input type="number" min={1} max={1000} step={1} value={form.queue_limit} onChange={(e) => set({ queue_limit: Number(e.target.value) })} />
                </Field>
                <Field label="Timeout (s)">
                  <input type="number" min={2} max={600} step={1} value={form.timeout_s} onChange={(e) => set({ timeout_s: Number(e.target.value) })} />
                </Field>
                <Field label="Answer length (tokens)" help="Room for models that reason before answering.">
                  <input type="number" min={64} max={16000} step={64} value={form.max_output_tokens} onChange={(e) => set({ max_output_tokens: Number(e.target.value) })} />
                </Field>
                {info.protocol === "openai" && (
                  <label className="check" style={{ gridColumn: "1 / -1" }}>
                    <input type="checkbox" checked={form.json_mode} onChange={(e) => set({ json_mode: e.target.checked })} />
                    Ask the server for a JSON answer (turned off by itself when a server does not support it)
                  </label>
                )}
                <Field label="Extra request fields (JSON, advanced)" className="span-2" help='Merged into every request, for example {"keep_alive": "10m"} for Ollama or {"reasoning_effort": "low"}.'>
                  <input type="text" className="mono" value={extra} onChange={(e) => setExtra(e.target.value)} />
                  {extraError && <div className="hint" style={{ color: "var(--err)" }}>{extraError}</div>}
                </Field>
              </div>
            </Panel>
          )}
          <Panel title="Queue">
            <KV
              items={[
                ["Waiting or running", v.queue.pending],
                ["Calls in the last hour", `${v.queue.calls_last_hour} of ${v.settings.max_calls_per_hour}`],
                ["Answers since start", v.queue.calls],
                ["Failures", v.queue.failures],
                ["Skipped (budget / queue full)", `${v.queue.skipped_budget} / ${v.queue.skipped_queue}`],
                ["Last answer took", v.queue.last_latency_ms != null ? `${(v.queue.last_latency_ms / 1000).toFixed(1)} s` : "–"],
                ["Last error", v.queue.last_error ?? "–"],
              ]}
            />
          </Panel>
        </div>
        <div className="stack">
          <Panel title="Privacy">
            <div className="stack" style={{ gap: 6 }}>
              <div>
                Only confirmed anomalies are sent, one request per event (never the video stream): up to four pictures of the moment and written observations such as the zone, the kind of change, the time and the tracked objects.
              </div>
              <div>
                People and vehicles are aliases like [Person A] with an anonymous status (recognized person, unknown person, registered vehicle). The model never receives a name or a plate number and is asked not to read one out. Names appear on the Anomalies page only for
                viewers with a recognition token.
              </div>
              <div>{info.local ? <Pill tone="ok">Stays on this machine or network</Pill> : form.provider === "none" ? <Pill tone="ok">Nothing is sent</Pill> : <Pill tone="warn">Pictures leave this installation</Pill>}</div>
            </div>
          </Panel>
          <LocalModelSetup
            vramGb={vramGb}
            gpuName={gpu?.name}
            activeModel={v.settings.provider === "local" ? v.resolved.model : null}
            warning={v.local_warning}
            onUsed={(nv) => {
              qc.setQueryData(["anomaly-assistant"], nv);
              setForm(nv.settings);
              setKey("");
            }}
          />
        </div>
      </div>
    </div>
  );
}
