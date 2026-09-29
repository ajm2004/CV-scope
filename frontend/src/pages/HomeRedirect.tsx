import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router";
import { api } from "../api/client";
import { ErrorNotice } from "../components/ui";

export default function HomeRedirect() {
  const q = useQuery({ queryKey: ["system-status"], queryFn: api.system.status });
  if (q.isError) return <ErrorNotice error={q.error} />;
  if (!q.data) return <div className="hint">Connecting to the API…</div>;
  return <Navigate to={q.data.setup_completed ? "/projects" : "/setup"} replace />;
}
