/* The HAS RELATIONSHIP clause of a rule (relationship engine):
 *
 *   AND HAS RELATIONSHIP  ASSOCIATED_WITH  with  Person  (Recognized person is Employee-017)
 *                         at least likely, now or in the last 300 s
 */

import type { Rule, RuleRelation } from "../api/types";
import { ANY_SUBJECT } from "../api/types";
import { ClassPicker } from "../components/ui";
import { CLASS_OPTIONS } from "../lib/format";
import { useMeta } from "../relationships/bits";
import SubjectClause, { type RecognitionContext } from "./SubjectClause";

export function newRelation(): RuleRelation {
  return { relation: "ASSOCIATED_WITH", direction: "any", other_classes: ["person"], other: { ...ANY_SUBJECT }, other_places: [], min_state: "likely", recent_s: 300 };
}

export default function RelationClause({ rule, onChange, ctx, enabled }: { rule: Rule; onChange: (r: RuleRelation | null) => void; ctx?: RecognitionContext; enabled: boolean }) {
  const meta = useMeta();
  const r = rule.relation;
  if (!r) {
    return (
      <div className="clause">
        <span className="kw">AND</span>
        <span className="row">
          <button className="btn sm ghost" onClick={() => onChange(newRelation())}>
            + has relationship…
          </button>
          {!enabled && <span className="hint">Needs Relationships turned on for this experiment.</span>}
        </span>
      </div>
    );
  }
  const set = (patch: Partial<RuleRelation>) => onChange({ ...r, ...patch });
  const types = (meta.data?.relation_types ?? []).filter((t) => !t.external_only);
  return (
    <>
      <div className="clause">
        <span className="kw">AND HAS RELATIONSHIP</span>
        <span className="row wrap">
          <select value={r.relation} onChange={(e) => set({ relation: e.target.value })} style={{ width: 200 }}>
            {types.map((t) => (
              <option key={t.id} value={t.id}>
                {t.id}
              </option>
            ))}
            {!types.some((t) => t.id === r.relation) && <option value={r.relation}>{r.relation}</option>}
          </select>
          <select value={r.direction} onChange={(e) => set({ direction: e.target.value as RuleRelation["direction"] })} style={{ width: 170 }}>
            <option value="any">in either direction</option>
            <option value="outgoing">as its subject</option>
            <option value="incoming">as its object</option>
          </select>
          <span className="small muted">at least</span>
          <select value={r.min_state} onChange={(e) => set({ min_state: e.target.value as RuleRelation["min_state"] })} style={{ width: 110 }}>
            <option value="confirmed">confirmed</option>
            <option value="likely">likely</option>
            <option value="possible">possible</option>
          </select>
          <span className="small muted">still holding or ended at most</span>
          <input type="number" min={1} value={r.recent_s ?? ""} placeholder="any time" onChange={(e) => set({ recent_s: e.target.value ? Number(e.target.value) : null })} style={{ width: 80 }} />
          <span className="small muted">s ago</span>
          <button className="btn sm ghost" onClick={() => onChange(null)}>
            Remove
          </button>
        </span>
      </div>
      <div className="clause">
        <span className="kw">WITH</span>
        <ClassPicker value={r.other_classes} onChange={(other_classes) => set({ other_classes })} options={CLASS_OPTIONS} />
      </div>
      <SubjectClause classes={r.other_classes} subject={r.other} onChange={(other) => set({ other })} ctx={ctx} />
      {!enabled && (
        <div className="clause">
          <span />
          <span className="hint">This clause needs Relationships turned on for the experiment; until then the rule stays inactive.</span>
        </div>
      )}
    </>
  );
}
