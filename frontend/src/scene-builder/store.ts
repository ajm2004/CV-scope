import { create } from "zustand";
import type { Calibration, LineObject, Point, RouteDefinition, SceneDocument, SceneObject, ZoneObject } from "../api/types";

export type Tool = "select" | "pan" | "line" | "gate" | "zone" | "checkpoint" | "ignore" | "route" | "calibration";

export interface Overlays {
  objects: boolean;
  labels: boolean;
  boxes: boolean;
  ids: boolean;
  trails: boolean;
  conf: boolean;
  routeState: boolean;
  zonesOfTrack: boolean;
  /** Identities and plates of the licensed recognition modules (needs a recognition token). */
  identity: boolean;
}

export interface ViewTransform {
  scale: number;
  x: number;
  y: number;
}

interface EditorState {
  doc: SceneDocument | null;
  sceneId: number | null;
  version: number;
  frozen: boolean;
  dirty: boolean;
  tool: Tool;
  selectedId: string | null;
  selectedRouteId: string | null;
  draft: Point[];
  routeDraft: string[];
  past: SceneDocument[];
  future: SceneDocument[];
  overlays: Overlays;
  view: ViewTransform;
  load: (doc: SceneDocument, meta: { sceneId: number | null; version: number; frozen: boolean }) => void;
  setTool: (t: Tool) => void;
  select: (id: string | null, routeId?: string | null) => void;
  pushDraftPoint: (p: Point) => void;
  setDraft: (pts: Point[]) => void;
  clearDraft: () => void;
  pushRouteDraft: (id: string) => void;
  clearRouteDraft: () => void;
  commit: (mutate: (doc: SceneDocument) => void) => void;
  beginDrag: () => void;
  setObjectPoints: (id: string, points: Point[]) => void;
  updateObject: (id: string, patch: Partial<LineObject> | Partial<ZoneObject>) => void;
  addObject: (obj: SceneObject) => void;
  removeObject: (id: string) => void;
  duplicateObject: (id: string) => void;
  addRoute: (route: RouteDefinition) => void;
  updateRoute: (id: string, patch: Partial<RouteDefinition>) => void;
  removeRoute: (id: string) => void;
  setCalibration: (cal: Calibration | null) => void;
  undo: () => void;
  redo: () => void;
  markSaved: (meta: { sceneId: number; version: number; frozen: boolean }) => void;
  setOverlay: (k: keyof Overlays, v: boolean) => void;
  setView: (v: ViewTransform) => void;
}

const MAX_HISTORY = 100;

export function newId(prefix: string): string {
  return `${prefix}_${Math.random().toString(16).slice(2, 10)}`;
}

function clone<T>(v: T): T {
  return structuredClone(v);
}

function uniqueName(doc: SceneDocument, base: string): string {
  const names = new Set(doc.objects.map((o) => o.name));
  if (!names.has(base)) return base;
  let i = 2;
  while (names.has(`${base} ${i}`)) i++;
  return `${base} ${i}`;
}

export function defaultLine(type: "line" | "gate", points: [Point, Point], doc: SceneDocument, classes: string[]): LineObject {
  return {
    id: newId(type),
    type,
    name: uniqueName(doc, type === "gate" ? "Gate" : "Line"),
    enabled: true,
    locked: false,
    visible: true,
    color: null,
    notes: "",
    classes,
    points,
    direction: "both",
    actions: ["count", "record"],
    min_confidence: 0,
    min_track_age: 2,
    debounce_s: 1,
    doorway: false,
  };
}

export function defaultZone(type: "zone" | "checkpoint" | "ignore", points: Point[], doc: SceneDocument, classes: string[]): ZoneObject {
  return {
    id: newId(type),
    type,
    name: uniqueName(doc, type === "zone" ? "Zone" : type === "checkpoint" ? "Checkpoint" : "Ignore region"),
    enabled: true,
    locked: false,
    visible: true,
    color: null,
    notes: "",
    classes: type === "ignore" ? [] : classes,
    points,
    measures: type === "zone" ? ["entry", "exit", "occupancy", "dwell"] : ["entry"],
    min_dwell_s: 0,
    max_dwell_s: null,
    max_objects: null,
    min_confidence: 0,
    min_track_age: 2,
    debounce_s: 0.5,
  };
}

export const useEditor = create<EditorState>((set, get) => ({
  doc: null,
  sceneId: null,
  version: 0,
  frozen: false,
  dirty: false,
  tool: "select",
  selectedId: null,
  selectedRouteId: null,
  draft: [],
  routeDraft: [],
  past: [],
  future: [],
  overlays: { objects: true, labels: true, boxes: true, ids: true, trails: true, conf: false, routeState: true, zonesOfTrack: false, identity: true },
  view: { scale: 1, x: 0, y: 0 },

  load: (doc, meta) => set({ doc: clone(doc), sceneId: meta.sceneId, version: meta.version, frozen: meta.frozen, dirty: false, past: [], future: [], selectedId: null, selectedRouteId: null, draft: [], routeDraft: [] }),
  setTool: (tool) => set({ tool, draft: [], routeDraft: [] }),
  select: (id, routeId = null) => set({ selectedId: id, selectedRouteId: routeId }),
  pushDraftPoint: (p) => set((s) => ({ draft: [...s.draft, p] })),
  setDraft: (pts) => set({ draft: pts }),
  clearDraft: () => set({ draft: [] }),
  pushRouteDraft: (id) => set((s) => (s.routeDraft.includes(id) ? s : { routeDraft: [...s.routeDraft, id] })),
  clearRouteDraft: () => set({ routeDraft: [] }),

  commit: (mutate) => {
    const { doc, past } = get();
    if (!doc) return;
    const next = clone(doc);
    mutate(next);
    set({ doc: next, past: [...past.slice(-MAX_HISTORY + 1), doc], future: [], dirty: true });
  },
  beginDrag: () => {
    const { doc, past } = get();
    if (!doc) return;
    set({ past: [...past.slice(-MAX_HISTORY + 1), clone(doc)], future: [] });
  },
  setObjectPoints: (id, points) => {
    const { doc } = get();
    if (!doc) return;
    const next = clone(doc);
    const o = next.objects.find((x) => x.id === id);
    if (!o) return;
    (o as ZoneObject).points = points as Point[];
    set({ doc: next, dirty: true });
  },
  updateObject: (id, patch) => get().commit((d) => {
    const o = d.objects.find((x) => x.id === id);
    if (o) Object.assign(o, patch);
  }),
  addObject: (obj) => {
    get().commit((d) => {
      d.objects.push(obj);
    });
    set({ selectedId: obj.id, selectedRouteId: null });
  },
  removeObject: (id) => {
    get().commit((d) => {
      d.objects = d.objects.filter((o) => o.id !== id);
      d.routes = d.routes.filter((r) => r.start !== id && r.end !== id).map((r) => ({ ...r, sequence: r.sequence.filter((s) => s !== id) }));
    });
    set({ selectedId: null });
  },
  duplicateObject: (id) => {
    const { doc } = get();
    if (!doc) return;
    const src = doc.objects.find((o) => o.id === id);
    if (!src) return;
    const copy = clone(src) as SceneObject;
    copy.id = newId(copy.type);
    copy.name = uniqueName(doc, `${src.name} copy`);
    copy.points = copy.points.map((p) => ({ x: Math.min(1, p.x + 0.03), y: Math.min(1, p.y + 0.03) })) as typeof copy.points;
    get().addObject(copy);
  },
  addRoute: (route) => {
    get().commit((d) => {
      d.routes.push(route);
    });
    set({ selectedRouteId: route.id, selectedId: null });
  },
  updateRoute: (id, patch) => get().commit((d) => {
    const r = d.routes.find((x) => x.id === id);
    if (r) Object.assign(r, patch);
  }),
  removeRoute: (id) => {
    get().commit((d) => {
      d.routes = d.routes.filter((r) => r.id !== id);
    });
    set({ selectedRouteId: null });
  },
  setCalibration: (cal) => get().commit((d) => {
    d.calibration = cal;
  }),
  undo: () => {
    const { past, doc, future } = get();
    if (!doc || past.length === 0) return;
    const prev = past[past.length - 1];
    set({ doc: prev, past: past.slice(0, -1), future: [doc, ...future].slice(0, MAX_HISTORY), dirty: true });
  },
  redo: () => {
    const { past, doc, future } = get();
    if (!doc || future.length === 0) return;
    const next = future[0];
    set({ doc: next, past: [...past, doc], future: future.slice(1), dirty: true });
  },
  markSaved: (meta) => set({ sceneId: meta.sceneId, version: meta.version, frozen: meta.frozen, dirty: false }),
  setOverlay: (k, v) => set((s) => ({ overlays: { ...s.overlays, [k]: v } })),
  setView: (view) => set({ view }),
}));

export function objectLabel(o: SceneObject): string {
  return o.name || o.id;
}

export function isLine(o: SceneObject): o is LineObject {
  return o.type === "line" || o.type === "gate";
}

export function routeUsesObject(doc: SceneDocument, id: string): boolean {
  return doc.routes.some((r) => r.start === id || r.end === id || r.sequence.includes(id));
}
