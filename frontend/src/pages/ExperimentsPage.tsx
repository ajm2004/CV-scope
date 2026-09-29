import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import { api } from "../api/client";
import { ClassPicker, Empty, ErrorNotice, Field, Modal, Panel, Pill } from "../components/ui";
import { CLASS_OPTIONS, dateTime, RUN_STATE_CLASS, SOURCE_LABEL } from "../lib/format";

export function NewExperimentModal({ projectId, cameraId, onClose, onCreated }: { projectId?: number; cameraId?: number; onClose: () => void; onCreated: (id: number) => void }) {
  const qc = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects.list });
  const cameras = useQuery({ queryKey: ["cameras", "all"], queryFn: () => api.cameras.list() });
  const [pid, setPid] = useState<number | "">(projectId ?? "");
  const [cid, setCid] = useState<number | "">(cameraId ?? "");
  const [moveCamera, setMoveCamera] = useState(true);
  const [name, setName] = useState("");
  const [classes, setClasses] = useState<string[]>(["person"]);
  const [notes, setNotes] = useState("");
  // Start in the most recently used project.
  useEffect(() => {
    if (pid === "" && projects.data?.length) setPid(projects.data[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects.data]);
  const all = cameras.data ?? [];
  const own = all.filter((c) => pid !== "" && c.project_id === pid);
  const others = all.filter((c) => pid === "" || c.project_id !== pid);
  const projectName = (id: number) => projects.data?.find((p) => p.id === id)?.name ?? `project ${id}`;
  const chosen = all.find((c) => c.id === cid);
  const foreign = !!chosen && pid !== "" && chosen.project_id !== pid;
  const create = useMutation({
    mutationFn: async () => {
      if (foreign && moveCamera && chosen) await api.cameras.update(chosen.id, { project_id: Number(pid) });
      return api.experiments.create({ project_id: Number(pid), camera_id: cid === "" ? null : Number(cid), name: name.trim(), object_classes: classes, condition_notes: notes });
    },
    onSuccess: (e) => {
      qc.invalidateQueries({ queryKey: ["cameras"] });
      qc.invalidateQueries({ queryKey: ["camera"] });
      onCreated(e.id);
    },
  });
  return (
    <Modal
      title="New experiment"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" disabled={!name.trim() || pid === "" || create.isPending} onClick={() => create.mutate()}>
            Create experiment
          </button>
        </>
      }
    >
      <div className="stack">
        <Field label="Name">
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Morning route A/B comparison" autoFocus />
        </Field>
        <div className="form-grid">
          <Field label="Project">
            <select value={pid} onChange={(e) => setPid(e.target.value ? Number(e.target.value) : "")}>
              <option value="">Select…</option>
              {projects.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Camera">
            <select value={cid} onChange={(e) => setCid(e.target.value ? Number(e.target.value) : "")}>
              <option value="">Choose later</option>
              {own.length > 0 && (
                <optgroup label="In this project">
                  {own.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name} ({SOURCE_LABEL[c.source_type] ?? c.source_type})
                    </option>
                  ))}
                </optgroup>
              )}
              {others.length > 0 && (
                <optgroup label={pid === "" ? "Cameras" : "Other projects"}>
                  {others.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}, in {projectName(c.project_id)}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          </Field>
        </div>
        {cameras.isSuccess && all.length === 0 && (
          <div className="hint">
            There are no cameras yet. <Link to="/cameras">Add one on the Cameras page</Link>, or choose it later.
          </div>
        )}
        {foreign && chosen && (
          <label className="check">
            <input type="checkbox" checked={moveCamera} onChange={(e) => setMoveCamera(e.target.checked)} />
            Move {chosen.name} from “{projectName(chosen.project_id)}” to this project
          </label>
        )}
        <Field label="Objects to track">
          <ClassPicker value={classes} onChange={setClasses} options={CLASS_OPTIONS} />
        </Field>
        <Field label="Condition notes" help="What is different in this experiment (signage, lighting, time of day…).">
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        {create.isError && <ErrorNotice error={create.error} />}
      </div>
    </Modal>
  );
}

export default function ExperimentsPage({ projectId, embedded = false }: { projectId?: number; embedded?: boolean }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["experiments", projectId ?? "all"], queryFn: () => api.experiments.list(projectId ? { project_id: projectId } : {}), refetchInterval: 5000 });
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects.list });
  const [creating, setCreating] = useState(false);
  const start = useMutation({ mutationFn: (id: number) => api.experiments.start(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["experiments"] }) });
  const stop = useMutation({ mutationFn: (runId: number) => api.runs.stop(runId), onSuccess: () => qc.invalidateQueries({ queryKey: ["experiments"] }) });
  const projectName = (id: number) => projects.data?.find((p) => p.id === id)?.name ?? `#${id}`;
  return (
    <div className="stack">
      {!embedded && (
        <div className="page-head">
          <div>
            <h1>Experiments</h1>
            <div className="sub">An experiment pins a camera, a scene version, the objects to track, the detector and the rules. Duplicate one to change a single condition.</div>
          </div>
          <button className="btn primary" onClick={() => setCreating(true)}>
            New experiment
          </button>
        </div>
      )}
      {embedded && (
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn primary" onClick={() => setCreating(true)}>
            New experiment
          </button>
        </div>
      )}
      {start.isError && <ErrorNotice error={start.error} />}
      <Panel title="Experiments" flush>
        {q.isError && <ErrorNotice error={q.error} />}
        {q.data && q.data.length === 0 && <Empty>No experiments yet.</Empty>}
        {q.data && q.data.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                {!projectId && <th>Project</th>}
                <th>Camera</th>
                <th>Objects</th>
                <th>Detector</th>
                <th className="num">Runs</th>
                <th>Last run</th>
                <th>Updated</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((e) => {
                const live = e.last_run && e.last_run.live && !["completed", "stopped", "failed"].includes(e.last_run.status);
                return (
                  <tr key={e.id} className="clickable" onClick={() => nav(`/experiments/${e.id}`)}>
                    <td>
                      <Link to={`/experiments/${e.id}`}>{e.name}</Link>
                      {e.tags.length > 0 && <span className="hint"> {e.tags.join(", ")}</span>}
                    </td>
                    {!projectId && <td className="muted">{projectName(e.project_id)}</td>}
                    <td>{e.camera_name ?? <span className="muted">none</span>}</td>
                    <td className="small">{e.object_classes.join(", ")}</td>
                    <td className="mono small">{e.model_id || "auto"}</td>
                    <td className="num">{e.run_count}</td>
                    <td>{e.last_run ? <Pill tone={(RUN_STATE_CLASS[e.last_run.status] ?? "") as "" | "ok" | "warn" | "err" | "accent"} dot={!!live}>{e.last_run.status}</Pill> : <span className="muted">never</span>}</td>
                    <td className="muted">{dateTime(e.updated_at)}</td>
                    <td onClick={(ev) => ev.stopPropagation()}>
                      {live ? (
                        <button className="btn sm danger" onClick={() => stop.mutate(e.last_run!.id)}>
                          Stop
                        </button>
                      ) : (
                        <button className="btn sm" disabled={!e.camera_id || start.isPending} onClick={() => start.mutate(e.id)}>
                          Start
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Panel>
      {creating && (
        <NewExperimentModal
          projectId={projectId}
          onClose={() => setCreating(false)}
          onCreated={(id) => {
            setCreating(false);
            qc.invalidateQueries({ queryKey: ["experiments"] });
            nav(`/experiments/${id}`);
          }}
        />
      )}
    </div>
  );
}
