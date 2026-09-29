/* The recognition clause of a rule (licensed modules):
 *
 *   OBJECT  Person   RECOGNITION  Any person | Anonymous person | Recognized person | Specific enrolled person
 *   OBJECT  Vehicle  PLATE        Any plate | Recognized plate | Registered vehicle | Specific plate
 */

import type { RecognitionPerson, RecognitionStatus, RecognitionVehicle, RuleSubject, SubjectMode } from "../api/types";
import { ANY_SUBJECT } from "../api/types";
import { Pill } from "../components/ui";
import { MODULE_STATE_LABEL } from "../lib/recognitionToken";

export interface RecognitionContext {
  status?: RecognitionStatus;
  people: RecognitionPerson[];
  vehicles: RecognitionVehicle[];
  groups: string[];
  hasToken: boolean;
}

const VEHICLES = new Set(["car", "motorcycle", "bus", "truck"]);

export function subjectDomain(classes: string[]): "person" | "vehicle" | "mixed" {
  if (classes.length === 0) return "mixed";
  if (classes.every((c) => c === "person")) return "person";
  if (classes.every((c) => VEHICLES.has(c))) return "vehicle";
  return "mixed";
}

const OPTIONS: Record<"person" | "vehicle" | "mixed", { id: SubjectMode; label: string }[]> = {
  person: [
    { id: "any", label: "Any person" },
    { id: "anonymous", label: "Anonymous person (nobody recognized)" },
    { id: "recognized", label: "Recognized person (any enrolled identity)" },
    { id: "specific", label: "Specific enrolled person" },
  ],
  vehicle: [
    { id: "any", label: "Any plate" },
    { id: "recognized", label: "Recognized plate (any plate read)" },
    { id: "registered", label: "Registered vehicle" },
    { id: "specific", label: "Specific plate or vehicle" },
  ],
  mixed: [
    { id: "any", label: "Any" },
    { id: "anonymous", label: "Anonymous (nobody / no plate recognized)" },
    { id: "recognized", label: "Recognized person or plate" },
    { id: "registered", label: "Registered vehicle" },
    { id: "specific", label: "Specific person, plate or vehicle" },
  ],
};

export function describeSubject(subject: RuleSubject | undefined, ctx?: RecognitionContext): string {
  const s = subject ?? ANY_SUBJECT;
  if (s.mode === "any") return "";
  if (s.mode === "specific") {
    const names = s.identity_ids.map((id) => ctx?.people.find((p) => p.id === id)?.display_name ?? id);
    const vehicles = s.vehicle_ids.map((id) => ctx?.vehicles.find((v) => v.id === id)?.plate ?? id);
    return ["is", [...names, ...vehicles, ...s.plates].join(" or ")].join(" ");
  }
  if (s.mode === "registered") return s.groups.length ? `belongs to group ${s.groups.join(" or ")}` : "is registered";
  return s.mode;
}

export default function SubjectClause({ classes, subject, onChange, ctx }: { classes: string[]; subject: RuleSubject | undefined; onChange: (s: RuleSubject) => void; ctx?: RecognitionContext }) {
  const domain = subjectDomain(classes);
  const s = subject ?? ANY_SUBJECT;
  const set = (patch: Partial<RuleSubject>) => onChange({ ...s, ...patch });
  const needs = domain === "person" ? ["face"] : domain === "vehicle" ? ["plate"] : ["face", "plate"];
  const states = ctx?.status?.modules;
  return (
    <div className="clause">
      <span className="kw">{domain === "vehicle" ? "PLATE" : "RECOGNITION"}</span>
      <div className="stack" style={{ gap: 6 }}>
        <div className="row wrap">
          <select value={s.mode} onChange={(e) => onChange({ ...ANY_SUBJECT, mode: e.target.value as SubjectMode })} style={{ width: 300 }}>
            {OPTIONS[domain].map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
          {s.mode !== "any" &&
            needs.map((m) => {
              const st = states?.[m as "face" | "plate"];
              if (!st) return null;
              return (
                <Pill key={m} tone={st.active ? "ok" : "warn"}>
                  {m === "face" ? "face recognition" : "plate recognition"}: {MODULE_STATE_LABEL[st.state]}
                </Pill>
              );
            })}
        </div>
        {s.mode === "specific" && domain !== "vehicle" && (
          <div className="row wrap" style={{ gap: 6 }}>
            <span className="small muted">Enrolled person:</span>
            {!ctx?.hasToken && <span className="hint">Sign in to Recognition (People page) to pick enrolled people.</span>}
            {ctx?.people.map((p) => (
              <label key={p.id} className="check">
                <input type="checkbox" checked={s.identity_ids.includes(p.id)} onChange={(e) => set({ identity_ids: e.target.checked ? [...s.identity_ids, p.id] : s.identity_ids.filter((x) => x !== p.id) })} />
                {p.display_name}
              </label>
            ))}
            {ctx?.hasToken && ctx.people.length === 0 && <span className="hint">No enrolled people yet.</span>}
          </div>
        )}
        {s.mode === "specific" && domain !== "person" && (
          <div className="row wrap" style={{ gap: 6 }}>
            <span className="small muted">Plate equals</span>
            <input type="text" value={s.plates.join(", ")} placeholder="ABC12345, DXB12567" onChange={(e) => set({ plates: e.target.value.split(",").map((p) => p.trim().toUpperCase().replace(/[^A-Z0-9]/g, "")).filter(Boolean) })} style={{ maxWidth: 260 }} />
            {ctx?.vehicles.map((v) => (
              <label key={v.id} className="check">
                <input type="checkbox" checked={s.vehicle_ids.includes(v.id)} onChange={(e) => set({ vehicle_ids: e.target.checked ? [...s.vehicle_ids, v.id] : s.vehicle_ids.filter((x) => x !== v.id) })} />
                {v.plate}
                {v.description ? ` (${v.description})` : ""}
              </label>
            ))}
          </div>
        )}
        {s.mode === "registered" && (
          <div className="row wrap" style={{ gap: 6 }}>
            <span className="small muted">belongs to group</span>
            {ctx?.groups.length ? (
              ctx.groups.map((g) => (
                <label key={g} className="check">
                  <input type="checkbox" checked={s.groups.includes(g)} onChange={(e) => set({ groups: e.target.checked ? [...s.groups, g] : s.groups.filter((x) => x !== g) })} />
                  {g}
                </label>
              ))
            ) : (
              <input type="text" value={s.groups.join(", ")} placeholder="any group (or type names)" onChange={(e) => set({ groups: e.target.value.split(",").map((g) => g.trim()).filter(Boolean) })} style={{ maxWidth: 260 }} />
            )}
          </div>
        )}
        {s.mode !== "any" && <span className="hint">The rule fires only when the identity or plate is known. Recognition may arrive a few seconds after the trigger; the event then keeps its original time. Without a licence the rule stays inactive.</span>}
      </div>
    </div>
  );
}
