import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { num } from "../lib/format";

// Categorical palette: distinct hues, moderate chroma, legible on white.
export const SERIES_COLORS = ["#0b6b8a", "#d9861b", "#3a9a4c", "#a24fa0", "#8b6a3d", "#5a7d9a", "#c4493b", "#6d7a73", "#2f8f8f", "#b8a12a"];

export function colorFor(i: number): string {
  return SERIES_COLORS[i % SERIES_COLORS.length];
}

/** Dense horizontal bars for a categorical distribution. */
export function BarList({ items, total, unit = "" }: { items: { label: string; value: number; muted?: boolean; color?: string }[]; total?: number; unit?: string }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  const t = total ?? items.reduce((a, b) => a + b.value, 0);
  return (
    <table className="table" style={{ fontSize: "var(--fs-1)" }}>
      <tbody>
        {items.map((it, i) => (
          <tr key={it.label}>
            <td style={{ width: 160, color: it.muted ? "var(--text-3)" : undefined }}>{it.label}</td>
            <td style={{ width: "100%" }}>
              <div style={{ height: 10, background: "var(--surface-3)", borderRadius: 2 }}>
                <div style={{ width: `${(it.value / max) * 100}%`, height: "100%", background: it.color ?? (it.muted ? "var(--line-strong)" : colorFor(i)), borderRadius: 2 }} />
              </div>
            </td>
            <td className="num" style={{ width: 70 }}>
              {num(it.value, 0)}
              {unit}
            </td>
            <td className="num muted" style={{ width: 60 }}>
              {t > 0 ? `${((it.value / t) * 100).toFixed(1)}%` : "–"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export interface SeriesPoint {
  x: string | number;
  [series: string]: string | number;
}

/** Stacked bars per bucket, one series per label. */
export function StackedSeries({ data, series, height = 220, xLabel, formatX }: { data: SeriesPoint[]; series: string[]; height?: number; xLabel?: string; formatX?: (x: string | number) => string }) {
  if (!data.length) return <div className="empty">No data for this range.</div>;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 6, right: 8, left: -18, bottom: xLabel ? 14 : 0 }} barCategoryGap={2}>
        <CartesianGrid stroke="var(--line)" vertical={false} />
        <XAxis dataKey="x" tick={{ fontSize: 11, fill: "var(--text-2)" }} tickFormatter={formatX} label={xLabel ? { value: xLabel, position: "insideBottom", offset: -8, fontSize: 11, fill: "var(--text-2)" } : undefined} />
        <YAxis tick={{ fontSize: 11, fill: "var(--text-2)" }} allowDecimals={false} />
        <Tooltip contentStyle={{ fontSize: 12, borderRadius: 3, border: "1px solid var(--line-strong)" }} labelFormatter={(l) => (formatX ? formatX(l as string) : String(l))} />
        {series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
        {series.map((s, i) => (
          <Bar key={s} dataKey={s} stackId="a" fill={colorFor(i)} isAnimationActive={false} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Convert {start_s|hour, counts:{label:n}} buckets to chart rows. */
export function bucketsToSeries(buckets: { start_s?: number; hour?: string; counts: Record<string, number> }[]): { data: SeriesPoint[]; series: string[] } {
  const labels = new Set<string>();
  for (const b of buckets) for (const k of Object.keys(b.counts)) labels.add(k);
  const series = [...labels];
  const data: SeriesPoint[] = buckets.map((b) => {
    const row: SeriesPoint = { x: b.hour ?? (b.start_s ?? 0) };
    for (const s of series) row[s] = b.counts[s] ?? 0;
    return row;
  });
  return { data, series };
}

export function Heatmap({ cells, grid, width = 480, aspect = 16 / 9 }: { cells: number[][]; grid: number; width?: number; aspect?: number }) {
  const height = width / aspect;
  const max = Math.max(1, ...cells.flat());
  const cw = width / grid;
  const ch = height / grid;
  return (
    <svg width={width} height={height} style={{ background: "var(--stage)", borderRadius: 3, display: "block", maxWidth: "100%" }} viewBox={`0 0 ${width} ${height}`}>
      {cells.map((row, y) =>
        row.map((v, x) =>
          v > 0 ? <rect key={`${x}-${y}`} x={x * cw} y={y * ch} width={cw + 0.5} height={ch + 0.5} fill={`rgba(255, 154, 60, ${0.15 + 0.85 * Math.sqrt(v / max)})`} /> : null,
        ),
      )}
    </svg>
  );
}
