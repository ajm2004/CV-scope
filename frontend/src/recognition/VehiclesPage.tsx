import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { ParsedPlate, RecognitionVehicle, VehicleInput } from "../api/types";
import { ConfirmButton, ErrorNotice, Field, KV, Modal, Notice, Panel, Pill } from "../components/ui";
import { roleAtLeast } from "../lib/recognitionToken";
import { usePrincipal, useRecognitionStatus } from "./hooks";
import RecognitionGate from "./RecognitionGate";

const TYPES = ["", "car", "van", "truck", "bus", "motorcycle", "other"];

type Draft = { plate: string; country: string; region: string; vehicle_type: string; description: string; owner_ref: string; groups: string; notes: string };
const EMPTY: Draft = { plate: "", country: "", region: "", vehicle_type: "", description: "", owner_ref: "", groups: "", notes: "" };

function toInput(d: Draft): VehicleInput {
  return { plate: d.plate, country: d.country, region: d.region, vehicle_type: d.vehicle_type, description: d.description, owner_ref: d.owner_ref, groups: d.groups.split(",").map((g) => g.trim()).filter(Boolean), notes: d.notes };
}

function VehicleForm({ value, onChange }: { value: Draft; onChange: (d: Draft) => void }) {
  return (
    <div className="form-grid">
      <Field label="Plate" help="Letters and digits; spaces and dashes are removed.">
        <input type="text" value={value.plate} onChange={(e) => onChange({ ...value, plate: e.target.value.toUpperCase() })} placeholder="ABC12345" />
      </Field>
      <Field label="Country (ISO code)">
        <input type="text" value={value.country} onChange={(e) => onChange({ ...value, country: e.target.value.toUpperCase() })} placeholder="AE, GB, DE, US…" />
      </Field>
      <Field label="Region / emirate / state">
        <input type="text" value={value.region} onChange={(e) => onChange({ ...value, region: e.target.value })} />
      </Field>
      <Field label="Vehicle type">
        <select value={value.vehicle_type} onChange={(e) => onChange({ ...value, vehicle_type: e.target.value })}>
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t || "unspecified"}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Description" help="Shown as the vehicle's label, for example Delivery Van 04.">
        <input type="text" value={value.description} onChange={(e) => onChange({ ...value, description: e.target.value })} />
      </Field>
      <Field label="Owner / reference name (optional)">
        <input type="text" value={value.owner_ref} onChange={(e) => onChange({ ...value, owner_ref: e.target.value })} />
      </Field>
      <Field label="Groups (comma separated)" help="Rules can match a group, for example Delivery Fleet.">
        <input type="text" value={value.groups} onChange={(e) => onChange({ ...value, groups: e.target.value })} />
      </Field>
      <Field label="Notes" className="span-2">
        <textarea value={value.notes} onChange={(e) => onChange({ ...value, notes: e.target.value })} />
      </Field>
    </div>
  );
}

function PlateTester() {
  const [text, setText] = useState("");
  const [result, setResult] = useState<ParsedPlate | null>(null);
  const parse = useMutation({ mutationFn: () => api.recognition.parsePlate(text), onSuccess: setResult });
  return (
    <Panel title="Test the plate format layer">
      <div className="inline-form">
        <Field label="Raw OCR text">
          <input type="text" value={text} onChange={(e) => setText(e.target.value)} placeholder="DXB 12S67" style={{ minWidth: 220 }} />
        </Field>
        <button className="btn" disabled={!text.trim() || parse.isPending} onClick={() => parse.mutate()}>
          Normalise
        </button>
      </div>
      {parse.isError && <ErrorNotice error={parse.error} />}
      {result && (
        <KV
          items={[
            ["Normalized", <span className="mono">{result.normalized || "–"}</span>],
            ["Valid", result.valid ? <Pill tone="ok">yes</Pill> : <Pill tone="warn">no format matched</Pill>],
            ["Format", result.format_name ?? "–"],
            ["Country / region", `${result.country ?? "–"} / ${result.region ?? "–"}`],
            ["Fields", Object.entries(result.fields).map(([k, v]) => `${k}=${v}`).join(", ") || "–"],
            ["Confusable substitutions", String(result.substitutions)],
            ["Formats tried", (result.formats_tried ?? []).join(", ")],
          ]}
        />
      )}
      <div className="hint" style={{ marginTop: 6 }}>Formats are configured under Recognition → Settings (plate formats). Custom formats go in data/recognition/plate_formats.json.</div>
    </Panel>
  );
}

export default function VehiclesPage() {
  const qc = useQueryClient();
  const me = usePrincipal();
  const status = useRecognitionStatus();
  const canEdit = roleAtLeast(me.data?.role, "operator") && !!status.data && (status.data.modules.plate.state === "licensed" || status.data.modules.plate.state === "disabled");
  const isAdmin = roleAtLeast(me.data?.role, "admin");
  const vehicles = useQuery({ queryKey: ["recognition-vehicles"], queryFn: api.recognition.vehicles, enabled: !!me.data });
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [editing, setEditing] = useState<RecognitionVehicle | null>(null);
  const [editDraft, setEditDraft] = useState<Draft>(EMPTY);
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["recognition-vehicles"] });
    qc.invalidateQueries({ queryKey: ["recognition-vehicle-groups"] });
  };
  const create = useMutation({
    mutationFn: () => api.recognition.createVehicle(toInput(draft)),
    onSuccess: () => {
      setDraft(EMPTY);
      invalidate();
    },
  });
  const update = useMutation({
    mutationFn: () => api.recognition.updateVehicle(editing!.id, toInput(editDraft)),
    onSuccess: () => {
      setEditing(null);
      invalidate();
    },
  });
  const toggle = useMutation({ mutationFn: (v: RecognitionVehicle) => api.recognition.updateVehicle(v.id, { active: !v.active }), onSuccess: invalidate });
  const remove = useMutation({ mutationFn: (id: string) => api.recognition.deleteVehicle(id), onSuccess: invalidate });
  return (
    <RecognitionGate title="Vehicles" sub="Registered vehicles are matched by their normalized plate. Registration is optional: plates are read either way, and unregistered reads are kept only if the deployment policy allows it.">
      {status.data && status.data.modules.plate.licensed && !status.data.modules.plate.models_ready && (
        <Notice tone="warn">
          The plate models are not installed. Install the plate detector and OCR model on the <Link to="/models">Models</Link> page.
        </Notice>
      )}
      {canEdit && (
        <Panel title="Register a vehicle">
          <VehicleForm value={draft} onChange={setDraft} />
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn primary" disabled={draft.plate.trim().length < 2 || create.isPending} onClick={() => create.mutate()}>
              Register
            </button>
          </div>
          {create.isError && <ErrorNotice error={create.error} />}
        </Panel>
      )}
      <Panel title={`Registered vehicles${vehicles.data ? ` (${vehicles.data.length})` : ""}`} flush>
        {vehicles.isError && <ErrorNotice error={vehicles.error} />}
        {vehicles.data && vehicles.data.length === 0 && <div className="empty">No vehicles registered.</div>}
        {vehicles.data && vehicles.data.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Plate</th>
                  <th>Country / region</th>
                  <th>Type</th>
                  <th>Description</th>
                  <th>Owner / reference</th>
                  <th>Groups</th>
                  <th>Active</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {vehicles.data.map((v) => (
                  <tr key={v.id}>
                    <td className="mono">{v.plate}</td>
                    <td className="muted">{[v.country, v.region].filter(Boolean).join(" / ") || "–"}</td>
                    <td>{v.vehicle_type || "–"}</td>
                    <td>{v.description || "–"}</td>
                    <td className="muted">{v.owner_ref || "–"}</td>
                    <td className="small">{v.groups.join(", ") || "–"}</td>
                    <td>{v.active ? <Pill tone="ok">active</Pill> : <Pill tone="warn">disabled</Pill>}</td>
                    <td className="row" style={{ gap: 4 }}>
                      {canEdit && (
                        <>
                          <button className="btn sm" onClick={() => { setEditing(v); setEditDraft({ plate: v.plate, country: v.country, region: v.region, vehicle_type: v.vehicle_type, description: v.description, owner_ref: v.owner_ref, groups: v.groups.join(", "), notes: v.notes }); }}>
                            Edit
                          </button>
                          <button className="btn sm ghost" onClick={() => toggle.mutate(v)}>
                            {v.active ? "Disable" : "Enable"}
                          </button>
                        </>
                      )}
                      {isAdmin && <ConfirmButton label="Delete" confirm="Delete?" onConfirm={() => remove.mutate(v.id)} className="btn sm ghost" />}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <PlateTester />
      {editing && (
        <Modal
          title={`Edit ${editing.plate}`}
          onClose={() => setEditing(null)}
          width={760}
          footer={
            <>
              <button className="btn" onClick={() => setEditing(null)}>
                Cancel
              </button>
              <button className="btn primary" disabled={update.isPending} onClick={() => update.mutate()}>
                Save
              </button>
            </>
          }
        >
          <VehicleForm value={editDraft} onChange={setEditDraft} />
          {update.isError && <ErrorNotice error={update.error} />}
        </Modal>
      )}
    </RecognitionGate>
  );
}
