/* Anomaly Assistant: defaults, labels and the names behind [Person A] placeholders.
 *
 * Descriptions refer to people and vehicles by aliases such as [Person A].
 * The stored subject carries only the recognition ids and status; a viewer
 * who holds a recognition token sees the enrolled name, everybody else an
 * anonymous phrase ("a recognized person"). */

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "../api/client";
import type { AnomalyKind, AnomalyRecord, AnomalySettings, AnomalySubject, AnomalyZoneSettings, ResolvedNames } from "../api/types";
import { useRecognitionAuth } from "./recognitionToken";

export const FRAME_ZONE_ID = "frame";

export const ANOMALY_KINDS: { id: AnomalyKind; label: string; help: string }[] = [
  { id: "presence", label: "Presence", help: "A tracked person, vehicle or animal is inside" },
  { id: "motion", label: "Movement", help: "Something moves that no tracked object explains" },
  { id: "appeared", label: "Object appeared", help: "Something new stays in place" },
  { id: "disappeared", label: "Object removed", help: "Something that belongs there is gone" },
  { id: "moved", label: "Object moved", help: "Something is now in another place" },
  { id: "changed", label: "Scene changed", help: "Opened, disturbed, rearranged" },
];

export const KIND_LABEL: Record<string, string> = {
  presence: "Presence",
  motion: "Movement",
  appeared: "Object appeared",
  disappeared: "Object removed",
  moved: "Object moved",
  changed: "Scene changed",
  lighting: "Lighting changed",
  tamper: "Camera blocked or moved",
};

export const SENSITIVITY_PRESETS: Record<"low" | "medium" | "high", { k_sigma: number; min_contrast: number; min_area_pct: number; persistence_s: number; min_confidence: number }> = {
  low: { k_sigma: 5.0, min_contrast: 28, min_area_pct: 2.0, persistence_s: 4.0, min_confidence: 0.6 },
  medium: { k_sigma: 3.5, min_contrast: 20, min_area_pct: 0.8, persistence_s: 2.5, min_confidence: 0.5 },
  high: { k_sigma: 2.5, min_contrast: 14, min_area_pct: 0.3, persistence_s: 1.5, min_confidence: 0.4 },
};

export const VALIDATION_LABEL: Record<string, string> = {
  deterministic: "Computer vision only",
  assisted: "Model describes",
  confirmed: "Model must confirm",
};

export const STATUS_LABEL: Record<string, string> = {
  raised: "Raised",
  awaiting_model: "Waiting for the model",
  dismissed: "Dismissed by the model",
  held: "Held",
};

export const DEFAULT_ANOMALY: AnomalySettings = {
  enabled: false,
  zones: [],
  analysis_fps: 4,
  learn_s: 8,
  adapt_minutes: 10,
  working_width: 320,
  use_ignore_regions: true,
  lighting_events: false,
  tamper_events: true,
  recognition: true,
  on_llm_failure: "raise",
};

export function newAnomalyZone(id: string, name: string): AnomalyZoneSettings {
  return {
    id,
    name,
    enabled: true,
    expected_state: "",
    sensitivity: "medium",
    k_sigma: null,
    min_contrast: null,
    min_area_pct: null,
    persistence_s: null,
    min_confidence: null,
    detect: ANOMALY_KINDS.map((k) => k.id),
    presence_classes: [],
    accept_after_s: 120,
    cooldown_s: 10,
    validation: "deterministic",
    interpret_at: "confirm",
    webhooks: [],
    record_clip: true,
  };
}

/** Thresholds a zone uses: its preset with its own values on top. */
export function effectiveThresholds(z: AnomalyZoneSettings) {
  const base = SENSITIVITY_PRESETS[z.sensitivity === "custom" ? "medium" : z.sensitivity];
  return {
    k_sigma: z.k_sigma ?? base.k_sigma,
    min_contrast: z.min_contrast ?? base.min_contrast,
    min_area_pct: z.min_area_pct ?? base.min_area_pct,
    persistence_s: z.persistence_s ?? base.persistence_s,
    min_confidence: z.min_confidence ?? base.min_confidence,
  };
}

/** Recognition names for the subjects of these anomalies (token holders only). */
export function useAnomalyNames(records: AnomalyRecord[] | undefined) {
  const token = useRecognitionAuth((s) => s.token);
  const { identity_ids, vehicle_ids } = useMemo(() => {
    const people = new Set<string>();
    const vehicles = new Set<string>();
    for (const r of records ?? []) {
      for (const s of r.subjects) {
        if (s.identity_id) people.add(s.identity_id);
        if (s.vehicle_id) vehicles.add(s.vehicle_id);
      }
    }
    return { identity_ids: [...people].sort(), vehicle_ids: [...vehicles].sort() };
  }, [records]);
  return useQuery({
    queryKey: ["recognition-resolve", identity_ids, vehicle_ids],
    queryFn: () => api.recognition.resolve({ identity_ids, vehicle_ids }),
    enabled: !!token && (identity_ids.length > 0 || vehicle_ids.length > 0),
    staleTime: 60_000,
    retry: 0,
  });
}

const PLACEHOLDER = /\[((?:Person|Vehicle|Animal|Object) [A-Z]{1,2})\]/g;

/** Replace [Person A] with the name (token holders) or an anonymous phrase. */
export function anomalyText(text: string | null | undefined, subjects: AnomalySubject[], names?: ResolvedNames | null): string {
  if (!text) return "";
  const byAlias = new Map(subjects.map((s) => [s.alias, s]));
  return text.replace(PLACEHOLDER, (whole, alias: string) => {
    const s = byAlias.get(alias);
    if (!s) return alias;
    if (s.identity_id && names?.identities[s.identity_id]) return names.identities[s.identity_id].display_name;
    if (s.vehicle_id && names?.vehicles[s.vehicle_id]) return names.vehicles[s.vehicle_id].label;
    if (s.kind === "enrolled_person") return "a recognized person";
    if (s.kind === "registered_vehicle") return "a registered vehicle";
    return `a ${s.object_class}`;
  });
}

/** Tidy "a recognized person (recognized person)" after an anonymous replacement. */
export function tidy(text: string): string {
  return text
    .replace(/a recognized person \(recognized person\)/g, "a recognized person")
    .replace(/a registered vehicle \(registered vehicle\)/g, "a registered vehicle")
    .replace(/(^|\. )a /g, (m, p) => `${p}A `);
}
