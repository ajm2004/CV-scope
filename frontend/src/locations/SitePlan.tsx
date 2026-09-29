/* A location frame drawn to scale: a floor plan picture, a schematic grid or a
 * map box, with its places, cameras (and their fields of view), sensors and
 * links. Used by the topology editor (drag to place, click two nodes to link),
 * the site view (live overlays) and journeys (the path an entity took).
 *
 * Coordinates are the frame's own (metres or plain units, y down). On a map
 * frame with a geographic box, nodes with GPS but no x/y are placed from their
 * latitude and longitude. */

import { useEffect, useMemo, useRef, useState, type ReactElement } from "react";
import { loc, type LocGraph, type LocLink, type LocNode } from "./api";

export interface PlanPathPoint {
  x: number;
  y: number;
  label: string;
  key: string;
}

export interface PlanOverlays {
  counts?: Record<number, number>; // camera id -> objects in view
  alerts?: Record<number, number>; // camera id -> recent alerts
  active?: Set<number>; // camera ids with an active run
  highlight?: Set<number>; // node ids
  lastSeen?: number | null; // node id
  path?: PlanPathPoint[];
  selectedStep?: string | null;
  onStep?: (key: string) => void;
  moves?: { from: number; to: number; flagged: boolean }[]; // node ids (recent cross-camera moves)
}

export interface SitePlanProps {
  graph: LocGraph;
  frameId: number;
  height?: number;
  selected?: number | null;
  selectedLink?: number | null;
  onSelect?: (id: number | null) => void;
  onSelectLink?: (link: LocLink) => void;
  editable?: boolean;
  onMove?: (id: number, x: number, y: number) => void;
  linkMode?: boolean;
  onLink?: (a: number, b: number) => void;
  overlays?: PlanOverlays;
}

export function nodePoint(n: LocNode, frame: LocNode): { x: number; y: number } | null {
  if (n.x != null && n.y != null) return { x: n.x, y: n.y };
  if (n.shape?.length) {
    const xs = n.shape.map((p) => p[0]);
    const ys = n.shape.map((p) => p[1]);
    return { x: xs.reduce((a, b) => a + b, 0) / xs.length, y: ys.reduce((a, b) => a + b, 0) / ys.length };
  }
  const L = frame.layout;
  const b = L?.bounds;
  if (L && b && n.lat != null && n.lon != null && b.east !== b.west && b.north !== b.south) {
    return { x: ((n.lon - b.west) / (b.east - b.west)) * L.width, y: ((b.north - n.lat) / (b.north - b.south)) * L.height };
  }
  return null;
}

/** Nodes drawn in a frame: those whose coordinate frame it is. */
export function frameNodes(graph: LocGraph, frameId: number): LocNode[] {
  return graph.nodes.filter((n) => n.frame_id === frameId);
}

function fovPath(x: number, y: number, deg: number, fov: number, r: number): string {
  const a0 = ((deg - fov / 2 - 90) * Math.PI) / 180;
  const a1 = ((deg + fov / 2 - 90) * Math.PI) / 180;
  const large = fov > 180 ? 1 : 0;
  return `M ${x} ${y} L ${x + r * Math.cos(a0)} ${y + r * Math.sin(a0)} A ${r} ${r} 0 ${large} 1 ${x + r * Math.cos(a1)} ${y + r * Math.sin(a1)} Z`;
}

export default function SitePlan({ graph, frameId, height = 520, selected, selectedLink, onSelect, onSelectLink, editable, onMove, linkMode, onLink, overlays }: SitePlanProps) {
  const frame = graph.nodes.find((n) => n.id === frameId);
  const svg = useRef<SVGSVGElement>(null);
  const L = frame?.layout;
  const W = L?.width ?? 100;
  const H = L?.height ?? 60;
  const [vb, setVb] = useState({ x: -W * 0.03, y: -H * 0.03, w: W * 1.06, h: H * 1.06 });
  const [drag, setDrag] = useState<{ id: number; x: number; y: number } | null>(null);
  const [linkFrom, setLinkFrom] = useState<number | null>(null);
  const pan = useRef<{ cx: number; cy: number; x: number; y: number; moved: boolean } | null>(null);

  useEffect(() => {
    setVb({ x: -W * 0.03, y: -H * 0.03, w: W * 1.06, h: H * 1.06 });
  }, [frameId, W, H]);
  useEffect(() => {
    if (!linkMode) setLinkFrom(null);
  }, [linkMode]);

  const nodes = useMemo(() => frameNodes(graph, frameId), [graph, frameId]);
  const pos = useMemo(() => {
    const out = new Map<number, { x: number; y: number }>();
    if (!frame) return out;
    for (const n of nodes) {
      const p = drag && drag.id === n.id ? { x: drag.x, y: drag.y } : nodePoint(n, frame);
      if (p) out.set(n.id, p);
    }
    return out;
  }, [nodes, frame, drag]);
  const links = graph.edges.filter((e) => !e.derived && pos.has(e.source) && pos.has(e.target)) as (LocLink & { derived: boolean; source: number; target: number })[];
  // Labels and markers keep their size on screen while the plan zooms (as on a
  // map): zooming into a busy building spreads its places apart instead of
  // enlarging their names.
  const fs = Math.max(vb.w, vb.h) / 70;
  const unit = L?.unit === "m" ? "m" : "";

  const toFrame = (clientX: number, clientY: number) => {
    const el = svg.current!;
    const pt = el.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const m = el.getScreenCTM();
    if (!m) return { x: 0, y: 0 };
    const p = pt.matrixTransform(m.inverse());
    return { x: p.x, y: p.y };
  };

  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    const stop = (e: WheelEvent) => e.preventDefault();
    el.addEventListener("wheel", stop, { passive: false });
    return () => el.removeEventListener("wheel", stop);
  }, []);

  if (!frame || !L) return <div className="hint">This location has no layout. Give it a layout (size and unit) to draw it.</div>;

  const clickNode = (id: number) => {
    if (linkMode) {
      if (linkFrom == null) setLinkFrom(id);
      else if (linkFrom !== id) {
        onLink?.(linkFrom, id);
        setLinkFrom(null);
      }
      return;
    }
    onSelect?.(id);
  };

  const gridStep = (() => {
    const target = Math.max(W, H) / 12;
    const pow = 10 ** Math.floor(Math.log10(target));
    return [1, 2, 5, 10].map((m) => m * pow).find((s) => s >= target) ?? target;
  })();
  const grid: ReactElement[] = [];
  if (!L.image) {
    for (let x = 0; x <= W + 1e-9; x += gridStep) grid.push(<line key={`gx${x}`} x1={x} y1={0} x2={x} y2={H} className={`plan-grid${Math.round(x / gridStep) % 5 === 0 ? " major" : ""}`} vectorEffect="non-scaling-stroke" />);
    for (let y = 0; y <= H + 1e-9; y += gridStep) grid.push(<line key={`gy${y}`} x1={0} y1={y} x2={W} y2={y} className={`plan-grid${Math.round(y / gridStep) % 5 === 0 ? " major" : ""}`} vectorEffect="non-scaling-stroke" />);
  }

  return (
    <div className="plan-wrap">
      <div className="g-tools">
        <button className="btn sm" onClick={() => setVb({ x: vb.x + vb.w * 0.1, y: vb.y + vb.h * 0.1, w: vb.w * 0.8, h: vb.h * 0.8 })} aria-label="Zoom in">
          +
        </button>
        <button className="btn sm" onClick={() => setVb({ x: vb.x - vb.w * 0.125, y: vb.y - vb.h * 0.125, w: vb.w * 1.25, h: vb.h * 1.25 })} aria-label="Zoom out">
          −
        </button>
        <button className="btn sm" onClick={() => setVb({ x: -W * 0.03, y: -H * 0.03, w: W * 1.06, h: H * 1.06 })}>
          Fit
        </button>
      </div>
      {linkMode && <div className="hint" style={{ position: "absolute", left: 8, top: 8, zIndex: 2, background: "var(--surface)", padding: "2px 6px" }}>{linkFrom == null ? "Click the first node of the link" : "Now click the second node"}</div>}
      <svg
        ref={svg}
        className="plan-svg"
        style={{ height }}
        viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={`Plan of ${frame.name}`}
        onWheel={(e) => {
          const p = toFrame(e.clientX, e.clientY);
          const f = e.deltaY < 0 ? 0.85 : 1 / 0.85;
          setVb({ x: p.x - (p.x - vb.x) * f, y: p.y - (p.y - vb.y) * f, w: vb.w * f, h: vb.h * f });
        }}
        onPointerDown={(e) => {
          if ((e.target as Element).closest(".plan-node,.plan-linkhit,.plan-stephit")) return;
          pan.current = { cx: e.clientX, cy: e.clientY, x: vb.x, y: vb.y, moved: false };
          (e.currentTarget as Element).setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => {
          if (drag) {
            const p = toFrame(e.clientX, e.clientY);
            setDrag({ id: drag.id, x: Math.min(W, Math.max(0, p.x)), y: Math.min(H, Math.max(0, p.y)) });
            return;
          }
          const p = pan.current;
          if (!p) return;
          const r = svg.current!.getBoundingClientRect();
          const scale = Math.max(vb.w / r.width, vb.h / r.height);
          const dx = (e.clientX - p.cx) * scale;
          const dy = (e.clientY - p.cy) * scale;
          if (Math.abs(e.clientX - p.cx) + Math.abs(e.clientY - p.cy) > 3) p.moved = true;
          setVb({ ...vb, x: p.x - dx, y: p.y - dy });
        }}
        onPointerUp={() => {
          if (drag) {
            onMove?.(drag.id, Math.round(drag.x * 100) / 100, Math.round(drag.y * 100) / 100);
            setDrag(null);
            return;
          }
          const p = pan.current;
          pan.current = null;
          if (p && !p.moved && !linkMode) onSelect?.(null);
        }}
      >
        <rect x={0} y={0} width={W} height={H} fill="var(--surface)" stroke="var(--line-strong)" vectorEffect="non-scaling-stroke" />
        {L.image && <image href={loc.imageUrl(frame.id, L.image)} x={0} y={0} width={W} height={H} preserveAspectRatio="none" opacity={0.85} />}
        {grid}
        {/* areas and rooms with a size or an outline */}
        {nodes.map((n) => {
          if (n.kind === "camera" || n.kind === "sensor") return null;
          const p = pos.get(n.id);
          const cls = `plan-place${n.restricted ? " restricted" : ""}${n.is_entry ? " entry" : ""}`;
          if (n.shape?.length > 2) return <polygon key={`a${n.id}`} points={n.shape.map((q) => q.join(",")).join(" ")} className={cls} vectorEffect="non-scaling-stroke" />;
          if (p && n.w && n.h) return <rect key={`a${n.id}`} x={p.x - n.w / 2} y={p.y - n.h / 2} width={n.w} height={n.h} className={n.layout ? "plan-area" : cls} vectorEffect="non-scaling-stroke" />;
          return null;
        })}
        {/* fields of view */}
        {nodes.map((n) => {
          const p = pos.get(n.id);
          if (n.kind !== "camera" || !p || n.orientation_deg == null) return null;
          return <path key={`f${n.id}`} d={fovPath(p.x, p.y, n.orientation_deg, n.fov_deg ?? 60, n.view_range ?? Math.max(W, H) / 12)} className="plan-fov" vectorEffect="non-scaling-stroke" />;
        })}
        {/* links */}
        {links.map((lk) => {
          const a = pos.get(lk.source)!;
          const b = pos.get(lk.target)!;
          const cam = [lk.source, lk.target].every((id) => graph.nodes.find((n) => n.id === id)?.kind === "camera");
          const mx = (a.x + b.x) / 2;
          const my = (a.y + b.y) / 2;
          const t = lk.travel_min_s != null || lk.travel_max_s != null ? `${lk.travel_min_s ?? 0}–${lk.travel_max_s ?? "?"} s` : "";
          const ang = Math.atan2(b.y - a.y, b.x - a.x);
          return (
            <g key={`l${lk.id}`}>
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className={`plan-link${cam ? " camera" : ""}${selectedLink === lk.id ? " sel" : ""}`} vectorEffect="non-scaling-stroke"
                strokeDasharray={lk.kind === "VISIBLE_FROM" ? "2 3" : undefined} />
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="plan-linkhit" stroke="transparent" strokeWidth={fs * 0.8} style={{ cursor: "pointer" }} onClick={() => onSelectLink?.(lk)}>
                <title>{`${lk.kind}${lk.one_way ? " (one way)" : ""}${t ? ` · ${t}` : ""}${lk.overlap ? " · overlapping views" : ""}`}</title>
              </line>
              {lk.one_way && (
                <path d={`M ${mx + Math.cos(ang) * fs * 0.6} ${my + Math.sin(ang) * fs * 0.6} L ${mx + Math.cos(ang + 2.5) * fs * 0.6} ${my + Math.sin(ang + 2.5) * fs * 0.6} L ${mx + Math.cos(ang - 2.5) * fs * 0.6} ${my + Math.sin(ang - 2.5) * fs * 0.6} Z`} fill="var(--g-camera)" />
              )}
              {t && <text x={mx} y={my - fs * 0.5} textAnchor="middle" className="plan-label small" style={{ fontSize: fs * 0.8 }}>{t}</text>}
            </g>
          );
        })}
        {/* recent moves between cameras (site view) */}
        {[...(overlays?.moves ?? [])].sort((a, b) => Number(a.flagged) - Number(b.flagged)).map((m, i) => {
          const a = pos.get(m.from);
          const b = pos.get(m.to);
          if (!a || !b) return null;
          return <line key={`m${i}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="plan-path" style={{ stroke: m.flagged ? "var(--err)" : undefined, strokeWidth: 2 }} vectorEffect="non-scaling-stroke" opacity={0.5} />;
        })}
        {/* a journey's path */}
        {overlays?.path && overlays.path.length > 1 && (
          <polyline points={overlays.path.map((p) => `${p.x},${p.y}`).join(" ")} className={`plan-path${overlays.selectedStep ? " dim" : ""}`} vectorEffect="non-scaling-stroke" />
        )}
        {/* nodes */}
        {nodes.map((n) => {
          const p = pos.get(n.id);
          if (!p) return null;
          const sel = selected === n.id || linkFrom === n.id;
          const hl = overlays?.highlight?.has(n.id);
          const r = fs * 0.55;
          const common = {
            className: `plan-node${drag?.id === n.id ? " dragging" : ""}`,
            onPointerDown: (e: React.PointerEvent) => {
              e.stopPropagation();
              if (editable && !linkMode) {
                (e.currentTarget as Element).setPointerCapture(e.pointerId);
                setDrag({ id: n.id, x: p.x, y: p.y });
              }
            },
            onPointerUp: (e: React.PointerEvent) => {
              e.stopPropagation();
              if (drag && drag.id === n.id) {
                const moved = Math.hypot(drag.x - p.x, drag.y - p.y) > 0.001;
                const orig = nodePoint(n, frame);
                const really = orig ? Math.hypot(drag.x - orig.x, drag.y - orig.y) > Math.max(W, H) / 500 : moved;
                if (really) onMove?.(n.id, Math.round(drag.x * 100) / 100, Math.round(drag.y * 100) / 100);
                setDrag(null);
                if (really) return;
              }
              clickNode(n.id);
            },
          };
          const label = (
            <text x={p.x} y={p.y + r * 2.6} textAnchor="middle" className="plan-label" style={{ fontSize: fs }}>
              {n.name}
            </text>
          );
          const hit = <rect x={p.x - Math.max(r * 2, n.name.length * fs * 0.3)} y={p.y - r * 1.6} width={Math.max(r * 4, n.name.length * fs * 0.6)} height={r * 4.6} fill="transparent" />;
          if (n.kind === "camera") {
            const cid = n.camera_id ?? -1;
            const count = overlays?.counts?.[cid];
            const alerts = overlays?.alerts?.[cid];
            return (
              <g key={n.id} {...common}>
                <title>{`${n.name}${n.camera ? ` (${n.camera.source_type})` : ""}`}</title>
                {hit}
                {(sel || hl) && <circle cx={p.x} cy={p.y} r={r * 2.1} className="plan-sel" vectorEffect="non-scaling-stroke" />}
                {overlays?.lastSeen === n.id && <circle cx={p.x} cy={p.y} r={r * 2.8} className="plan-lastseen" vectorEffect="non-scaling-stroke" />}
                <rect x={p.x - r} y={p.y - r * 0.75} width={r * 1.5} height={r * 1.5} rx={r * 0.15} className={`plan-cam${overlays?.active?.has(cid) ? " active" : ""}`} vectorEffect="non-scaling-stroke" />
                <path d={`M ${p.x + r * 0.5} ${p.y} L ${p.x + r * 1.1} ${p.y - r * 0.5} L ${p.x + r * 1.1} ${p.y + r * 0.5} Z`} className={`plan-cam${overlays?.active?.has(cid) ? " active" : ""}`} vectorEffect="non-scaling-stroke" />
                {count != null && count > 0 && (
                  <g>
                    <circle cx={p.x + r * 1.3} cy={p.y - r * 1.2} r={r * 0.75} className="plan-count-bg" />
                    <text x={p.x + r * 1.3} y={p.y - r * 0.95} textAnchor="middle" className="plan-count" style={{ fontSize: fs * 0.8 }}>{count}</text>
                  </g>
                )}
                {alerts != null && alerts > 0 && <circle cx={p.x - r * 1.2} cy={p.y - r * 1.2} r={r * 0.45} className="plan-alert"><title>{`${alerts} alert(s) in the last 24 h`}</title></circle>}
                {label}
              </g>
            );
          }
          if (n.kind === "sensor") {
            return (
              <g key={n.id} {...common}>
                <title>{`${n.name} (sensor ${n.sensor_id})`}</title>
                {hit}
                {(sel || hl) && <circle cx={p.x} cy={p.y} r={r * 2} className="plan-sel" vectorEffect="non-scaling-stroke" />}
                <path d={`M ${p.x} ${p.y - r} L ${p.x + r} ${p.y + r * 0.8} L ${p.x - r} ${p.y + r * 0.8} Z`} className="g-node g-node-sensor" vectorEffect="non-scaling-stroke" />
                {label}
              </g>
            );
          }
          const sized = (n.w && n.h) || n.shape?.length > 2;
          return (
            <g key={n.id} {...common}>
              <title>{`${n.name} (${n.kind_label})${n.restricted ? " · restricted" : ""}${n.is_entry ? " · entry point" : ""}`}</title>
              {!sized && hit}
              {(sel || hl) && <circle cx={p.x} cy={p.y} r={r * 1.9} className="plan-sel" vectorEffect="non-scaling-stroke" />}
              {overlays?.lastSeen === n.id && <circle cx={p.x} cy={p.y} r={r * 2.6} className="plan-lastseen" vectorEffect="non-scaling-stroke" />}
              {!sized && <rect x={p.x - r * 0.8} y={p.y - r * 0.6} width={r * 1.6} height={r * 1.2} rx={r * 0.2} className={`plan-place${n.restricted ? " restricted" : ""}${n.is_entry ? " entry" : ""}`} vectorEffect="non-scaling-stroke" />}
              {sized && <circle cx={p.x} cy={p.y} r={r * 0.35} fill="var(--g-place)" />}
              <text x={p.x} y={p.y + r * 2.4} textAnchor="middle" className="plan-label" style={{ fontSize: fs * (sized ? 1.05 : 0.95), fontWeight: n.layout ? 600 : undefined }}>
                {n.name}
                {n.is_entry ? " ⇥" : ""}
              </text>
            </g>
          );
        })}
        {/* journey steps on top */}
        {overlays?.path?.map((p, i) => (
          <g key={`s${p.key}`} className="plan-stephit" style={{ cursor: "pointer" }} onClick={() => overlays.onStep?.(p.key)}>
            <circle cx={p.x + fs * 0.9} cy={p.y - fs * 0.9} r={fs * 0.62} className={`plan-step${overlays.selectedStep === p.key ? " sel" : ""}`} vectorEffect="non-scaling-stroke" />
            <text x={p.x + fs * 0.9} y={p.y - fs * 0.62} textAnchor="middle" className="plan-step-label" style={{ fontSize: fs * 0.72 }}>{i + 1}</text>
            <title>{p.label}</title>
          </g>
        ))}
        {/* scale bar */}
        {unit && (
          <g>
            <line x1={W * 0.02} y1={H * 0.97} x2={W * 0.02 + gridStep} y2={H * 0.97} stroke="var(--text-2)" strokeWidth={2} vectorEffect="non-scaling-stroke" />
            <text x={W * 0.02 + gridStep + fs * 0.4} y={H * 0.97 + fs * 0.3} textAnchor="start" className="plan-label small" style={{ fontSize: fs * 0.8 }}>{gridStep} {unit}</text>
          </g>
        )}
      </svg>
    </div>
  );
}

/** Frames (nodes with a layout) to choose from, deepest last. */
export function layoutFrames(graph: LocGraph | undefined): LocNode[] {
  return (graph?.nodes ?? []).filter((n) => n.layout).sort((a, b) => a.path.localeCompare(b.path));
}

/** The frame to draw for a node: its own layout, else the frame it is placed in. */
export function frameFor(graph: LocGraph, nodeId: number | null | undefined): number | null {
  if (nodeId == null) return null;
  const n = graph.nodes.find((x) => x.id === nodeId);
  if (!n) return null;
  if (n.layout) return n.id;
  return n.frame_id;
}
