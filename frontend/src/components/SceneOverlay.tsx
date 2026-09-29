/* The zones, lines and routes of a scene drawn over a camera picture, with the
 * names the rule builder uses, so conditions can be read off the image.
 *
 * Scene points are normalized to the camera's geometry frame (after rotation
 * and crop), which is also the frame of the preview and the snapshots: the
 * overlay is stretched over the picture's box. Lines show which way is
 * "forward" (the direction a rule's "forward" refers to). Shapes are SVG;
 * labels are HTML so they stay sharp at any size. */

import type { Point, RouteDefinition, SceneDocument, SceneObject } from "../api/types";
import { OBJECT_COLORS, OBJECT_TYPE_LABELS } from "../lib/format";
import "./sceneOverlay.css";

const ROUTE_COLORS = ["#ff9a3c", "#70d6ff", "#c39bff", "#ff8fd8", "#a0e7a0", "#f9f871"];

export function objectColor(o: SceneObject): string {
  return o.color || OBJECT_COLORS[o.type] || "#ffffff";
}

export function isLineObject(o: SceneObject): boolean {
  return o.type === "line" || o.type === "gate";
}

function centroid(points: Point[]): Point {
  const n = points.length || 1;
  return { x: points.reduce((a, p) => a + p.x, 0) / n, y: points.reduce((a, p) => a + p.y, 0) / n };
}

/** What a rule can ask of this object, for its tooltip. */
export function objectHint(o: SceneObject): string {
  const type = OBJECT_TYPE_LABELS[o.type] ?? o.type;
  if (o.type === "ignore") return `${o.name} · ${type}: detections here are ignored`;
  if (isLineObject(o)) {
    const dir = "direction" in o ? o.direction : "both";
    const counted = dir === "both" ? "counts both directions" : dir === "forward" ? "counts forward crossings" : "counts reverse crossings";
    return `${o.name} · ${type} (${counted}). Rules: crosses — forward (arrow), reverse or any direction.`;
  }
  return `${o.name} · ${type}. Rules: enters, exits, remains in.`;
}

function routeLine(doc: SceneDocument, r: RouteDefinition): Point[] {
  return [r.start, ...r.sequence, r.end]
    .map((id) => doc.objects.find((o) => o.id === id))
    .filter((o): o is SceneObject => !!o)
    .map((o) => centroid(o.points));
}

export default function SceneOverlay({ doc, highlight, onHover, routes = true, labels = true }: { doc: SceneDocument; highlight?: Set<string>; onHover?: (ids: string[] | null) => void; routes?: boolean; labels?: boolean }) {
  const fw = doc.frame_width > 0 ? doc.frame_width : 16;
  const fh = doc.frame_height > 0 ? doc.frame_height : 9;
  const unit = Math.min(fw, fh);
  const px = (p: Point) => ({ x: p.x * fw, y: p.y * fh });
  const focus = highlight && highlight.size > 0;
  const opacity = (o: SceneObject) => (focus ? (highlight!.has(o.id) ? 1 : 0.28) : o.enabled ? 1 : 0.45);
  const objects = doc.objects;
  const arrow = (from: { x: number; y: number }, to: { x: number; y: number }, color: string, width: number, faint = false, key?: string) => {
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len;
    const uy = dy / len;
    const head = unit * 0.028;
    const base = { x: to.x - ux * head, y: to.y - uy * head };
    return (
      <g key={key} opacity={faint ? 0.45 : 1}>
        <line x1={from.x} y1={from.y} x2={base.x} y2={base.y} stroke={color} strokeWidth={width} vectorEffect="non-scaling-stroke" />
        <polygon points={`${to.x},${to.y} ${base.x - uy * head * 0.6},${base.y + ux * head * 0.6} ${base.x + uy * head * 0.6},${base.y - ux * head * 0.6}`} fill={color} />
      </g>
    );
  };

  return (
    <div className="scene-overlay">
      <svg viewBox={`0 0 ${fw} ${fh}`} preserveAspectRatio="none" role="img" aria-label="Zones and lines of the scene">
        {routes &&
          doc.routes.map((r, i) => {
            const pts = routeLine(doc, r).map(px);
            if (pts.length < 2) return null;
            const color = r.color || ROUTE_COLORS[i % ROUTE_COLORS.length];
            const faded = focus && ![r.start, ...r.sequence, r.end].some((id) => highlight!.has(id));
            return (
              <g key={`r-${r.id}`} opacity={faded ? 0.2 : r.enabled ? 0.85 : 0.35} className="scene-route">
                <polyline points={pts.map((p) => `${p.x},${p.y}`).join(" ")} fill="none" stroke={color} strokeWidth={1.5} strokeDasharray="7 5" vectorEffect="non-scaling-stroke" />
                {arrow(pts[pts.length - 2], pts[pts.length - 1], color, 1.5)}
                <title>{`Route ${r.name}: ${[r.start, ...r.sequence, r.end].map((id) => objects.find((o) => o.id === id)?.name ?? id).join(" → ")}`}</title>
              </g>
            );
          })}
        {objects.map((o) => {
          const color = objectColor(o);
          const hl = !!highlight?.has(o.id);
          const pts = o.points.map(px);
          if (pts.length === 0) return null;
          const events = onHover ? { onMouseEnter: () => onHover([o.id]), onMouseLeave: () => onHover(null) } : {};
          if (isLineObject(o) && pts.length >= 2) {
            const [a, b] = pts;
            const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
            const dx = b.x - a.x;
            const dy = b.y - a.y;
            const len = Math.hypot(dx, dy) || 1;
            const n = { x: -dy / len, y: dx / len };
            const L = unit * 0.075;
            const dir = "direction" in o ? o.direction : "both";
            return (
              <g key={o.id} opacity={opacity(o)} className="scene-object" {...events}>
                <title>{objectHint(o)}</title>
                <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="transparent" strokeWidth={14} vectorEffect="non-scaling-stroke" />
                {hl && <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#ffffff" strokeWidth={6} strokeOpacity={0.55} vectorEffect="non-scaling-stroke" />}
                <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={color} strokeWidth={hl ? 3.5 : 2.2} strokeDasharray={o.type === "gate" ? undefined : "7 4"} vectorEffect="non-scaling-stroke" />
                <circle cx={a.x} cy={a.y} r={unit * 0.008} fill={color} />
                <circle cx={b.x} cy={b.y} r={unit * 0.008} fill={color} />
                {/* forward = the side the solid arrow points to; a rule's "forward" means crossing that way */}
                {arrow({ x: mid.x - n.x * L * 0.15, y: mid.y - n.y * L * 0.15 }, { x: mid.x + n.x * L, y: mid.y + n.y * L }, color, hl ? 2.6 : 2, dir === "reverse")}
                {dir !== "forward" && arrow({ x: mid.x + n.x * L * 0.15, y: mid.y + n.y * L * 0.15 }, { x: mid.x - n.x * L * (dir === "both" ? 0.6 : 1), y: mid.y - n.y * L * (dir === "both" ? 0.6 : 1) }, color, 1.4, dir === "both")}
              </g>
            );
          }
          const fill = o.type === "ignore" ? "#969f9b" : color;
          const fillOpacity = o.type === "ignore" ? 0.3 : hl ? 0.26 : 0.13;
          return (
            <g key={o.id} opacity={opacity(o)} className="scene-object" {...events}>
              <title>{objectHint(o)}</title>
              {hl && <polygon points={pts.map((p) => `${p.x},${p.y}`).join(" ")} fill="none" stroke="#ffffff" strokeWidth={5} strokeOpacity={0.55} vectorEffect="non-scaling-stroke" />}
              <polygon points={pts.map((p) => `${p.x},${p.y}`).join(" ")} fill={fill} fillOpacity={fillOpacity} stroke={color} strokeWidth={hl ? 3 : 1.8} strokeDasharray={o.type === "checkpoint" ? "6 4" : undefined} vectorEffect="non-scaling-stroke" />
            </g>
          );
        })}
      </svg>
      {labels &&
        objects.map((o) => {
          if (!o.points.length) return null;
          const line = isLineObject(o) && o.points.length >= 2;
          // lines: at their first end; zones: inside the top-left corner, clear of lines through their middle
          const at = line ? o.points[0] : { x: Math.min(...o.points.map((q) => q.x)), y: Math.min(...o.points.map((q) => q.y)) };
          const color = objectColor(o);
          const hl = !!highlight?.has(o.id);
          const style: React.CSSProperties = {
            left: `${at.x * 100}%`,
            top: `${at.y * 100}%`,
            color,
            opacity: focus ? (hl ? 1 : 0.35) : o.enabled ? 1 : 0.55,
            borderColor: hl ? color : "transparent",
            transform: line ? "translate(4px, -125%)" : "translate(4px, 4px)",
          };
          return (
            <span key={`l-${o.id}`} className={`scene-label${hl ? " hl" : ""}`} style={style}>
              {o.name || o.id}
              <span className="scene-label-type">{OBJECT_TYPE_LABELS[o.type] ?? o.type}</span>
            </span>
          );
        })}
      {labels &&
        objects.filter((o) => isLineObject(o) && o.points.length >= 2).map((o) => {
          // "forward" written at the tip of the forward arrow
          const [a, b] = o.points.map(px);
          const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const len = Math.hypot(dx, dy) || 1;
          const L = unit * 0.075 * 1.35;
          const tip = { x: mid.x + (-dy / len) * L, y: mid.y + (dx / len) * L };
          const hl = !!highlight?.has(o.id);
          return (
            <span key={`f-${o.id}`} className="scene-forward" style={{ left: `${(tip.x / fw) * 100}%`, top: `${(tip.y / fh) * 100}%`, color: objectColor(o), opacity: focus ? (hl ? 1 : 0.3) : 0.9 }}>
              forward
            </span>
          );
        })}
    </div>
  );
}

/** One chip per scene object: its colour, name and type. Hovering a chip highlights it on the picture. */
export function SceneLegend({ doc, highlight, onHover }: { doc: SceneDocument; highlight?: Set<string>; onHover?: (ids: string[] | null) => void }) {
  return (
    <div className="scene-legend">
      {doc.objects.map((o) => (
        <span
          key={o.id}
          className={`scene-chip${highlight?.has(o.id) ? " hl" : ""}${o.enabled ? "" : " off"}`}
          title={objectHint(o)}
          onMouseEnter={() => onHover?.([o.id])}
          onMouseLeave={() => onHover?.(null)}
        >
          <span className={`scene-swatch ${isLineObject(o) ? "line" : o.type}`} style={{ color: objectColor(o) }} />
          {o.name || o.id}
          <span className="hint">{OBJECT_TYPE_LABELS[o.type] ?? o.type}</span>
          {isLineObject(o) && "direction" in o && o.direction !== "both" && <span className="hint">· counts {o.direction}</span>}
          {!o.enabled && <span className="hint">· off</span>}
        </span>
      ))}
      {doc.routes.map((r) => (
        <span key={`r-${r.id}`} className={`scene-chip${r.enabled ? "" : " off"}`} title={[r.start, ...r.sequence, r.end].map((id) => doc.objects.find((o) => o.id === id)?.name ?? id).join(" → ")}
          onMouseEnter={() => onHover?.([r.start, ...r.sequence, r.end])} onMouseLeave={() => onHover?.(null)}>
          <span className="scene-swatch route" style={{ color: r.color || OBJECT_COLORS.route }} />
          {r.name}
          <span className="hint">Route</span>
        </span>
      ))}
    </div>
  );
}
