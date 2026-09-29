/* Choose an entity by typing part of its label. */

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useRecognitionAuth } from "../lib/recognitionToken";
import { rel, type EntityOut } from "./api";

export default function EntityPicker({ value, onChange, types, placeholder = "Type to search…", experimentId }: { value: EntityOut | null; onChange: (e: EntityOut | null) => void; types?: string; placeholder?: string; experimentId?: number }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const token = useRecognitionAuth((s) => s.token);
  const list = useQuery({
    queryKey: ["rel-entity-picker", q, types, experimentId, token],
    queryFn: () => rel.entities({ q: q || undefined, type: types, experiment_id: experimentId, limit: 30 }),
    enabled: open,
  });
  if (value && !open) {
    return (
      <span className="row" style={{ gap: 6 }}>
        <strong>{value.label}</strong>
        <span className="hint">{value.type_label}</span>
        <button className="btn sm ghost" onClick={() => { onChange(null); setOpen(true); }}>
          Change
        </button>
      </span>
    );
  }
  return (
    <div style={{ position: "relative", minWidth: 260 }}>
      <input type="search" value={q} placeholder={placeholder} onFocus={() => setOpen(true)} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onBlur={() => setTimeout(() => setOpen(false), 150)} />
      {open && (
        <ul className="rel-entity-list" style={{ position: "absolute", zIndex: 20, left: 0, right: 0, background: "var(--surface)", border: "1px solid var(--line)", maxHeight: 280 }}>
          {list.data?.filter((e) => e.key).map((e) => (
            <li key={e.key!}>
              <button onMouseDown={(ev) => ev.preventDefault()} onClick={() => { onChange(e); setOpen(false); setQ(""); }}>
                <span>{e.label}</span>
                <span className="hint">{e.type_label}{e.last_seen ? ` · ${new Date(e.last_seen).toLocaleString()}` : ""}</span>
              </button>
            </li>
          ))}
          {list.data && list.data.length === 0 && <li className="hint" style={{ padding: 8 }}>No match.</li>}
        </ul>
      )}
    </div>
  );
}
