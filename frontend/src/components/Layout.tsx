import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet, useLocation } from "react-router";
import { api } from "../api/client";
import GuidePanel from "../guides/GuidePanel";
import { useGuideState } from "../guides/state";
import { Pill } from "./ui";

const WORKSPACE = [
  { to: "/projects", label: "Projects" },
  { to: "/live", label: "Live" },
  { to: "/experiments", label: "Experiments" },
  { to: "/data", label: "Data" },
  { to: "/analysis", label: "Analysis" },
  { to: "/anomalies", label: "Anomalies", end: true },
  { to: "/cameras", label: "Cameras" },
];
// Relationship & Event Correlation Engine
const RELATIONSHIPS = [
  { to: "/relationships", label: "Explorer", end: true },
  { to: "/relationships/graph", label: "Graph" },
  { to: "/relationships/journeys", label: "Journeys" },
  { to: "/relationships/timeline", label: "Timeline" },
  { to: "/relationships/search", label: "Search" },
  { to: "/relationships/rules", label: "Rules" },
  { to: "/relationships/settings", label: "Settings" },
];
// Location Engine: site plans and camera topology
const LOCATIONS = [
  { to: "/locations/site", label: "Site view" },
  { to: "/locations/topology", label: "Topology" },
];
// Licensed recognition modules: the section stays folded to one entry until a licence is installed.
const RECOGNITION = [
  { to: "/recognition/people", label: "People" },
  { to: "/recognition/vehicles", label: "Vehicles" },
  { to: "/recognition/events", label: "Recognition events" },
  { to: "/recognition/test", label: "Test recognition" },
  { to: "/recognition/settings", label: "Settings" },
];
const RECOGNITION_LOCKED = [{ to: "/recognition/settings", label: "Recognition" }];
const ADMIN = [
  { to: "/anomalies/assistant", label: "Anomaly Assistant" },
  { to: "/models", label: "Models" },
  { to: "/hardware", label: "Hardware" },
  { to: "/settings", label: "Settings" },
];
const HELP = [{ to: "/guides", label: "Guides" }];

function titleFor(path: string): string {
  if (path.startsWith("/scene")) return "Scene Builder";
  if (path.startsWith("/review")) return "Video review";
  if (path.startsWith("/setup")) return "First-run setup";
  if (path.startsWith("/anomalies/assistant")) return "Anomaly Assistant";
  if (path.startsWith("/relationships")) {
    const r = [...RELATIONSHIPS].reverse().find((n) => path.startsWith(n.to));
    return r ? `Relationships · ${r.label}` : "Relationships";
  }
  if (path.startsWith("/locations")) {
    const r = LOCATIONS.find((n) => path.startsWith(n.to));
    return r ? `Locations · ${r.label}` : "Locations";
  }
  if (path.startsWith("/recognition")) {
    const r = RECOGNITION.find((n) => path.startsWith(n.to));
    return r ? `Recognition · ${r.label}` : "Recognition";
  }
  const all = [...WORKSPACE, ...ADMIN, ...HELP].find((n) => path.startsWith(n.to));
  return all?.label ?? "";
}

export function StatusPill() {
  const q = useQuery({ queryKey: ["system-status"], queryFn: api.system.status, refetchInterval: 10_000, retry: 0 });
  if (q.isError) return <Pill tone="err" dot>API unreachable</Pill>;
  if (!q.data) return <Pill dot>Connecting</Pill>;
  const n = q.data.active_runs.length;
  return (
    <span className="row" style={{ gap: 6 }}>
      <Pill tone="ok" dot>
        API connected
      </Pill>
      {n > 0 && <Pill tone="accent">{n} run{n > 1 ? "s" : ""} active</Pill>}
      <span className="hint">v{q.data.version}</span>
    </span>
  );
}

export default function Layout() {
  const loc = useLocation();
  const flush = loc.pathname.startsWith("/scene");
  const guideOpen = useGuideState((s) => s.panel !== null);
  const guideCollapsed = useGuideState((s) => s.collapsed);
  const recognition = useQuery({ queryKey: ["recognition-status"], queryFn: api.recognition.status, refetchInterval: 60_000, retry: 0 });
  const unlocked = !!recognition.data && (recognition.data.any_licensed || recognition.data.license.license_installed);
  const recognitionNav = unlocked ? RECOGNITION : RECOGNITION_LOCKED;
  return (
    <div className={`app ${guideOpen ? (guideCollapsed ? "with-guide-strip" : "with-guide") : ""}`}>
      <header className="topbar">
        <NavLink to="/projects" className="brand" style={{ textDecoration: "none" }}>
          CV-Scope<span>fixed-camera movement research</span>
        </NavLink>
        <span className="topbar-title">{titleFor(loc.pathname)}</span>
        <span className="grow" />
        <StatusPill />
      </header>
      <nav className="nav">
        <div className="nav-group">Workspace</div>
        {WORKSPACE.map((n) => (
          <NavLink key={n.to} to={n.to} end={"end" in n && n.end} className={({ isActive }) => (isActive ? "active" : "")}>
            {n.label}
          </NavLink>
        ))}
        <div className="nav-group" style={{ marginTop: 10 }}>
          Relationships
        </div>
        {RELATIONSHIPS.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? "active" : "")}>
            {n.label}
          </NavLink>
        ))}
        <div className="nav-group" style={{ marginTop: 10 }}>
          Locations
        </div>
        {LOCATIONS.map((n) => (
          <NavLink key={n.to} to={n.to} className={({ isActive }) => (isActive ? "active" : "")}>
            {n.label}
          </NavLink>
        ))}
        <div className="nav-group" style={{ marginTop: 10 }}>
          Recognition{!unlocked && <span className="hint"> · locked</span>}
        </div>
        {recognitionNav.map((n) => (
          <NavLink key={n.to} to={n.to} className={({ isActive }) => (isActive ? "active" : "")}>
            {n.label}
          </NavLink>
        ))}
        <div className="nav-group" style={{ marginTop: 10 }}>
          Administration
        </div>
        {ADMIN.map((n) => (
          <NavLink key={n.to} to={n.to} className={({ isActive }) => (isActive ? "active" : "")}>
            {n.label}
          </NavLink>
        ))}
        <div className="nav-group" style={{ marginTop: 10 }}>
          Help
        </div>
        {HELP.map((n) => (
          <NavLink key={n.to} to={n.to} className={({ isActive }) => (isActive ? "active" : "")}>
            {n.label}
          </NavLink>
        ))}
      </nav>
      <main className={`main ${flush ? "flush" : ""}`}>
        <Outlet />
      </main>
      <GuidePanel />
    </div>
  );
}
