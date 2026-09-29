/* Who may see and do what with relationship data, which recognition results
 * feed the graph, how long data is kept, user-defined relationship types and
 * the audit trail. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { ErrorNotice, Field, Notice, Panel, Pill } from "../components/ui";
import { dateTime } from "../lib/format";
import { useRecognitionAuth } from "../lib/recognitionToken";
import { rel, type RelationshipSettings } from "./api";
import "./relationships.css";

const ROLES = [
  { id: "none", label: "Anyone who can open CV-Scope" },
  { id: "viewer", label: "Recognition viewer or higher" },
  { id: "operator", label: "Recognition operator or higher" },
  { id: "admin", label: "Recognition administrator" },
];

const ACCESS: { key: keyof RelationshipSettings["access"]; label: string; help: string }[] = [
  { key: "graph_role", label: "Read relationships, timelines and search", help: "Relationship data can reveal routines; restrict it if this computer is shared." },
  { key: "identity_role", label: "See names, plates and identity history", help: "Everyone else sees “Recognized person” without a name and cannot open identity history." },
  { key: "export_role", label: "Export anonymous relationship data", help: "" },
  { key: "export_identity_role", label: "Export with names and plates", help: "" },
  { key: "rules_role", label: "Change rules, analyse runs again, send sensor observations", help: "" },
  { key: "delete_role", label: "Delete relationship data", help: "" },
  { key: "settings_role", label: "Change these settings", help: "While no recognition access token exists, only from the CV-Scope computer itself." },
];

export default function RelationshipSettingsPage() {
  const qc = useQueryClient();
  const token = useRecognitionAuth((s) => s.token);
  const q = useQuery({ queryKey: ["relationship-settings", token], queryFn: rel.settings });
  const audit = useQuery({ queryKey: ["relationship-audit", token], queryFn: () => rel.audit(200), retry: 0, enabled: !!q.data?.viewer.can.settings });
  const [form, setForm] = useState<RelationshipSettings | null>(null);
  useEffect(() => {
    if (q.data) setForm(structuredClone(q.data.settings));
  }, [q.data]);
  const save = useMutation({
    mutationFn: () => rel.saveSettings(form!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["relationship-settings"] });
      qc.invalidateQueries({ queryKey: ["relationships-meta"] });
      qc.invalidateQueries({ queryKey: ["relationship-audit"] });
    },
  });
  if (q.isError) return <ErrorNotice error={q.error} />;
  if (!form || !q.data) return <div className="hint">Loading…</div>;
  const viewer = q.data.viewer;
  const dirty = JSON.stringify(form) !== JSON.stringify(q.data.settings);
  const set = <K extends keyof RelationshipSettings>(k: K, v: RelationshipSettings[K]) => setForm({ ...form, [k]: v });

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Relationship settings</h1>
          <div className="sub">
            Access, recognition modules, retention, relationship types and the audit trail of the relationship graph. You are{" "}
            <strong>{viewer.role === "none" ? "not signed in with a recognition token" : `${viewer.name} (${viewer.role})`}</strong>
            {viewer.role === "none" && (
              <>
                {" "}
                — sign in on the <Link to="/recognition/people">People</Link> page.
              </>
            )}
          </div>
        </div>
        <div className="row">
          <button className="btn primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
            Save
          </button>
        </div>
      </div>
      {save.isError && <ErrorNotice error={save.error} />}
      {save.isSuccess && !dirty && <Notice tone="ok">Saved.</Notice>}
      <div className="grid-2" style={{ alignItems: "start" }}>
        <Panel title="Access">
          <div className="stack" style={{ gap: 8 }}>
            {ACCESS.map((a) => (
              <Field key={a.key} label={a.label} help={a.help || undefined}>
                <select value={form.access[a.key]} onChange={(e) => set("access", { ...form.access, [a.key]: e.target.value })}>
                  {ROLES.filter((r) => a.key !== "identity_role" || r.id !== "none").map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.label}
                    </option>
                  ))}
                </select>
              </Field>
            ))}
            <div className="hint">Roles are the recognition access tokens' roles (viewer &lt; operator &lt; administrator).</div>
          </div>
        </Panel>
        <div className="stack">
          <Panel title="Recognition and sensor input">
            <div className="stack" style={{ gap: 6 }}>
              <label className="check">
                <input type="checkbox" checked={form.modules.face} onChange={(e) => set("modules", { ...form.modules, face: e.target.checked })} />
                Use face recognition results (Track IDENTIFIED_AS a recognized person)
              </label>
              <label className="check">
                <input type="checkbox" checked={form.modules.plate} onChange={(e) => set("modules", { ...form.modules, plate: e.target.checked })} />
                Use plate recognition results (IDENTIFIED_BY_PLATE, REGISTERED_AS)
              </label>
              <label className="check">
                <input type="checkbox" checked={form.modules.sensors} onChange={(e) => set("modules", { ...form.modules, sensors: e.target.checked })} />
                Accept observations from external sensors (depth, radar, thermal) through the API
              </label>
              <div className="hint">Switched-off identities are hidden in every view and not created by new runs. Anonymous tracking always works.</div>
            </div>
          </Panel>
          <Panel title="Retention">
            <div className="stack" style={{ gap: 8 }}>
              <Field label="Delete relationship data after (days, 0 = keep)">
                <input type="number" min={0} value={form.retention.days} onChange={(e) => set("retention", { ...form.retention, days: Number(e.target.value) || 0 })} />
              </Field>
              <Field label="Delete identity links after (days, 0 = keep)" help="Links between tracks and recognized people or plates, and deviations about them.">
                <input type="number" min={0} value={form.retention.identity_days} onChange={(e) => set("retention", { ...form.retention, identity_days: Number(e.target.value) || 0 })} />
              </Field>
              <Field label="Delete audit records after (days, 0 = keep)">
                <input type="number" min={0} value={form.retention.audit_days} onChange={(e) => set("retention", { ...form.retention, audit_days: Number(e.target.value) || 0 })} />
              </Field>
              <div className="hint">Checked every hour. Deleting a run deletes its relationship data.</div>
            </div>
          </Panel>
          <Panel title="Summaries">
            <label className="check">
              <input type="checkbox" checked={form.llm_summaries} onChange={(e) => set("llm_summaries", e.target.checked)} />
              Allow a language model to reword timeline summaries
            </label>
            <div className="hint">
              Uses the model chosen on the <Link to="/anomalies/assistant">Anomaly Assistant</Link> page. It receives the anonymous deterministic summary only (no names, no plates, no pictures) and never creates relationships; the deterministic summary stays the source of
              truth.
            </div>
          </Panel>
        </div>
      </div>
      <Panel title="Relationship types you add">
        <div className="stack" style={{ gap: 8 }}>
          <div className="hint">
            Add observable types for your rules (for example WAITED_FOR). Personal or organisational relations (colleague, family, owner…) can only be added as <em>external only</em>: they come from an authorized registry through the API and are never
            produced by rules.
          </div>
          {form.custom_types.map((t, i) => (
            <div key={i} className="row wrap" style={{ gap: 6 }}>
              <input type="text" value={t.id} placeholder="TYPE_ID" onChange={(e) => set("custom_types", form.custom_types.map((x, j) => (j === i ? { ...x, id: e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "_") } : x)))} style={{ width: 180 }} />
              <input type="text" value={t.label} placeholder="verb phrase, e.g. waited for" onChange={(e) => set("custom_types", form.custom_types.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} style={{ width: 200 }} />
              <label className="check">
                <input type="checkbox" checked={t.symmetric} onChange={(e) => set("custom_types", form.custom_types.map((x, j) => (j === i ? { ...x, symmetric: e.target.checked } : x)))} />
                symmetric
              </label>
              <label className="check">
                <input type="checkbox" checked={t.external_only} onChange={(e) => set("custom_types", form.custom_types.map((x, j) => (j === i ? { ...x, external_only: e.target.checked } : x)))} />
                external only (registry)
              </label>
              <button className="btn sm ghost" onClick={() => set("custom_types", form.custom_types.filter((_, j) => j !== i))}>
                Remove
              </button>
            </div>
          ))}
          <div>
            <button className="btn sm" onClick={() => set("custom_types", [...form.custom_types, { id: "", label: "", inverse: "", symmetric: false, description: "", external_only: false }])}>
              Add type
            </button>
          </div>
        </div>
      </Panel>
      <Panel title="Audit trail" flush>
        {!q.data?.viewer.can.settings || audit.isError ? (
          <div className="hint" style={{ padding: 10 }}>
            Visible to the settings role only.
          </div>
        ) : (
          <div className="table-wrap" style={{ maxHeight: 420 }}>
            <table className="table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Who</th>
                  <th>Action</th>
                  <th>Target</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {audit.data?.map((a) => (
                  <tr key={a.id}>
                    <td className="muted nowrap">{dateTime(a.at)}</td>
                    <td>
                      {a.actor} <Pill>{a.actor_role}</Pill>
                    </td>
                    <td>{a.action.replace(/_/g, " ")}</td>
                    <td className="muted">{a.target_type ? `${a.target_type} ${a.target_id ?? ""}` : ""}</td>
                    <td className="small mono" style={{ whiteSpace: "normal", maxWidth: 420 }}>
                      {Object.keys(a.detail).length ? JSON.stringify(a.detail) : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
