import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { RecognitionSettingDefinition, RecognitionStatus } from "../api/types";
import { ConfirmButton, ErrorNotice, Field, KV, Notice, Panel, Pill } from "../components/ui";
import { dateTime } from "../lib/format";
import { MODULE_STATE_LABEL, moduleStateTone, ROLE_LABEL, roleAtLeast, useRecognitionAuth } from "../lib/recognitionToken";
import { usePrincipal, useRecognitionStatus } from "./hooks";
import RecognitionGate, { TokenEntry } from "./RecognitionGate";

const SECTIONS: { id: string; label: string }[] = [
  { id: "face", label: "Face recognition" },
  { id: "plate", label: "Plate recognition" },
  { id: "rules", label: "Rules" },
  { id: "retention", label: "Retention" },
  { id: "privacy", label: "Privacy" },
];

function ModuleCards({ status }: { status: RecognitionStatus }) {
  return (
    <div className="grid-2">
      {(["face", "plate"] as const).map((m) => {
        const st = status.modules[m];
        return (
          <Panel key={m} title={st.label}>
            <KV
              items={[
                ["Status", <Pill tone={moduleStateTone(st.state)} dot>{MODULE_STATE_LABEL[st.state]}</Pill>],
                ["Reason", st.reason],
                ["Models", st.models_ready ? <Pill tone="ok">installed</Pill> : <span><Pill tone="warn">not installed</Pill> <Link to="/models">Models page</Link></span>],
              ]}
            />
          </Panel>
        );
      })}
    </div>
  );
}

function LicensePanel({ status, isAdmin }: { status: RecognitionStatus; isAdmin: boolean }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [key, setKey] = useState("");
  const [keyName, setKeyName] = useState("vendor");
  const refresh = () => qc.invalidateQueries({ queryKey: ["recognition-status"] });
  const install = useMutation({ mutationFn: () => api.recognition.installLicense(text), onSuccess: () => { setText(""); refresh(); } });
  const remove = useMutation({ mutationFn: api.recognition.removeLicense, onSuccess: refresh });
  const trust = useMutation({ mutationFn: () => api.recognition.addTrustedKey(key.trim(), keyName), onSuccess: () => { setKey(""); refresh(); } });
  const lic = status.license.license;
  return (
    <Panel title="Licence">
      <KV
        items={[
          ["State", <Pill tone={moduleStateTone(lic.state)} dot>{MODULE_STATE_LABEL[lic.state] ?? lic.state}</Pill>],
          ["Detail", lic.reason],
          ["Licensee", lic.licensee ?? "–"],
          ["Issuer", lic.issuer ?? "–"],
          ["Licence id", lic.license_id ?? "–"],
          ["Issued / expires", lic.issued_at ? `${lic.issued_at} → ${lic.expires_at ?? "perpetual"}${lic.days_left != null ? ` (${lic.days_left} days left)` : ""}` : "–"],
          ["Modules", (lic.modules ?? []).join(", ") || "–"],
          ["Maximum cameras", lic.max_cameras != null ? String(lic.max_cameras) : "unlimited"],
          ["Bound to this machine", lic.hardware_bound ? "yes" : "no"],
          ["Trusted issuer keys", String(status.license.trusted_issuers)],
          ["This machine's id", <code className="mono">{status.license.hardware_id}</code>],
        ]}
      />
      <Notice>
        Licences are issued after a request has been reviewed for a legitimate use case. Send the licensee name (and this machine's id for a machine-bound licence) to the vendor; the vendor signs a licence file with its private issuer key and this installation checks the signature offline against the trusted issuer keys. An open-source build trusts no issuer, so the modules stay locked; a vendor build sets <code>PATHSCOPE_RECOGNITION_ISSUER_KEYS</code>.
      </Notice>
      {isAdmin && (
        <div className="stack" style={{ marginTop: 10 }}>
          <Field label="Install a licence file (paste its JSON)">
            <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder='{"version": 1, "payload": {...}, "signature": "...", "issuer_public_key": "..."}' />
          </Field>
          <div className="row wrap">
            <button className="btn primary" disabled={!text.trim() || install.isPending} onClick={() => install.mutate()}>
              Validate and install
            </button>
            {status.license.license_installed && <ConfirmButton label="Remove licence" confirm="Lock the modules?" onConfirm={() => remove.mutate()} />}
          </div>
          {install.isError && <ErrorNotice error={install.error} />}
          {install.isSuccess && <Notice tone="ok">Licence installed: {install.data.verdict.licensee}, modules {(install.data.verdict.modules ?? []).join(", ")}.</Notice>}
          <div className="inline-form">
            <Field label="Trust an issuer public key (64 hex characters)" help="Only needed when the key is not configured through the environment.">
              <input type="text" value={key} onChange={(e) => setKey(e.target.value)} style={{ minWidth: 420 }} className="mono" />
            </Field>
            <Field label="Name">
              <input type="text" value={keyName} onChange={(e) => setKeyName(e.target.value)} />
            </Field>
            <button className="btn" disabled={key.trim().length !== 64 || trust.isPending} onClick={() => trust.mutate()}>
              Trust key
            </button>
          </div>
          {trust.isError && <ErrorNotice error={trust.error} />}
        </div>
      )}
    </Panel>
  );
}

function TokensPanel() {
  const qc = useQueryClient();
  const tokens = useQuery({ queryKey: ["recognition-tokens"], queryFn: api.recognition.tokens });
  const [draft, setDraft] = useState({ name: "", role: "viewer", expires_in_days: "" });
  const [issued, setIssued] = useState<{ name: string; token: string } | null>(null);
  const create = useMutation({
    mutationFn: () => api.recognition.createToken({ name: draft.name, role: draft.role, expires_in_days: draft.expires_in_days ? Number(draft.expires_in_days) : null }),
    onSuccess: (r) => {
      setIssued({ name: r.name, token: r.token });
      setDraft({ name: "", role: "viewer", expires_in_days: "" });
      qc.invalidateQueries({ queryKey: ["recognition-tokens"] });
    },
  });
  const revoke = useMutation({ mutationFn: (id: string) => api.recognition.revokeToken(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["recognition-tokens"] }) });
  return (
    <Panel title="Access tokens">
      <div className="inline-form">
        <Field label="Name">
          <input type="text" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="Reception desk" />
        </Field>
        <Field label="Role">
          <select value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value })}>
            <option value="viewer">Viewer: read events, registries, diagnostics</option>
            <option value="operator">Operator: enroll and register</option>
            <option value="admin">Administrator: everything</option>
          </select>
        </Field>
        <Field label="Expires in (days)">
          <input type="number" min={1} value={draft.expires_in_days} onChange={(e) => setDraft({ ...draft, expires_in_days: e.target.value })} placeholder="never" style={{ width: 90 }} />
        </Field>
        <button className="btn primary" disabled={!draft.name.trim() || create.isPending} onClick={() => create.mutate()}>
          Create token
        </button>
      </div>
      {create.isError && <ErrorNotice error={create.error} />}
      {issued && (
        <Notice tone="ok">
          Token for {issued.name}, shown once: <code className="mono">{issued.token}</code>
        </Notice>
      )}
      {revoke.isError && <ErrorNotice error={revoke.error} />}
      <table className="table" style={{ marginTop: 8 }}>
        <thead>
          <tr>
            <th>Name</th>
            <th>Role</th>
            <th>Active</th>
            <th>Created</th>
            <th>Last used</th>
            <th>Expires</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {tokens.data?.map((t) => (
            <tr key={t.id}>
              <td>{t.name}</td>
              <td>{ROLE_LABEL[t.role] ?? t.role}</td>
              <td>{t.active ? <Pill tone="ok">active</Pill> : <Pill>revoked</Pill>}</td>
              <td className="muted">{dateTime(t.created_at)}</td>
              <td className="muted">{t.last_used_at ? dateTime(t.last_used_at) : "never"}</td>
              <td className="muted">{t.expires_at ? dateTime(t.expires_at) : "never"}</td>
              <td>{t.active && <ConfirmButton label="Revoke" confirm="Revoke?" onConfirm={() => revoke.mutate(t.id)} className="btn sm ghost" />}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function SettingInput({ def, value, onChange, faceStacks }: { def: RecognitionSettingDefinition; value: unknown; onChange: (v: unknown) => void; faceStacks: Record<string, string> }) {
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
            {def.key === "recognition.face.stack" ? faceStacks[o] ?? o : o}
          </option>
        ))}
      </select>
    );
  if (def.kind === "int" || def.kind === "float")
    return (
      <input
        type="number"
        step={def.kind === "float" ? "0.01" : "1"}
        min={def.min}
        max={def.max}
        value={value === null || value === undefined ? "" : Number(value)}
        placeholder={def.nullable ? "model default" : undefined}
        onChange={(e) => onChange(e.target.value === "" ? (def.nullable ? null : 0) : def.kind === "int" ? parseInt(e.target.value, 10) : parseFloat(e.target.value))}
      />
    );
  return <input type="text" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />;
}

function SettingsPanel({ isAdmin }: { isAdmin: boolean }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["recognition-settings"], queryFn: api.recognition.settings });
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [advanced, setAdvanced] = useState(false);
  useEffect(() => {
    if (q.data) setValues(q.data.values);
  }, [q.data]);
  const save = useMutation({
    mutationFn: () => api.recognition.updateSettings(values),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["recognition-settings"] });
      qc.invalidateQueries({ queryKey: ["recognition-status"] });
      qc.invalidateQueries({ queryKey: ["recommendations"] });
    },
  });
  if (q.isError) return <ErrorNotice error={q.error} />;
  if (!q.data) return <div className="hint">Loading settings…</div>;
  const dirty = JSON.stringify(values) !== JSON.stringify(q.data.values);
  const defs = q.data.definitions.filter((d) => advanced || !d.advanced);
  return (
    <Panel
      title="Recognition settings"
      actions={
        <span className="row">
          <label className="check">
            <input type="checkbox" checked={advanced} onChange={(e) => setAdvanced(e.target.checked)} />
            Advanced settings (thresholds)
          </label>
          {isAdmin && (
            <button className="btn primary sm" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
              Save changes
            </button>
          )}
        </span>
      }
    >
      {!isAdmin && <Notice>Only administrators can change these settings.</Notice>}
      {save.isError && <ErrorNotice error={save.error} />}
      {save.isSuccess && save.data.changed.length > 0 && <Notice tone="ok">Saved: {save.data.changed.join(", ")}. Runs started from now on use the new values.</Notice>}
      <div className="stack">
        {SECTIONS.map((s) => {
          const items = defs.filter((d) => d.section === s.id);
          if (!items.length) return null;
          return (
            <div key={s.id}>
              <div className="section-title">{s.label}</div>
              <div className="form-grid">
                {items.map((d) => (
                  <div key={d.key} className="field">
                    {d.kind !== "bool" && <label>{d.label}</label>}
                    <SettingInput def={d} value={values[d.key]} onChange={(v) => setValues({ ...values, [d.key]: v })} faceStacks={q.data!.face_stacks} />
                    {d.help && <span className="help">{d.help}</span>}
                    {d.key === "recognition.plate.formats" && <span className="help">Available: {q.data!.plate_formats.map((f) => `${f.id} (${f.name})`).join(", ")}.</span>}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

function BenchmarkPanel() {
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const run = useMutation({ mutationFn: (m: "face" | "plate") => api.recognition.benchmark(m), onSuccess: setResult });
  return (
    <Panel title="Benchmark the recognition models on this machine">
      <div className="row wrap">
        <button className="btn" disabled={run.isPending} onClick={() => run.mutate("face")}>
          Benchmark face models
        </button>
        <button className="btn" disabled={run.isPending} onClick={() => run.mutate("plate")}>
          Benchmark plate models
        </button>
        <span className="hint">Synthetic inputs, timing only: detector on a head or vehicle crop, embedding or OCR on a crop.</span>
      </div>
      {run.isError && <ErrorNotice error={run.error} />}
      {result && <pre className="mono small" style={{ whiteSpace: "pre-wrap", marginTop: 8 }}>{JSON.stringify(result, null, 1)}</pre>}
    </Panel>
  );
}

function AuditPanel() {
  const q = useQuery({ queryKey: ["recognition-audit"], queryFn: () => api.recognition.audit(200) });
  return (
    <Panel title="Audit trail" flush>
      {q.isError && <ErrorNotice error={q.error} />}
      {q.data && q.data.length === 0 && <div className="empty">Nothing recorded yet.</div>}
      {q.data && q.data.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>When</th>
                <th>Who</th>
                <th>Action</th>
                <th>Target</th>
                <th className="wrap">Detail</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((a) => (
                <tr key={a.id}>
                  <td className="muted">{dateTime(a.at)}</td>
                  <td>
                    {a.actor} <span className="hint">{a.actor_role}</span>
                  </td>
                  <td>{a.action.replace(/_/g, " ")}</td>
                  <td className="small muted">{a.target_type ? `${a.target_type} ${a.target_id ?? ""}` : "–"}</td>
                  <td className="wrap mono small">{JSON.stringify(a.detail)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

export default function RecognitionSettingsPage() {
  const status = useRecognitionStatus();
  const me = usePrincipal();
  const token = useRecognitionAuth((s) => s.token);
  const isAdmin = !!me.data && roleAtLeast(me.data.role, "admin");
  return (
    <RecognitionGate title="Recognition settings" sub="Licence, access, thresholds, retention and audit of the licensed face and plate recognition modules." requireToken={false}>
      {status.data && <ModuleCards status={status.data} />}
      {status.data && <LicensePanel status={status.data} isAdmin={isAdmin} />}
      {!token && <TokenEntry status={status.data} />}
      {token && me.isError && <Notice tone="err">This recognition token is not accepted (revoked, expired or mistyped). Sign out above and enter another one.</Notice>}
      {token && me.data && (
        <>
          {isAdmin && <TokensPanel />}
          <SettingsPanel isAdmin={isAdmin} />
          {isAdmin && <BenchmarkPanel />}
          {isAdmin && <AuditPanel />}
        </>
      )}
    </RecognitionGate>
  );
}
