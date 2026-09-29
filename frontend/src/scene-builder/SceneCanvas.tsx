import type Konva from "konva";
import type { KonvaEventObject } from "konva/lib/Node";
import { useCallback, useMemo, useRef } from "react";
import { Arrow, Circle, Group, Image as KImage, Label, Layer, Line, Rect, Stage, Tag, Text } from "react-konva";
import type { Point, SceneObject } from "../api/types";
import { OBJECT_COLORS } from "../lib/format";
import { defaultLine, defaultZone, isLine, useEditor } from "./store";
import type { LiveFrame } from "./useLiveRun";

interface Fit {
  x: number;
  y: number;
  w: number;
  h: number;
}

const TRACK_COLORS = ["#ff5e5e", "#ffb347", "#f9f871", "#7bed9f", "#70d6ff", "#c39bff", "#ff8fd8", "#a0e7a0"];

function fitImage(cw: number, ch: number, iw: number, ih: number): Fit {
  const s = Math.min(cw / iw, ch / ih);
  const w = iw * s;
  const h = ih * s;
  return { x: (cw - w) / 2, y: (ch - h) / 2, w, h };
}

export default function SceneCanvas({ width, height, image, live, defaultClasses, onObjectClick }: { width: number; height: number; image: HTMLImageElement | null; live: LiveFrame | null; defaultClasses: string[]; onObjectClick?: (id: string) => void }) {
  const doc = useEditor((s) => s.doc);
  const tool = useEditor((s) => s.tool);
  const selectedId = useEditor((s) => s.selectedId);
  const selectedRouteId = useEditor((s) => s.selectedRouteId);
  const draft = useEditor((s) => s.draft);
  const routeDraft = useEditor((s) => s.routeDraft);
  const overlays = useEditor((s) => s.overlays);
  const view = useEditor((s) => s.view);
  const ed = useEditor.getState;
  const stageRef = useRef<Konva.Stage | null>(null);
  const dragStart = useRef<{ x: number; y: number } | null>(null);

  const frameW = doc?.frame_width ?? live?.meta.source_width ?? image?.naturalWidth ?? 16;
  const frameH = doc?.frame_height ?? live?.meta.source_height ?? image?.naturalHeight ?? 9;
  const fit = useMemo(() => fitImage(width, height, frameW, frameH), [width, height, frameW, frameH]);

  const toPx = useCallback((p: Point) => ({ x: fit.x + p.x * fit.w, y: fit.y + p.y * fit.h }), [fit]);
  // Points within ~1% of the image border snap onto it, so a zone can reach the
  // frame edge exactly (people cut off by the frame have their feet on that edge).
  const toNorm = useCallback((px: number, py: number): Point => {
    const snap = (v: number) => {
      const c = Math.max(0, Math.min(1, v));
      return c < 0.012 ? 0 : c > 0.988 ? 1 : c;
    };
    return { x: snap((px - fit.x) / fit.w), y: snap((py - fit.y) / fit.h) };
  }, [fit]);

  /** Pointer position in the (zoomed/panned) content coordinate system. */
  const pointer = (): { x: number; y: number } | null => {
    const stage = stageRef.current;
    if (!stage) return null;
    const p = stage.getPointerPosition();
    if (!p) return null;
    return { x: (p.x - view.x) / view.scale, y: (p.y - view.y) / view.scale };
  };

  const finishPolygon = () => {
    const d = ed();
    if (!d.doc || d.draft.length < 3) return;
    const type = d.tool === "zone" ? "zone" : d.tool === "checkpoint" ? "checkpoint" : "ignore";
    d.addObject(defaultZone(type, d.draft, d.doc, defaultClasses));
    d.clearDraft();
  };

  const onStageMouseDown = (e: KonvaEventObject<MouseEvent>) => {
    const d = ed();
    if (!d.doc) return;
    const p = pointer();
    if (!p) return;
    const clickedEmpty = e.target === e.target.getStage() || e.target.name() === "background";
    if (tool === "select" && clickedEmpty) {
      d.select(null);
      return;
    }
    if (tool === "line" || tool === "gate") {
      const n = toNorm(p.x, p.y);
      if (d.draft.length === 0) d.pushDraftPoint(n);
      else {
        d.addObject(defaultLine(tool, [d.draft[0], n], d.doc, defaultClasses));
        d.clearDraft();
      }
      return;
    }
    if (tool === "zone" || tool === "checkpoint" || tool === "ignore") {
      const n = toNorm(p.x, p.y);
      if (d.draft.length >= 3) {
        const first = toPx(d.draft[0]);
        if (Math.hypot(first.x - p.x, first.y - p.y) < 8 / view.scale) {
          finishPolygon();
          return;
        }
      }
      d.pushDraftPoint(n);
      return;
    }
    if (tool === "calibration") {
      const n = toNorm(p.x, p.y);
      const cal = d.doc.calibration ?? { unit: "m", points: [], known_distance: null, notes: "" };
      d.setCalibration({ ...cal, points: [...cal.points, { image: n, ground_x: 0, ground_y: 0 }] });
      return;
    }
  };

  const onDblClick = () => {
    if (tool === "zone" || tool === "checkpoint" || tool === "ignore") finishPolygon();
  };

  const onWheel = (e: KonvaEventObject<WheelEvent>) => {
    e.evt.preventDefault();
    const stage = stageRef.current;
    if (!stage) return;
    const p = stage.getPointerPosition();
    if (!p) return;
    const old = view.scale;
    const factor = e.evt.deltaY > 0 ? 1 / 1.1 : 1.1;
    const scale = Math.max(0.5, Math.min(8, old * factor));
    const mx = (p.x - view.x) / old;
    const my = (p.y - view.y) / old;
    ed().setView({ scale, x: p.x - mx * scale, y: p.y - my * scale });
  };

  const objectClick = (o: SceneObject) => (e: KonvaEventObject<MouseEvent>) => {
    e.cancelBubble = true;
    const d = ed();
    if (tool === "route") {
      d.pushRouteDraft(o.id);
      onObjectClick?.(o.id);
      return;
    }
    if (tool === "select") d.select(o.id);
  };

  const objectDrag = (o: SceneObject) => ({
    draggable: tool === "select" && !o.locked && selectedId === o.id,
    onDragStart: (e: KonvaEventObject<DragEvent>) => {
      ed().beginDrag();
      dragStart.current = { x: e.target.x(), y: e.target.y() };
    },
    onDragEnd: (e: KonvaEventObject<DragEvent>) => {
      const dx = (e.target.x() - (dragStart.current?.x ?? 0)) / fit.w;
      const dy = (e.target.y() - (dragStart.current?.y ?? 0)) / fit.h;
      e.target.position({ x: 0, y: 0 });
      ed().setObjectPoints(o.id, o.points.map((p) => ({ x: Math.max(0, Math.min(1, p.x + dx)), y: Math.max(0, Math.min(1, p.y + dy)) })));
    },
  });

  const vertexHandles = (o: SceneObject) =>
    o.points.map((p, i) => {
      const px = toPx(p);
      return (
        <Circle
          key={i}
          x={px.x}
          y={px.y}
          radius={5 / view.scale}
          fill="#fff"
          stroke={colorOf(o)}
          strokeWidth={1.5 / view.scale}
          draggable={!o.locked}
          onDragStart={() => ed().beginDrag()}
          onDragMove={(e) => {
            const n = toNorm(e.target.x(), e.target.y());
            const pts = o.points.map((q, j) => (j === i ? n : q));
            ed().setObjectPoints(o.id, pts);
          }}
          onMouseDown={(e) => (e.cancelBubble = true)}
        />
      );
    });

  const colorOf = (o: SceneObject) => o.color || OBJECT_COLORS[o.type] || "#fff";
  const routeColorMap = useMemo(() => {
    const m: Record<string, string> = {};
    doc?.routes.forEach((r, i) => (m[r.id] = r.color || TRACK_COLORS[(i + 3) % TRACK_COLORS.length]));
    return m;
  }, [doc?.routes]);

  const strokeScale = 1 / view.scale;
  const bg = live?.img ?? image;

  return (
    <Stage
      ref={stageRef}
      width={width}
      height={height}
      scaleX={view.scale}
      scaleY={view.scale}
      x={view.x}
      y={view.y}
      draggable={tool === "pan"}
      onDragEnd={(e) => {
        if (e.target === e.target.getStage()) ed().setView({ ...view, x: e.target.x(), y: e.target.y() });
      }}
      onMouseDown={onStageMouseDown}
      onDblClick={onDblClick}
      onWheel={onWheel}
      style={{ cursor: tool === "pan" ? "grab" : tool === "select" ? "default" : "crosshair" }}
    >
      <Layer listening={false}>
        <Rect name="background" x={fit.x} y={fit.y} width={fit.w} height={fit.h} fill="#000" />
        {bg && <KImage image={bg} x={fit.x} y={fit.y} width={fit.w} height={fit.h} />}
      </Layer>
      <Layer>
        <Rect name="background" x={fit.x} y={fit.y} width={fit.w} height={fit.h} fill="rgba(0,0,0,0)" />
        {/* routes: dashed chain through start -> checkpoints -> end */}
        {doc && overlays.objects && doc.routes.map((r) => {
          const ids = [r.start, ...r.sequence, r.end];
          const pts = ids
            .map((id) => doc.objects.find((o) => o.id === id))
            .filter((o): o is SceneObject => !!o)
            .map((o) => centroid(o))
            .map(toPx);
          if (pts.length < 2) return null;
          const sel = selectedRouteId === r.id;
          return (
            <Group key={r.id} listening={false}>
              <Arrow points={pts.flatMap((p) => [p.x, p.y])} stroke={routeColorMap[r.id]} fill={routeColorMap[r.id]} strokeWidth={(sel ? 2.5 : 1.5) * strokeScale} dash={[8 * strokeScale, 6 * strokeScale]} pointerLength={10 * strokeScale} pointerWidth={8 * strokeScale} opacity={r.enabled ? 0.9 : 0.4} />
              {overlays.labels && (
                <Label x={pts[Math.floor(pts.length / 2) - (pts.length % 2 === 0 ? 1 : 0)].x + 6 * strokeScale} y={pts[Math.floor(pts.length / 2) - (pts.length % 2 === 0 ? 1 : 0)].y + 6 * strokeScale}>
                  <Tag fill={routeColorMap[r.id]} cornerRadius={2} />
                  <Text text={r.name} fontSize={11 * strokeScale} padding={3 * strokeScale} fill="#111" />
                </Label>
              )}
            </Group>
          );
        })}
        {/* scene objects */}
        {doc && overlays.objects && doc.objects.filter((o) => o.visible).map((o) => {
          const color = colorOf(o);
          const sel = selectedId === o.id;
          const inRouteDraft = routeDraft.includes(o.id);
          const op = o.enabled ? 1 : 0.35;
          const pts = o.points.map(toPx);
          const flat = pts.flatMap((p) => [p.x, p.y]);
          if (isLine(o)) {
            const [a, b] = pts;
            const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
            const dx = b.x - a.x;
            const dy = b.y - a.y;
            const len = Math.hypot(dx, dy) || 1;
            const n = { x: -dy / len, y: dx / len };
            const arrowLen = 18 * strokeScale;
            return (
              <Group key={o.id} opacity={op} {...objectDrag(o)}>
                <Line points={flat} stroke={color} strokeWidth={(sel ? 3 : 2) * strokeScale} hitStrokeWidth={14 * strokeScale} dash={o.type === "gate" ? undefined : [6 * strokeScale, 4 * strokeScale]} shadowColor={sel || inRouteDraft ? "#fff" : undefined} shadowBlur={sel || inRouteDraft ? 6 : 0} onClick={objectClick(o)} />
                <Circle x={a.x} y={a.y} radius={3 * strokeScale} fill={color} listening={false} />
                <Circle x={b.x} y={b.y} radius={3 * strokeScale} fill={color} listening={false} />
                {(o.direction === "both" || o.direction === "forward") && (
                  <Arrow points={[mid.x - n.x * 4 * strokeScale, mid.y - n.y * 4 * strokeScale, mid.x + n.x * arrowLen, mid.y + n.y * arrowLen]} stroke={color} fill={color} strokeWidth={2 * strokeScale} pointerLength={7 * strokeScale} pointerWidth={7 * strokeScale} listening={false} />
                )}
                {(o.direction === "both" || o.direction === "reverse") && (
                  // With both directions counted, the reverse arrow is short and faint so
                  // the solid one still shows which way the results call forward.
                  <Arrow
                    points={[mid.x + n.x * 4 * strokeScale, mid.y + n.y * 4 * strokeScale, mid.x - n.x * arrowLen * (o.direction === "both" ? 0.6 : 1), mid.y - n.y * arrowLen * (o.direction === "both" ? 0.6 : 1)]}
                    stroke={color}
                    fill={color}
                    strokeWidth={(o.direction === "both" ? 1.25 : 2) * strokeScale}
                    pointerLength={(o.direction === "both" ? 5 : 7) * strokeScale}
                    pointerWidth={(o.direction === "both" ? 5 : 7) * strokeScale}
                    opacity={o.direction === "both" ? 0.45 : 1}
                    listening={false}
                  />
                )}
                {overlays.labels && (
                  <Label x={a.x + 6 * strokeScale} y={a.y - 18 * strokeScale} listening={false}>
                    <Tag fill="rgba(20,23,22,0.8)" cornerRadius={2} />
                    <Text text={`${o.name}${o.doorway ? " (doorway)" : ""}`} fontSize={11 * strokeScale} padding={3 * strokeScale} fill={color} />
                  </Label>
                )}
                {sel && tool === "select" && vertexHandles(o)}
              </Group>
            );
          }
          const c = toPx(centroid(o));
          return (
            <Group key={o.id} opacity={op} {...objectDrag(o)}>
              <Line points={flat} closed stroke={color} strokeWidth={(sel ? 2.5 : 1.5) * strokeScale} fill={o.type === "ignore" ? "rgba(150,160,155,0.35)" : `${color}26`} dash={o.type === "checkpoint" ? [5 * strokeScale, 4 * strokeScale] : undefined} shadowColor={sel || inRouteDraft ? "#fff" : undefined} shadowBlur={sel || inRouteDraft ? 6 : 0} onClick={objectClick(o)} />
              {overlays.labels && (
                <Label x={c.x} y={c.y} listening={false}>
                  <Tag fill="rgba(20,23,22,0.8)" cornerRadius={2} />
                  <Text text={o.name} fontSize={11 * strokeScale} padding={3 * strokeScale} fill={color} />
                </Label>
              )}
              {sel && tool === "select" && vertexHandles(o)}
            </Group>
          );
        })}
        {/* calibration */}
        {doc?.calibration && overlays.objects && (
          <Group listening={false}>
            {doc.calibration.points.map((cp, i) => {
              const p = toPx(cp.image);
              return (
                <Group key={i}>
                  <Circle x={p.x} y={p.y} radius={5 * strokeScale} stroke="#fff" strokeWidth={1.5 * strokeScale} />
                  <Line points={[p.x - 8 * strokeScale, p.y, p.x + 8 * strokeScale, p.y]} stroke="#fff" strokeWidth={1 * strokeScale} />
                  <Line points={[p.x, p.y - 8 * strokeScale, p.x, p.y + 8 * strokeScale]} stroke="#fff" strokeWidth={1 * strokeScale} />
                  <Text x={p.x + 7 * strokeScale} y={p.y + 4 * strokeScale} text={`${i + 1} (${cp.ground_x}, ${cp.ground_y})`} fontSize={10 * strokeScale} fill="#fff" />
                </Group>
              );
            })}
            {doc.calibration.known_distance && (
              <Group>
                <Line points={[toPx(doc.calibration.known_distance.a).x, toPx(doc.calibration.known_distance.a).y, toPx(doc.calibration.known_distance.b).x, toPx(doc.calibration.known_distance.b).y]} stroke="#fff" strokeWidth={1.5 * strokeScale} dash={[3 * strokeScale, 3 * strokeScale]} />
                <Text x={(toPx(doc.calibration.known_distance.a).x + toPx(doc.calibration.known_distance.b).x) / 2} y={(toPx(doc.calibration.known_distance.a).y + toPx(doc.calibration.known_distance.b).y) / 2} text={`${doc.calibration.known_distance.distance} ${doc.calibration.unit}`} fontSize={11 * strokeScale} fill="#fff" />
              </Group>
            )}
          </Group>
        )}
        {/* draft */}
        {draft.length > 0 && (
          <Group listening={false}>
            <Line points={draft.map(toPx).flatMap((p) => [p.x, p.y])} stroke="#fff" strokeWidth={1.5 * strokeScale} dash={[4 * strokeScale, 4 * strokeScale]} closed={false} />
            {draft.map((p, i) => {
              const px = toPx(p);
              return <Circle key={i} x={px.x} y={px.y} radius={4 * strokeScale} fill={i === 0 ? "#fff" : "#ccc"} />;
            })}
          </Group>
        )}
      </Layer>
      {/* live overlay */}
      {live && (
        <Layer listening={false}>
          {live.meta.tracks.map((t) => {
            const sx = fit.w / live.meta.source_width;
            const sy = fit.h / live.meta.source_height;
            const [x1, y1, x2, y2] = t.box;
            const col = t.state === "lost" ? "#9aa3a0" : TRACK_COLORS[t.id % TRACK_COLORS.length];
            const bx = fit.x + x1 * sx;
            const by = fit.y + y1 * sy;
            const bw = (x2 - x1) * sx;
            const bh = (y2 - y1) * sy;
            const rec = overlays.identity && t.recognition ? t.recognition.identity ?? (t.recognition.plate ? `${t.recognition.plate}${t.recognition.vehicle ? ` (${t.recognition.vehicle})` : ""}` : "") : "";
            const label = [overlays.ids ? `#${t.id}` : "", t.cls, rec ? `= ${rec}` : "", overlays.conf ? `${(t.conf * 100).toFixed(0)}%` : "", overlays.routeState && t.route_state ? (t.route_state.candidate ? `→ ${t.route_state.candidate}` : `in ${t.route_state.group}`) : "", overlays.zonesOfTrack && t.zones?.length ? `in ${t.zones.length} zone${t.zones.length > 1 ? "s" : ""}` : ""].filter(Boolean).join(" ");
            return (
              <Group key={t.id}>
                {overlays.boxes && <Rect x={bx} y={by} width={bw} height={bh} stroke={col} strokeWidth={1.5 * strokeScale} dash={t.state === "lost" ? [4 * strokeScale, 3 * strokeScale] : undefined} />}
                {overlays.boxes && <Circle x={bx + bw / 2} y={by + bh} radius={3 * strokeScale} fill={col} />}
                {overlays.trails && t.trail && t.trail.length > 1 && <Line points={t.trail.flatMap(([x, y]) => [fit.x + x * fit.w, fit.y + y * fit.h])} stroke={col} strokeWidth={1.5 * strokeScale} opacity={0.8} />}
                {label && (
                  <Label x={bx} y={by - 14 * strokeScale}>
                    <Tag fill="rgba(20,23,22,0.85)" cornerRadius={2} />
                    <Text text={label} fontSize={10 * strokeScale} padding={2 * strokeScale} fill={col} />
                  </Label>
                )}
              </Group>
            );
          })}
        </Layer>
      )}
    </Stage>
  );
}

function centroid(o: SceneObject): Point {
  const n = o.points.length || 1;
  return { x: o.points.reduce((a, p) => a + p.x, 0) / n, y: o.points.reduce((a, p) => a + p.y, 0) / n };
}
