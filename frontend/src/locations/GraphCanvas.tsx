/* Interactive node-edge graph (SVG): pan with the background, zoom with the
 * wheel, drag nodes to pin them, click to select, double-click to expand.
 *
 * Encoding (see GraphLegend):
 *   node shape  - track ○, recognized identity ◆, scene place ▭, location ▢ (double),
 *                 camera ▣, sensor △, event ⬡
 *   edge colour - observed fact, identity link, inferred by a rule, cross-camera
 *                 correlation, external registry, derived context
 *   edge line   - solid: confirmed / likely; dashed: possible; dotted: insufficient
 *   S badge     - supported by a sensor observation
 * Nothing moves on its own: layouts are computed once and only change when the
 * graph changes or a node is dragged. */

import { useEffect, useMemo, useRef, useState } from "react";
import type { EdgeNature, VEdge, VNode } from "./api";
import type { Pos } from "./graphModel";

export const NATURE_LABEL: Record<EdgeNature, string> = {
  observed: "Observed fact",
  identity: "Identity (recognition)",
  inferred: "Inferred by a rule",
  cross_camera: "Across cameras",
  external: "External registry",
  context: "Location context",
};

const NATURE_CLASS: Record<EdgeNature, string> = {
  observed: "g-observed",
  identity: "g-identity",
  inferred: "g-inferred",
  cross_camera: "g-cross",
  external: "g-external",
  context: "g-context",
};

function dash(state: string, nature: EdgeNature): string | undefined {
  if (nature === "context") return "1 4";
  if (state === "possible") return "7 4";
  if (state === "insufficient") return "2 4";
  return undefined;
}

export function NodeShape({ n, x, y, r = 9, emphasis = false }: { n: Pick<VNode, "klass" | "redacted">; x: number; y: number; r?: number; emphasis?: boolean }) {
  const cls = `g-node g-node-${n.klass}${emphasis ? " g-emph" : ""}${n.redacted ? " g-redacted" : ""}`;
  switch (n.klass) {
    case "identity":
      return <rect className={cls} x={x - r * 0.8} y={y - r * 0.8} width={r * 1.6} height={r * 1.6} transform={`rotate(45 ${x} ${y})`} />;
    case "place":
      return <rect className={cls} x={x - r * 1.2} y={y - r * 0.75} width={r * 2.4} height={r * 1.5} rx={1.5} />;
    case "location":
      return (
        <g className={cls}>
          <rect x={x - r * 1.35} y={y - r * 0.95} width={r * 2.7} height={r * 1.9} rx={3} />
          <rect x={x - r * 1.0} y={y - r * 0.6} width={r * 2.0} height={r * 1.2} rx={2} className="g-inner" />
        </g>
      );
    case "camera":
      return (
        <g className={cls}>
          <rect x={x - r} y={y - r * 0.75} width={r * 1.55} height={r * 1.5} rx={1.5} />
          <path d={`M ${x + r * 0.55} ${y} L ${x + r * 1.15} ${y - r * 0.55} L ${x + r * 1.15} ${y + r * 0.55} Z`} />
        </g>
      );
    case "sensor":
      return <path className={cls} d={`M ${x} ${y - r} L ${x + r} ${y + r * 0.8} L ${x - r} ${y + r * 0.8} Z`} />;
    case "event": {
      const pts = Array.from({ length: 6 }, (_, i) => {
        const a = (Math.PI / 3) * i;
        return `${x + r * Math.cos(a)},${y + r * Math.sin(a)}`;
      }).join(" ");
      return <polygon className={cls} points={pts} />;
    }
    case "track":
      return <circle className={cls} cx={x} cy={y} r={r * 0.85} />;
    default:
      return <circle className={cls} cx={x} cy={y} r={r * 0.6} />;
  }
}

interface View {
  x: number;
  y: number;
  k: number;
}

export interface GraphCanvasProps {
  nodes: VNode[];
  edges: VEdge[];
  positions: Record<string, Pos>;
  center?: string | null;
  selectedNode?: string | null;
  selectedEdge?: string | null;
  highlightNodes?: Set<string>;
  highlightEdges?: Set<string>;
  height?: number;
  onSelectNode?: (key: string | null) => void;
  onSelectEdge?: (edge: VEdge | null) => void;
  onMoveNode?: (key: string, pos: Pos) => void;
  onExpandNode?: (key: string) => void;
  labels?: "auto" | "all" | "none";
}

export default function GraphCanvas({ nodes, edges, positions, center, selectedNode, selectedEdge, highlightNodes, highlightEdges, height = 560, onSelectNode, onSelectEdge, onMoveNode, onExpandNode, labels = "auto" }: GraphCanvasProps) {
  const svg = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ w: 900, h: height });
  const [view, setView] = useState<View>({ x: 0, y: 0, k: 1 });
  const [drag, setDrag] = useState<{ key: string; pos: Pos } | null>(null);
  const pan = useRef<{ sx: number; sy: number; vx: number; vy: number; moved: boolean } | null>(null);
  const fitted = useRef<string>("");

  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth || 900, h: el.clientHeight || height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, [height]);

  const pos = (k: string): Pos | undefined => (drag && drag.key === k ? drag.pos : positions[k]);

  const fit = () => {
    const pts = nodes.map((n) => positions[n.node]).filter(Boolean);
    if (!pts.length) return;
    const xs = pts.map((p) => p.x);
    const ys = pts.map((p) => p.y);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const k = Math.min(2, Math.max(0.15, Math.min((size.w - 80) / Math.max(1, x1 - x0), (size.h - 80) / Math.max(1, y1 - y0))));
    setView({ k, x: size.w / 2 - ((x0 + x1) / 2) * k, y: size.h / 2 - ((y0 + y1) / 2) * k });
  };

  // fit once per new set of nodes (not on every filter change)
  const sig = useMemo(() => nodes.map((n) => n.node).sort().join("|"), [nodes]);
  useEffect(() => {
    if (fitted.current === "" || Math.abs(sig.split("|").length - fitted.current.split("|").length) > 0) {
      if (fitted.current === "") fit();
      fitted.current = sig;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig, size.w, size.h]);

  const toGraph = (clientX: number, clientY: number): Pos => {
    const r = svg.current!.getBoundingClientRect();
    return { x: (clientX - r.left - view.x) / view.k, y: (clientY - r.top - view.y) / view.k };
  };

  const onWheel = (e: React.WheelEvent) => {
    const r = svg.current!.getBoundingClientRect();
    const mx = e.clientX - r.left;
    const my = e.clientY - r.top;
    const k = Math.min(4, Math.max(0.1, view.k * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
    setView({ k, x: mx - ((mx - view.x) / view.k) * k, y: my - ((my - view.y) / view.k) * k });
  };

  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    const stop = (e: WheelEvent) => e.preventDefault();
    el.addEventListener("wheel", stop, { passive: false });
    return () => el.removeEventListener("wheel", stop);
  }, []);

  const byId = useMemo(() => new Map(nodes.map((n) => [n.node, n])), [nodes]);
  const pairIndex = useMemo(() => {
    const seen = new Map<string, number>();
    const out = new Map<string, number>();
    for (const e of edges) {
      const k = [e.source, e.target].sort().join("|");
      const i = seen.get(k) ?? 0;
      seen.set(k, i + 1);
      out.set(e.id, i);
    }
    return out;
  }, [edges]);

  const showLabels = labels === "all" || (labels === "auto" && view.k >= 0.75);
  const dim = (highlightNodes && highlightNodes.size > 0) || (highlightEdges && highlightEdges.size > 0);

  return (
    <div className="g-wrap" style={{ height }}>
      <div className="g-tools">
        <button className="btn sm" onClick={() => setView({ ...view, k: Math.min(4, view.k * 1.25) })} aria-label="Zoom in">
          +
        </button>
        <button className="btn sm" onClick={() => setView({ ...view, k: Math.max(0.1, view.k / 1.25) })} aria-label="Zoom out">
          −
        </button>
        <button className="btn sm" onClick={fit}>
          Fit
        </button>
      </div>
      <svg
        ref={svg}
        className="g-svg"
        role="img"
        aria-label="Relationship graph"
        onWheel={onWheel}
        onPointerDown={(e) => {
          if ((e.target as Element).closest(".g-hit")) return;
          pan.current = { sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y, moved: false };
          (e.currentTarget as Element).setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => {
          if (drag) {
            setDrag({ key: drag.key, pos: toGraph(e.clientX, e.clientY) });
            return;
          }
          const p = pan.current;
          if (!p) return;
          const dx = e.clientX - p.sx;
          const dy = e.clientY - p.sy;
          if (Math.abs(dx) + Math.abs(dy) > 3) p.moved = true;
          setView({ ...view, x: p.vx + dx, y: p.vy + dy });
        }}
        onPointerUp={() => {
          if (drag) {
            onMoveNode?.(drag.key, drag.pos);
            setDrag(null);
            return;
          }
          const p = pan.current;
          pan.current = null;
          if (p && !p.moved) {
            onSelectNode?.(null);
            onSelectEdge?.(null);
          }
        }}
      >
        <defs>
          {(["observed", "identity", "inferred", "cross_camera", "external", "context"] as EdgeNature[]).map((n) => (
            <marker key={n} id={`g-arrow-${n}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" className={`g-arrow ${NATURE_CLASS[n]}`} />
            </marker>
          ))}
        </defs>
        <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
          {edges.map((e) => {
            const a = pos(e.source);
            const b = pos(e.target);
            if (!a || !b) return null;
            const idx = pairIndex.get(e.id) ?? 0;
            const dx = b.x - a.x;
            const dy = b.y - a.y;
            const len = Math.hypot(dx, dy) || 1;
            const nx = -dy / len;
            const ny = dx / len;
            const bend = idx === 0 ? 0 : (idx % 2 ? 1 : -1) * Math.ceil(idx / 2) * 18;
            const mx = (a.x + b.x) / 2 + nx * bend;
            const my = (a.y + b.y) / 2 + ny * bend;
            const trim = 13 / len;
            const sx = a.x + dx * trim;
            const sy = a.y + dy * trim;
            const tx = b.x - dx * trim;
            const ty = b.y - dy * trim;
            const hl = highlightEdges?.has(e.id);
            const sel = selectedEdge === e.id;
            const faded = dim && !hl && !sel;
            const d = bend ? `M ${sx} ${sy} Q ${mx} ${my} ${tx} ${ty}` : `M ${sx} ${sy} L ${tx} ${ty}`;
            const opacity = faded ? 0.15 : e.nature === "context" ? 0.55 : 0.45 + 0.55 * e.best_confidence;
            return (
              <g key={e.id} className={`g-edge ${NATURE_CLASS[e.nature]}${sel ? " g-sel" : ""}${hl ? " g-hl" : ""}`} style={{ opacity }}>
                <path d={d} className="g-hit" onClick={(ev) => { ev.stopPropagation(); onSelectEdge?.(e); }}>
                  <title>{`${e.type}${e.count > 1 ? ` ×${e.count}` : ""} · ${NATURE_LABEL[e.nature]} · ${e.state} ${Math.round(e.best_confidence * 100)}%${e.sensor ? " · sensor-supported" : ""}`}</title>
                </path>
                <path d={d} className="g-line" strokeDasharray={dash(e.state, e.nature)} strokeWidth={(sel || hl ? 2.6 : e.state === "confirmed" ? 1.9 : 1.3) / Math.sqrt(view.k)}
                  markerEnd={e.nature === "context" ? undefined : `url(#g-arrow-${e.nature})`} />
                {e.sensor && <text x={mx} y={my + 11} textAnchor="middle" className="g-badge">S</text>}
                {(showLabels || sel || hl) && e.nature !== "context" && (
                  <text x={mx} y={my - 4} textAnchor="middle" className="g-edge-label">
                    {e.type}
                    {e.count > 1 ? ` ×${e.count}` : ""}
                  </text>
                )}
              </g>
            );
          })}
          {nodes.map((n) => {
            const p = pos(n.node);
            if (!p) return null;
            const isCenter = n.node === center;
            const sel = selectedNode === n.node;
            const hl = highlightNodes?.has(n.node);
            const faded = dim && !hl && !sel && !isCenter;
            return (
              <g
                key={n.node}
                className={`g-hit g-nodewrap${sel ? " g-sel" : ""}${hl ? " g-hl" : ""}`}
                style={{ opacity: faded ? 0.25 : 1, cursor: "pointer" }}
                onPointerDown={(e) => {
                  e.stopPropagation();
                  (e.currentTarget as Element).setPointerCapture(e.pointerId);
                  setDrag({ key: n.node, pos: p });
                }}
                onPointerUp={(e) => {
                  e.stopPropagation();
                  const moved = drag && Math.hypot(drag.pos.x - p.x, drag.pos.y - p.y) > 2;
                  if (drag && moved) onMoveNode?.(drag.key, drag.pos);
                  setDrag(null);
                  if (!moved) onSelectNode?.(n.node);
                }}
                onDoubleClick={(e) => {
                  e.stopPropagation();
                  if (n.expandable) onExpandNode?.(n.node);
                }}
              >
                <title>{`${n.label} (${n.type_label})${n.redacted ? " — identity hidden" : ""}${n.location ? `\n${n.location.path}` : ""}`}</title>
                {(sel || hl || isCenter) && <circle cx={p.x} cy={p.y} r={isCenter ? 19 : 16} className={isCenter ? "g-ring-center" : "g-ring"} />}
                <NodeShape n={n} x={p.x} y={p.y} r={isCenter ? 11 : 9} emphasis={isCenter} />
                <text x={p.x} y={p.y + (isCenter ? 26 : 22)} textAnchor="middle" className={`g-node-label${isCenter ? " center" : ""}`}>
                  {n.label.length > 28 ? `${n.label.slice(0, 27)}…` : n.label}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}

export function GraphLegend() {
  const nodeKinds: [VNode["klass"], string][] = [
    ["track", "Tracked object"],
    ["identity", "Recognized identity"],
    ["place", "Scene place"],
    ["location", "Location"],
    ["camera", "Camera"],
    ["sensor", "Sensor"],
    ["event", "Event"],
  ];
  return (
    <div className="g-legend">
      <div className="g-legend-row">
        {nodeKinds.map(([k, label]) => (
          <span key={k} className="g-legend-item">
            <svg width="26" height="20" viewBox="-13 -10 26 20" aria-hidden>
              <NodeShape n={{ klass: k, redacted: false }} x={0} y={0} r={7} />
            </svg>
            {label}
          </span>
        ))}
      </div>
      <div className="g-legend-row">
        {(Object.keys(NATURE_LABEL) as EdgeNature[]).map((k) => (
          <span key={k} className="g-legend-item">
            <svg width="30" height="10" aria-hidden>
              <line x1="2" y1="5" x2="28" y2="5" className={`g-line ${NATURE_CLASS[k]}`} strokeWidth={2} strokeDasharray={k === "context" ? "1 4" : undefined} />
            </svg>
            {NATURE_LABEL[k]}
          </span>
        ))}
        <span className="g-legend-item hint">solid: confirmed or likely · dashed: possible · dotted: insufficient · S: sensor-supported</span>
      </div>
    </div>
  );
}
