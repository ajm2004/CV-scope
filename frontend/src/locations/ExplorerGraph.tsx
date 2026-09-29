/* The explorer's graph tab: the interactive graph around the open entity
 * (click a node to open it, an edge for its evidence). The full workbench
 * (filters, time, paths, expand/collapse) is one click away. */

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link } from "react-router";
import { Empty, ErrorNotice } from "../components/ui";
import { useRecognitionAuth } from "../lib/recognitionToken";
import type { Filters } from "../relationships/api";
import { loc, type VEdge } from "./api";
import GraphCanvas, { GraphLegend } from "./GraphCanvas";
import "./locations.css";
import { useGraph } from "./useGraph";

export default function ExplorerGraph({ entityKey, depth, filters, onOpen, onEdge }: { entityKey: string; depth: number; filters: Filters; onOpen: (key: string) => void; onEdge: (e: VEdge) => void }) {
  const token = useRecognitionAuth((s) => s.token);
  const q = useQuery({ queryKey: ["explorer-visual", entityKey, depth, filters, token], queryFn: () => loc.visual({ ...filters, key: entityKey, depth, project: true, context: true }), retry: 0 });
  const g = useGraph();
  const { reset } = g;
  useEffect(() => {
    if (q.data) reset(q.data);
  }, [q.data, reset]);
  const params = new URLSearchParams({ key: entityKey, depth: String(depth) });
  return (
    <div className="stack" style={{ gap: 6 }}>
      {q.isError && <ErrorNotice error={q.error} />}
      {q.data && q.data.edges.length === 0 && <Empty>No relationships match these filters.</Empty>}
      {g.model && g.model.graph.edges.length > 0 && (
        <GraphCanvas nodes={g.model.graph.nodes} edges={g.model.graph.edges} positions={g.positions} center={g.model.graph.center} height={480} onMoveNode={g.move}
          onSelectNode={(k) => { const n = g.model?.graph.nodes.find((x) => x.node === k); if (n?.expandable && k !== g.model?.graph.center && n.key) onOpen(n.key); }}
          onSelectEdge={(e) => e && e.ids.length > 0 && onEdge(e)} />
      )}
      <GraphLegend />
      <div className="hint">
        Click a node to open it, an edge to see why it exists. <Link to={`/relationships/graph?${params}`}>Open in the graph workbench</Link> for time replay, filters, paths and expanding nodes in place.
      </div>
    </div>
  );
}
