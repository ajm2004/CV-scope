import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { api } from "../api/client";
import { ConfirmButton, Empty, ErrorNotice, Field, Panel } from "../components/ui";
import { dateTime } from "../lib/format";

export default function ProjectsPage() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["projects"], queryFn: api.projects.list });
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const create = useMutation({
    mutationFn: () => api.projects.create({ name: name.trim(), description }),
    onSuccess: (p) => {
      setName("");
      setDescription("");
      qc.invalidateQueries({ queryKey: ["projects"] });
      nav(`/projects/${p.id}`);
    },
  });
  const remove = useMutation({ mutationFn: (id: number) => api.projects.remove(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }) });

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Projects</h1>
          <div className="sub">A project groups sites, cameras and experiments for one study or one monitored location.</div>
        </div>
      </div>
      <div className="grid-2" style={{ gridTemplateColumns: "minmax(0, 2fr) minmax(280px, 1fr)" }}>
        <Panel title="All projects" flush>
          {q.isError && <ErrorNotice error={q.error} />}
          {q.data && q.data.length === 0 && (
            <Empty>
              No projects yet. Create the first one on the right, or run the first-run setup from <Link to="/setup">Setup</Link>. New to CV-Scope? The <Link to="/guides">guides</Link> start with a short tour.
            </Empty>
          )}
          {q.data && q.data.length > 0 && (
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Description</th>
                  <th className="num">Cameras</th>
                  <th className="num">Experiments</th>
                  <th>Updated</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {q.data.map((p) => (
                  <tr key={p.id} className="clickable" onClick={() => nav(`/projects/${p.id}`)}>
                    <td>
                      <Link to={`/projects/${p.id}`}>{p.name}</Link>
                    </td>
                    <td className="muted wrap">{p.description}</td>
                    <td className="num">{p.camera_count}</td>
                    <td className="num">{p.experiment_count}</td>
                    <td className="muted">{dateTime(p.updated_at)}</td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <ConfirmButton label="Delete" confirm="Delete project and its data?" onConfirm={() => remove.mutate(p.id)} className="btn sm ghost" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
        <Panel title="New project">
          <form
            className="stack"
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim()) create.mutate();
            }}
          >
            <Field label="Name">
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Pedestrian route behaviour study" required />
            </Field>
            <Field label="Description" help="What is being observed and why. Shown on the project overview.">
              <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Route choice at the main entrance with and without directional signage." />
            </Field>
            {create.isError && <ErrorNotice error={create.error} />}
            <div>
              <button className="btn primary" type="submit" disabled={create.isPending || !name.trim()}>
                Create project
              </button>
            </div>
          </form>
        </Panel>
      </div>
    </div>
  );
}
