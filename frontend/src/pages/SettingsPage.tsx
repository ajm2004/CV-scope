import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { SettingDefinition } from "../api/types";
import { ErrorNotice, KV, Notice, Panel, Pill } from "../components/ui";

const SECTIONS: { id: string; label: string }[] = [
  { id: "hardware", label: "Hardware" },
  { id: "models", label: "Models" },
  { id: "performance", label: "Performance" },
  { id: "cameras", label: "Cameras" },
  { id: "storage", label: "Storage" },
  { id: "video", label: "Video retention" },
  { id: "export", label: "Export" },
  { id: "logging", label: "Logging" },
  { id: "system", label: "System" },
];

function SettingInput({ def, value, onChange }: { def: SettingDefinition; value: unknown; onChange: (v: unknown) => void }) {
  if (def.kind === "bool")
    return (
      <label className="check">
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        {def.label}
      </label>
    );
  if (def.kind === "enum")
    return (
      <select value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
        {def.options?.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    );
  if (def.kind === "int" || def.kind === "float") return <input type="number" step={def.kind === "float" ? "0.1" : "1"} value={value === null || value === undefined ? "" : Number(value)} onChange={(e) => onChange(def.kind === "int" ? parseInt(e.target.value || "0", 10) : parseFloat(e.target.value || "0"))} />;
  return <input type="text" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />;
}

export default function SettingsPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["settings"], queryFn: api.settings.get });
  const privacy = useQuery({ queryKey: ["privacy"], queryFn: api.system.privacy });
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [advanced, setAdvanced] = useState(false);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (q.data) setValues(q.data.values);
  }, [q.data]);
  const save = useMutation({
    mutationFn: () => api.settings.update(values),
    onSuccess: () => {
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["privacy"] });
    },
  });
  if (q.isError) return <ErrorNotice error={q.error} />;
  if (!q.data) return <div className="hint">Loading settings…</div>;
  const defs = q.data.definitions.filter((d) => advanced || !d.advanced);
  const dirty = JSON.stringify(values) !== JSON.stringify(q.data.values);
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <div className="sub">Basic settings are enough for ordinary use. Advanced settings expose worker and export internals.</div>
        </div>
        <div className="row">
          <label className="check">
            <input type="checkbox" checked={advanced} onChange={(e) => setAdvanced(e.target.checked)} />
            Show advanced
          </label>
          {saved && <Pill tone="ok">Saved</Pill>}
          <button className="btn primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
            Save changes
          </button>
        </div>
      </div>
      {save.isError && <ErrorNotice error={save.error} />}
      <div className="grid-2">
        <div className="stack">
          {SECTIONS.map((s) => {
            const items = defs.filter((d) => d.section === s.id);
            if (!items.length) return null;
            return (
              <Panel key={s.id} title={s.label}>
                <div className="form-grid">
                  {items.map((d) => (
                    <div key={d.key} className="field">
                      {d.kind !== "bool" && <label>{d.label}</label>}
                      <SettingInput def={d} value={values[d.key]} onChange={(v) => setValues({ ...values, [d.key]: v })} />
                      {d.help && <span className="help">{d.help}</span>}
                    </div>
                  ))}
                </div>
              </Panel>
            );
          })}
        </div>
        <div className="stack">
          <Panel title="What this installation stores">
            {privacy.data && (
              <table className="table">
                <thead>
                  <tr>
                    <th>Data</th>
                    <th>Stored</th>
                    <th className="wrap">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {privacy.data.stored.map((s) => (
                    <tr key={s.item}>
                      <td>{s.item}</td>
                      <td>{s.stored ? <Pill tone="accent">yes</Pill> : <Pill>no</Pill>}</td>
                      <td className="wrap muted">{s.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="hint" style={{ marginTop: 8 }}>
              Track ids are anonymous and session-scoped. The open-source core has no face recognition or identity storage; the licensed recognition modules (Recognition section) only match deliberately enrolled identities and registered plates, and the list above reflects their current state.
            </div>
          </Panel>
          <Panel title="Environment (from .env)">
            <KV items={Object.entries(q.data.environment).map(([k, v]) => [k, <span className="mono">{String(v)}</span>])} />
            <Notice>Database, data directory and network settings come from the .env file and require a restart to change. See docs/installation.md.</Notice>
          </Panel>
        </div>
      </div>
    </div>
  );
}
