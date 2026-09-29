import { useQuery } from "@tanstack/react-query";
import { Link, NavLink, useParams } from "react-router";
import { api } from "../api/client";
import { Empty, ErrorNotice, Panel, Pill } from "../components/ui";
import { dateTime, RUN_STATE_CLASS } from "../lib/format";
import AnalysisPage from "./AnalysisPage";
import DataPage from "./DataPage";
import ExperimentsPage from "./ExperimentsPage";

export default function ProjectPage() {
  const { projectId, tab = "overview" } = useParams();
  const pid = Number(projectId);
  const project = useQuery({ queryKey: ["project", pid], queryFn: () => api.projects.get(pid) });
  const cameras = useQuery({ queryKey: ["cameras", pid], queryFn: () => api.cameras.list(pid) });
  const experiments = useQuery({ queryKey: ["experiments", pid], queryFn: () => api.experiments.list({ project_id: pid }) });
  if (project.isError) return <ErrorNotice error={project.error} />;
  if (!project.data) return <div className="hint">Loading project…</div>;
  const p = project.data;
  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "scene", label: "Scene" },
    { id: "experiments", label: "Experiments" },
    { id: "data", label: "Data" },
    { id: "analysis", label: "Analysis" },
  ];
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>{p.name}</h1>
          <div className="sub">{p.description || "No description."}</div>
        </div>
        <Link className="btn" to="/projects">
          All projects
        </Link>
      </div>
      <div className="tabs">
        {tabs.map((t) => (
          <NavLink key={t.id} to={`/projects/${pid}/${t.id}`} className={tab === t.id ? "active" : ""}>
            {t.label}
          </NavLink>
        ))}
      </div>

      {tab === "overview" && (
        <div className="grid-2">
          <Panel title="Cameras" actions={<Link className="btn sm" to="/cameras">Manage cameras</Link>} flush>
            {cameras.data && cameras.data.length === 0 && (
              <Empty action={<Link className="btn primary" to="/cameras">Add a camera</Link>}>No cameras in this project yet.</Empty>
            )}
            {cameras.data && cameras.data.length > 0 && (
              <table className="table">
                <thead>
                  <tr>
                    <th>Camera</th>
                    <th>Source</th>
                    <th>Scene</th>
                    <th>State</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {cameras.data.map((c) => (
                    <tr key={c.id}>
                      <td>{c.name}</td>
                      <td className="muted">{c.source_type === "file" ? c.video?.filename ?? "video" : c.source_type.toUpperCase()}</td>
                      <td>{c.latest_scene_version ? `v${c.latest_scene_version}` : <span className="muted">not drawn</span>}</td>
                      <td>{c.active_run_id ? <Pill tone="ok" dot>running</Pill> : <Pill>idle</Pill>}</td>
                      <td>
                        <Link className="btn sm" to={`/scene/${c.id}`}>
                          Scene builder
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
          <Panel title="Experiments" actions={<Link className="btn sm" to={`/projects/${pid}/experiments`}>All experiments</Link>} flush>
            {experiments.data && experiments.data.length === 0 && <Empty>No experiments yet. Draw a scene first, then create an experiment from the Scene Builder or the Experiments tab.</Empty>}
            {experiments.data && experiments.data.length > 0 && (
              <table className="table">
                <thead>
                  <tr>
                    <th>Experiment</th>
                    <th>Camera</th>
                    <th className="num">Runs</th>
                    <th>Last run</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {experiments.data.map((e) => (
                    <tr key={e.id}>
                      <td>
                        <Link to={`/experiments/${e.id}`}>{e.name}</Link>
                      </td>
                      <td className="muted">{e.camera_name ?? "–"}</td>
                      <td className="num">{e.run_count}</td>
                      <td>{e.last_run ? <Pill tone={(RUN_STATE_CLASS[e.last_run.status] ?? "") as "" | "ok" | "warn" | "err" | "accent"}>{e.last_run.status}</Pill> : <span className="muted">never</span>}</td>
                      <td className="muted">{dateTime(e.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
        </div>
      )}
      {tab === "scene" && (
        <Panel title="Choose a camera to edit its scene">
          {cameras.data?.length ? (
            <ul className="list-plain">
              {cameras.data.map((c) => (
                <li key={c.id} className="row">
                  <span className="grow">
                    {c.name} <span className="muted">— {c.latest_scene_version ? `scene v${c.latest_scene_version}` : "no scene yet"}</span>
                  </span>
                  <Link className="btn sm primary" to={`/scene/${c.id}`}>
                    Open
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <Empty action={<Link className="btn primary" to="/cameras">Add a camera</Link>}>Add a camera to this project first.</Empty>
          )}
        </Panel>
      )}
      {tab === "experiments" && <ExperimentsPage projectId={pid} embedded />}
      {tab === "data" && <DataPage projectId={pid} embedded />}
      {tab === "analysis" && <AnalysisPage projectId={pid} embedded />}
    </div>
  );
}
