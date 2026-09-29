import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { EnrollmentAnalysis, EnrollmentResult, RecognitionPerson } from "../api/types";
import { ConfirmButton, ErrorNotice, Field, KV, Modal, Notice, Panel, Pill, Progress, Tabs } from "../components/ui";
import { dateTime, num } from "../lib/format";
import { roleAtLeast } from "../lib/recognitionToken";
import EnrollmentLooks, { lookLabel } from "./EnrollmentLooks";
import GuidedEnrollment from "./GuidedEnrollment";
import { ENROLLMENT_VIEWS, usePrincipal, useRecognitionStatus } from "./hooks";
import RecognitionGate from "./RecognitionGate";

function statusPill(p: RecognitionPerson) {
  const tone = p.enrollment_status === "enrolled" ? "ok" : p.enrollment_status === "insufficient" ? "warn" : "";
  return <Pill tone={tone}>{p.enrollment_status}</Pill>;
}

function QualityBar({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span className="muted">–</span>;
  return (
    <span className="row" style={{ gap: 6, minWidth: 120 }}>
      <span style={{ flex: 1 }}>
        <Progress value={value} />
      </span>
      <span className="num small">{num(value * 100, 0)}%</span>
    </span>
  );
}

function AnalysisView({ a }: { a: EnrollmentAnalysis }) {
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="row wrap">
        {a.face_found ? <Pill tone="ok">face found</Pill> : <Pill tone="warn">no face found</Pill>}
        {a.accepted ? <Pill tone="ok">acceptable for enrollment</Pill> : <Pill tone="warn">not accepted</Pill>}
        {a.quality && (
          <span className="small muted">
            quality {num(a.quality.score, 2)} · size {num(a.quality.size_px, 0)} px · sharpness {num(a.quality.blur, 2)} · exposure {num(a.quality.exposure, 2)}
            {a.quality.yaw !== null ? ` · yaw ${a.quality.yaw >= 0 ? "+" : ""}${num(a.quality.yaw, 2)}` : ""}
          </span>
        )}
      </div>
      {a.guidance.length > 0 && (
        <Notice tone="warn">
          {a.guidance.map((g) => (
            <div key={g}>{g}</div>
          ))}
        </Notice>
      )}
    </div>
  );
}

function EnrollmentPanel({ person, canEdit, onChanged }: { person: RecognitionPerson; canEdit: boolean; onChanged: (p: RecognitionPerson) => void }) {
  const [view, setView] = useState("front");
  // Which appearance the next pictures belong to ("" = the first enrollment).
  const [look, setLook] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [cameraId, setCameraId] = useState<number | "">("");
  const [analysis, setAnalysis] = useState<EnrollmentAnalysis | null>(null);
  const [result, setResult] = useState<EnrollmentResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const cameras = useQuery({ queryKey: ["cameras", "all"], queryFn: () => api.cameras.list() });
  const viewInfo = ENROLLMENT_VIEWS.find((v) => v.id === view)!;
  const analyzeFile = useMutation({ mutationFn: () => api.recognition.analyzeImage(person.id, file!, view, look), onSuccess: setAnalysis, onError: setError });
  const addFile = useMutation({
    mutationFn: () => api.recognition.addImage(person.id, file!, view, look),
    onSuccess: (r) => {
      setAnalysis(r.analysis);
      setFile(null);
      onChanged(r.person);
    },
    onError: setError,
  });
  const capture = useMutation({
    mutationFn: (store: boolean) => api.recognition.capture(person.id, { camera_id: Number(cameraId), view, store, variant: look }),
    onSuccess: (r) => {
      setAnalysis(r.analysis);
      if (r.person) onChanged(r.person);
    },
    onError: setError,
  });
  const finalize = useMutation({
    mutationFn: () => api.recognition.finalize(person.id),
    onSuccess: (r) => {
      setResult(r.result);
      onChanged(r.person);
    },
    onError: setError,
  });
  const removeImage = useMutation({ mutationFn: (imageId: string) => api.recognition.deleteImage(person.id, imageId), onSuccess: onChanged, onError: setError });
  const busy = analyzeFile.isPending || addFile.isPending || capture.isPending;
  // Views already captured for the look being worked on.
  const views = new Set<string>((person.images ?? []).filter((im) => (im.variant ?? "") === look).map((im) => im.view));
  const liveCameras = (cameras.data ?? []).filter((c) => c.source_type !== "file");
  const [mode, setMode] = useState<string>("guided");
  useEffect(() => {
    if (cameras.isSuccess && liveCameras.length === 0) setMode("manual");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameras.isSuccess, liveCameras.length]);
  return (
    <div className="stack">
      <div className="section-title">Enrollment: several views of the same person</div>
      <EnrollmentLooks person={person} look={look} onChange={setLook} canEdit={canEdit} onChanged={onChanged} />
      {canEdit && <Tabs tabs={[{ id: "guided", label: "Guided (live camera)" }, { id: "manual", label: "Single pictures" }]} active={mode} onChange={setMode} />}
      {canEdit && mode === "guided" && <GuidedEnrollment person={person} cameras={cameras.data ?? []} onChanged={onChanged} look={look} />}
      {(!canEdit || mode === "manual") && (
        <>
          <div className="row wrap" style={{ gap: 6 }}>
            {ENROLLMENT_VIEWS.map((v) => (
              <button key={v.id} className={`btn sm ${view === v.id ? "active" : ""}`} onClick={() => { setView(v.id); setAnalysis(null); }}>
                {v.label}
                {views.has(v.id) && " ✓"}
              </button>
            ))}
          </div>
          <div className="hint">{viewInfo.instruction}</div>
        </>
      )}
      {canEdit && mode === "manual" && (
        <div className="grid-2">
          <Panel title="From a camera">
            <div className="inline-form">
              <Field label="Camera">
                <select value={cameraId} onChange={(e) => setCameraId(e.target.value ? Number(e.target.value) : "")}>
                  <option value="">Select…</option>
                  {cameras.data?.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </Field>
              <button className="btn" disabled={cameraId === "" || busy} onClick={() => capture.mutate(false)}>
                Capture and check
              </button>
              <button className="btn primary" disabled={cameraId === "" || busy} onClick={() => capture.mutate(true)}>
                Capture and add
              </button>
            </div>
            <div className="hint" style={{ marginTop: 6 }}>One frame is taken on the server; nothing is stored unless it is added. The picture is checked for size, sharpness, lighting, pose and obstruction, and the guidance tells the person what to change.</div>
          </Panel>
          <Panel title="From a file">
            <div className="inline-form">
              <Field label="Image (JPEG or PNG)">
                <input type="file" accept="image/*" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setAnalysis(null); }} />
              </Field>
              <button className="btn" disabled={!file || busy} onClick={() => analyzeFile.mutate()}>
                Check
              </button>
              <button className="btn primary" disabled={!file || busy} onClick={() => addFile.mutate()}>
                Add to enrollment
              </button>
            </div>
          </Panel>
        </div>
      )}
      {error ? <ErrorNotice error={error} /> : null}
      {analysis && <AnalysisView a={analysis} />}
      <div className="section-title">Enrollment images ({person.images?.length ?? 0})</div>
      {(!person.images || person.images.length === 0) && <div className="hint">No images yet. A front view is required; left and right angles make recognition more robust.</div>}
      <div className="row wrap" style={{ gap: 10, alignItems: "flex-start" }}>
        {person.images?.map((im) => (
          <div key={im.id} style={{ width: 150 }}>
            <div className="camera-view" style={{ height: 110 }}>
              <img src={api.recognition.imageUrl(person.id, im.id)} alt={im.view} style={{ maxHeight: 110 }} />
            </div>
            <div className="row" style={{ justifyContent: "space-between", marginTop: 4 }}>
              <span className="small">
                {ENROLLMENT_VIEWS.find((v) => v.id === im.view)?.label ?? im.view}
                {!im.biometric && <span className="hint"> (reference)</span>}
                {im.variant ? <span className="hint"> · {im.variant}</span> : null}
              </span>
              {canEdit && (
                <button className="btn ghost sm" onClick={() => removeImage.mutate(im.id)}>
                  ×
                </button>
              )}
            </div>
            <QualityBar value={im.quality} />
          </div>
        ))}
      </div>
      {canEdit && (
        <div className="row">
          <button className="btn primary" disabled={finalize.isPending || person.n_templates === 0} onClick={() => finalize.mutate()}>
            Finalize enrollment
          </button>
          <span className="hint">Computes the enrollment quality: views covered, image quality and how consistent the images are with each other. Poor enrollments are refused.</span>
        </div>
      )}
      {(result || person.enrollment_summary?.templates !== undefined) && (
        <Panel title="Enrollment quality">
          {(() => {
            const s = result ?? (person.enrollment_summary as EnrollmentResult);
            const st = result?.status ?? person.enrollment_status;
            return (
              <KV
                items={[
                  ["Status", <Pill tone={st === "enrolled" ? "ok" : st === "insufficient" ? "warn" : ""}>{st}</Pill>],
                  ["Quality", <QualityBar value={result?.quality ?? person.enrollment_quality} />],
                  ["Views", (s.views ?? []).join(", ") || "–"],
                  ["Templates", String(s.templates ?? person.n_templates)],
                  ["Mean image quality", num(s.mean_quality, 2)],
                  ["Consistency between images", s.consistency != null ? num(s.consistency, 2) : "n/a (one image)"],
                  [
                    "Looks",
                    (s.looks ?? []).length
                      ? (s.looks ?? []).map((l) => (
                          <div key={l.name}>
                            {lookLabel(l.name)}: {l.templates} templates, views {l.views.join(", ") || "–"}
                            {l.link_to_first != null ? `, matches the first enrollment at ${num(l.link_to_first, 2)}` : ""}
                          </div>
                        ))
                      : "one",
                  ],
                  ["Problems", (s.problems ?? []).length ? (s.problems ?? []).map((p) => <div key={p}>{p}</div>) : "none"],
                  ["Model", s.model_version || person.model_version || "–"],
                ]}
              />
            );
          })()}
        </Panel>
      )}
    </div>
  );
}

function PersonModal({ personId, onClose }: { personId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const me = usePrincipal();
  const status = useRecognitionStatus();
  const q = useQuery({ queryKey: ["recognition-person", personId], queryFn: () => api.recognition.person(personId) });
  const [form, setForm] = useState<{ display_name: string; reference_id: string; notes: string; valid_from: string; valid_until: string } | null>(null);
  const canEdit = roleAtLeast(me.data?.role, "operator") && !!status.data && (status.data.modules.face.state === "licensed" || status.data.modules.face.state === "disabled");
  const isAdmin = roleAtLeast(me.data?.role, "admin");
  const refresh = (p?: RecognitionPerson) => {
    if (p) qc.setQueryData(["recognition-person", personId], p);
    qc.invalidateQueries({ queryKey: ["recognition-person", personId] });
    qc.invalidateQueries({ queryKey: ["recognition-people"] });
  };
  const save = useMutation({
    mutationFn: () => api.recognition.updatePerson(personId, { display_name: form!.display_name, reference_id: form!.reference_id || null, notes: form!.notes, valid_from: form!.valid_from || null, valid_until: form!.valid_until || null, clear_validity: !form!.valid_from && !form!.valid_until }),
    onSuccess: (p) => {
      setForm(null);
      refresh(p);
    },
  });
  const toggle = useMutation({ mutationFn: (active: boolean) => (active ? api.recognition.enablePerson(personId) : api.recognition.disablePerson(personId)), onSuccess: () => refresh() });
  const reenroll = useMutation({ mutationFn: () => api.recognition.reenroll(personId), onSuccess: (p) => refresh(p) });
  const remove = useMutation({
    mutationFn: () => api.recognition.deletePerson(personId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["recognition-people"] });
      onClose();
    },
  });
  if (q.isError) return <Modal title="Person" onClose={onClose}><ErrorNotice error={q.error} /></Modal>;
  if (!q.data) return <Modal title="Person" onClose={onClose}><div className="hint">Loading…</div></Modal>;
  const p = q.data;
  const f = form ?? { display_name: p.display_name, reference_id: p.reference_id ?? "", notes: p.notes, valid_from: p.valid_from ?? "", valid_until: p.valid_until ?? "" };
  return (
    <Modal title={`${p.display_name}${p.reference_id ? ` (${p.reference_id})` : ""}`} onClose={onClose} width={960}>
      <div className="stack">
        <div className="row wrap">
          {statusPill(p)}
          {!p.active && <Pill tone="warn">disabled</Pill>}
          <span className="hint">Internal id {p.id} · created {dateTime(p.created_at)} · enrolled {p.enrolled_at ? dateTime(p.enrolled_at) : "–"}</span>
        </div>
        <div className="form-grid">
          <Field label="Display name">
            <input type="text" value={f.display_name} disabled={!canEdit} onChange={(e) => setForm({ ...f, display_name: e.target.value })} />
          </Field>
          <Field label="Reference id" help="Badge number, employee id or study code.">
            <input type="text" value={f.reference_id} disabled={!canEdit} onChange={(e) => setForm({ ...f, reference_id: e.target.value })} />
          </Field>
          <Field label="Valid from" help="Optional validity period; outside it the identity is never matched.">
            <input type="date" value={f.valid_from} disabled={!canEdit} onChange={(e) => setForm({ ...f, valid_from: e.target.value })} />
          </Field>
          <Field label="Valid until">
            <input type="date" value={f.valid_until} disabled={!canEdit} onChange={(e) => setForm({ ...f, valid_until: e.target.value })} />
          </Field>
          <Field label="Notes" className="span-2">
            <textarea value={f.notes} disabled={!canEdit} onChange={(e) => setForm({ ...f, notes: e.target.value })} />
          </Field>
        </div>
        {canEdit && (
          <div className="row wrap">
            <button className="btn primary" disabled={!form || save.isPending} onClick={() => save.mutate()}>
              Save profile
            </button>
            <button className="btn" onClick={() => toggle.mutate(!p.active)}>
              {p.active ? "Disable" : "Enable"}
            </button>
            <ConfirmButton label="Re-enroll" confirm="Delete all templates and images?" onConfirm={() => reenroll.mutate()} className="btn" />
            {isAdmin && <ConfirmButton label="Delete profile" confirm="Delete profile, templates and images?" onConfirm={() => remove.mutate()} className="btn danger" />}
          </div>
        )}
        {save.isError && <ErrorNotice error={save.error} />}
        {remove.isError && <ErrorNotice error={remove.error} />}
        {!canEdit && <Notice>Enrollment needs the operator role and a licensed face module.</Notice>}
        <EnrollmentPanel person={p} canEdit={canEdit} onChanged={refresh} />
      </div>
    </Modal>
  );
}

export default function PeoplePage() {
  const qc = useQueryClient();
  const me = usePrincipal();
  const status = useRecognitionStatus();
  const [open, setOpen] = useState<string | null>(null);
  const [draft, setDraft] = useState({ display_name: "", reference_id: "", notes: "" });
  const canEdit = roleAtLeast(me.data?.role, "operator") && !!status.data && (status.data.modules.face.state === "licensed" || status.data.modules.face.state === "disabled");
  const people = useQuery({ queryKey: ["recognition-people"], queryFn: api.recognition.people, enabled: !!me.data });
  const create = useMutation({
    mutationFn: () => api.recognition.createPerson({ display_name: draft.display_name, reference_id: draft.reference_id || null, notes: draft.notes }),
    onSuccess: (p) => {
      setDraft({ display_name: "", reference_id: "", notes: "" });
      qc.invalidateQueries({ queryKey: ["recognition-people"] });
      setOpen(p.id);
    },
  });
  return (
    <RecognitionGate title="People" sub="Identities enrolled on purpose for this installation. Unknown people stay anonymous tracks; no attribute other than the enrolled identity is ever inferred.">
      {status.data && !status.data.modules.face.models_ready && status.data.modules.face.licensed && (
        <Notice tone="warn">
          The face models are not installed, so enrollment and recognition cannot run. Install the face detector and embedding model on the <Link to="/models">Models</Link> page.
        </Notice>
      )}
      {canEdit && (
        <Panel title="Add a person">
          <div className="inline-form">
            <Field label="Display name">
              <input type="text" value={draft.display_name} onChange={(e) => setDraft({ ...draft, display_name: e.target.value })} placeholder="Research Subject 001 / Employee 001" style={{ minWidth: 260 }} />
            </Field>
            <Field label="Reference id (optional)">
              <input type="text" value={draft.reference_id} onChange={(e) => setDraft({ ...draft, reference_id: e.target.value })} />
            </Field>
            <button className="btn primary" disabled={!draft.display_name.trim() || create.isPending} onClick={() => create.mutate()}>
              Create profile
            </button>
          </div>
          {create.isError && <ErrorNotice error={create.error} />}
        </Panel>
      )}
      <Panel title={`Enrolled people${people.data ? ` (${people.data.length})` : ""}`} flush>
        {people.isError && <ErrorNotice error={people.error} />}
        {people.data && people.data.length === 0 && <div className="empty">No profiles yet.</div>}
        {people.data && people.data.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Reference</th>
                  <th>Enrollment</th>
                  <th>Quality</th>
                  <th>Views</th>
                  <th className="num">Templates</th>
                  <th>Active</th>
                  <th>Validity</th>
                  <th>Enrolled</th>
                </tr>
              </thead>
              <tbody>
                {people.data.map((p) => (
                  <tr key={p.id} className="clickable" onClick={() => setOpen(p.id)}>
                    <td>{p.display_name}</td>
                    <td className="muted">{p.reference_id ?? "–"}</td>
                    <td>{statusPill(p)}</td>
                    <td><QualityBar value={p.enrollment_quality} /></td>
                    <td className="small muted">{p.views.join(", ") || "–"}</td>
                    <td className="num">{p.n_templates}</td>
                    <td>{p.active ? <Pill tone="ok">active</Pill> : <Pill tone="warn">disabled</Pill>}</td>
                    <td className="small muted">{p.valid_from || p.valid_until ? `${p.valid_from ?? "…"} → ${p.valid_until ?? "…"}` : "always"}</td>
                    <td className="muted">{p.enrolled_at ? dateTime(p.enrolled_at) : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      {open && <PersonModal personId={open} onClose={() => setOpen(null)} />}
    </RecognitionGate>
  );
}
