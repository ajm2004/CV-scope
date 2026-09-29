/* Looks: the same person enrolled again in another appearance.
 *
 * One enrollment session covers one look — the person as they were that day.
 * Glasses, a hard hat, a beard, a uniform or a very different light change the
 * picture enough that a single session can miss them later, so the profile can
 * hold several looks. Every look keeps its own views and is checked against
 * the first enrollment, so a second person can never be added by mistake. */

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import type { RecognitionPerson } from "../api/types";
import { api } from "../api/client";
import { ConfirmButton, ErrorNotice, Field, Notice, Pill } from "../components/ui";
import { num } from "../lib/format";

const SUGGESTIONS = ["Glasses", "Sunglasses off", "Hat", "Hard hat", "Mask", "Beard", "Work clothes", "Evening light", "Night"];

export function lookLabel(name: string): string {
  return name || "First enrollment";
}

export default function EnrollmentLooks({ person, look, onChange, canEdit, onChanged }: { person: RecognitionPerson; look: string; onChange: (look: string) => void; canEdit: boolean; onChanged: (p: RecognitionPerson) => void }) {
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const looks = person.looks ?? [];
  const known = looks.map((l) => l.name);
  const remove = useMutation({
    mutationFn: (name: string) => api.recognition.deleteLook(person.id, name),
    onSuccess: (p) => {
      if (!(p.looks ?? []).some((l) => l.name === look)) onChange("");
      onChanged(p);
    },
  });
  const start = () => {
    const name = draft.trim();
    if (!name) return;
    setAdding(false);
    setDraft("");
    onChange(name);
  };
  const chips = known.includes(look) ? known : [...known, look];
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="row wrap" style={{ gap: 6 }}>
        <span className="small muted">Look:</span>
        {(chips.length ? chips : [""]).map((name) => {
          const info = looks.find((l) => l.name === name);
          return (
            <button key={name} className={`btn sm ${look === name ? "active" : ""}`} onClick={() => onChange(name)} title={info ? `${info.templates} templates · views ${info.views.join(", ")}` : "New look, nothing captured yet"}>
              {lookLabel(name)}
              {info ? ` (${info.templates})` : ""}
            </button>
          );
        })}
        {canEdit && !adding && (
          <button className="btn sm" onClick={() => setAdding(true)}>
            + Add another look
          </button>
        )}
        {canEdit && look !== "" && known.includes(look) && (
          <ConfirmButton label={`Delete "${look}"`} confirm={`Delete the look "${look}" with its pictures and templates? The rest of the enrollment stays.`} onConfirm={() => remove.mutate(look)} className="btn sm ghost" />
        )}
      </div>
      {adding && (
        <div className="inline-form">
          <Field label="Name of the look">
            <input autoFocus type="text" value={draft} placeholder="Glasses" list="pathscope-look-suggestions" onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => e.key === "Enter" && start()} />
            <datalist id="pathscope-look-suggestions">
              {SUGGESTIONS.filter((s) => !known.includes(s)).map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
          </Field>
          <button className="btn primary" disabled={!draft.trim() || known.includes(draft.trim())} onClick={start}>
            Start this look
          </button>
          <button className="btn" onClick={() => { setAdding(false); setDraft(""); }}>
            Cancel
          </button>
          <span className="hint">Capture the same views again in the new appearance. The templates are added to this person, never replaced.</span>
        </div>
      )}
      {remove.isError && <ErrorNotice error={remove.error} />}
      {look !== "" && !known.includes(look) && (
        <Notice>
          New look <strong>{look}</strong>: capture the views again as the person looks now. Finish with <em>Finish and check quality</em> so the templates are taken into account.
        </Notice>
      )}
      {looks.length > 1 && (
        <div className="row wrap" style={{ gap: 10 }}>
          {looks.map((l) => (
            <span key={l.name} className="small muted">
              <Pill tone={l.link_to_first != null && l.link_to_first < 0.35 ? "warn" : ""}>{lookLabel(l.name)}</Pill> {l.templates} templates
              {l.consistency != null ? ` · own agreement ${num(l.consistency, 2)}` : ""}
              {l.link_to_first != null ? ` · matches the first enrollment at ${num(l.link_to_first, 2)}` : ""}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
