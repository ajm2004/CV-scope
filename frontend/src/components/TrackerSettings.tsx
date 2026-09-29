import type { TrackerInfo, TrackerSetting } from "../api/types";
import { Field } from "./ui";

/** Editable fields for a tracker's settings. Only values that differ from the
 *  tracker defaults are kept, so defaults can improve without migrating data. */
export function TrackerSettingsFields({ tracker, values, onChange }: { tracker: TrackerInfo; values: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void }) {
  const set = (s: TrackerSetting, v: unknown) => {
    const next = { ...values };
    if (v === undefined || v === s.default) delete next[s.key];
    else next[s.key] = v;
    onChange(next);
  };
  return (
    <>
      {tracker.settings.map((s) => {
        const current = values[s.key];
        if (s.type === "enum") {
          const value = String(current ?? s.default ?? "");
          const known = s.options?.some((o) => o.value === value);
          return (
            <Field key={s.key} label={s.label} help={s.help} className={s.key === "appearance" ? "span-2" : ""}>
              <select value={value} onChange={(e) => set(s, e.target.value)}>
                {!known && <option value={value}>{value} (not available here)</option>}
                {s.options?.map((o) => (
                  <option key={o.value} value={o.value} disabled={o.available === false}>
                    {o.label}
                    {o.available === false && o.reason ? ` — ${o.reason}` : ""}
                  </option>
                ))}
              </select>
            </Field>
          );
        }
        if (s.type === "bool") {
          return (
            <Field key={s.key} label={s.label} help={s.help}>
              <label className="check">
                <input type="checkbox" checked={Boolean(current ?? s.default)} onChange={(e) => set(s, e.target.checked)} />
                Enabled
              </label>
            </Field>
          );
        }
        const shown = current === undefined || current === null ? (s.nullable || s.default === null ? "" : String(s.default)) : String(current);
        return (
          <Field key={s.key} label={s.label} help={s.help}>
            <input
              type="number"
              step={s.type === "float" ? "0.01" : "1"}
              min={s.min}
              max={s.max}
              value={shown}
              placeholder={s.nullable ? "calibrated default" : undefined}
              onChange={(e) => {
                const raw = e.target.value;
                if (raw === "") set(s, undefined);
                else set(s, s.type === "int" ? parseInt(raw, 10) : parseFloat(raw));
              }}
            />
          </Field>
        );
      })}
    </>
  );
}
