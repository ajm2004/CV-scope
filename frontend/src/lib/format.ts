import type { SourceType } from "../api/types";

export const SOURCE_LABEL: Record<SourceType, string> = { file: "Video file", usb: "USB / built-in camera", rtsp: "RTSP stream", http: "HTTP / IP camera" };

export function bytes(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined) return "–";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i === 0 ? 0 : digits)} ${units[i]}`;
}

export function gb(n: number | null | undefined): string {
  if (n === null || n === undefined) return "–";
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
}

export function seconds(s: number | null | undefined, digits = 1): string {
  if (s === null || s === undefined || Number.isNaN(s)) return "–";
  if (s < 60) return `${s.toFixed(digits)} s`;
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  if (m < 60) return `${m}m ${r.toFixed(0)}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${(m - h * 60)}m`;
}

/** Without calibration, speeds are measured in frame widths per second, which "frame/s" hides. */
export function speedUnit(unit: string | null | undefined): string {
  if (!unit) return "";
  return unit === "frame/s" ? "frame widths/s" : unit;
}

export function clock(s: number | null | undefined): string {
  if (s === null || s === undefined || Number.isNaN(s)) return "--:--";
  const total = Math.max(0, Math.floor(s));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  const frac = Math.floor((s - total) * 10);
  const core = `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}.${frac}`;
  return h > 0 ? `${h}:${core}` : core;
}

export function num(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "–";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export function pct(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "–";
  return `${n.toFixed(digits)}%`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function timeOnly(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function titleCase(s: string | null | undefined): string {
  if (!s) return "";
  return s.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export const CLASS_OPTIONS = [
  { id: "person", label: "Person" },
  { id: "bicycle", label: "Bicycle" },
  { id: "car", label: "Car" },
  { id: "motorcycle", label: "Motorcycle" },
  { id: "bus", label: "Bus" },
  { id: "truck", label: "Truck" },
  { id: "train", label: "Train" },
  { id: "boat", label: "Boat" },
  { id: "dog", label: "Dog" },
  { id: "cat", label: "Cat" },
  { id: "horse", label: "Horse" },
];

export function classLabel(id: string): string {
  return CLASS_OPTIONS.find((c) => c.id === id)?.label ?? titleCase(id);
}

export const OBJECT_COLORS: Record<string, string> = {
  line: "#f2b632",
  gate: "#29c4e6",
  zone: "#52d273",
  checkpoint: "#e77df5",
  ignore: "#9aa3a0",
  route: "#ff9a3c",
  calibration: "#ffffff",
};

export const OBJECT_TYPE_LABELS: Record<string, string> = {
  line: "Counting line",
  gate: "Gate",
  zone: "Zone",
  checkpoint: "Checkpoint",
  ignore: "Ignore region",
};

export const EVENT_TYPE_LABELS: Record<string, string> = {
  crossing: "Crossing",
  zone_entry: "Zone entry",
  zone_exit: "Zone exit",
  dwell: "Dwell",
  dwell_exceeded: "Dwell exceeded",
  occupancy_exceeded: "Occupancy exceeded",
  route: "Route",
  sequence: "Sequence",
  rule: "Rule",
  custom: "Custom",
  anomaly: "Anomaly",
};

export function eventLabel(t: string): string {
  return EVENT_TYPE_LABELS[t] ?? titleCase(t);
}

export const RUN_STATE_CLASS: Record<string, string> = {
  running: "ok",
  starting: "accent",
  queued: "accent",
  paused: "warn",
  stopping: "warn",
  completed: "",
  finished: "",
  stopped: "",
  failed: "err",
};
