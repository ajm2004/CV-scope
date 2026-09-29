import { describe, expect, it } from "vitest";
import type { AnomalySubject, ResolvedNames } from "../api/types";
import { anomalyText, effectiveThresholds, newAnomalyZone, tidy } from "./anomaly";

const subjects: AnomalySubject[] = [
  { alias: "Person A", track_id: 3, object_class: "person", kind: "enrolled_person", identity_id: "p_1", status: "recognized" },
  { alias: "Person B", track_id: 4, object_class: "person", kind: "anonymous_person", status: "unknown" },
  { alias: "Vehicle A", track_id: 9, object_class: "car", kind: "registered_vehicle", vehicle_id: "v_2", status: "recognized" },
];
const names: ResolvedNames = {
  identities: { p_1: { id: "p_1", display_name: "Employee 017", reference_id: null, active: true, enrollment_status: "ready" } },
  vehicles: { v_2: { id: "v_2", plate: "ABC123", label: "Delivery van", groups: [], active: true } },
  missing: [],
};

describe("anomaly descriptions", () => {
  it("shows names only when the recognition API resolved them", () => {
    const text = "[Person A] (recognized person) met [Person B] next to [Vehicle A].";
    expect(anomalyText(text, subjects, names)).toBe("Employee 017 (recognized person) met a person next to Delivery van.");
    expect(tidy(anomalyText(text, subjects, null))).toBe("A recognized person met a person next to a registered vehicle.");
  });

  it("leaves unknown aliases and plain text alone", () => {
    expect(anomalyText("[Animal A] entered the barn.", subjects, null)).toBe("Animal A entered the barn.");
    expect(anomalyText(null, subjects, null)).toBe("");
  });

  it("uses the preset unless a zone sets its own threshold", () => {
    const z = { ...newAnomalyZone("frame", "Whole picture"), sensitivity: "high" as const, persistence_s: 10 };
    expect(effectiveThresholds(z)).toMatchObject({ persistence_s: 10, min_area_pct: 0.3, k_sigma: 2.5 });
  });
});
