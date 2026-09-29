import { describe, expect, it } from "vitest";
import { ANY_SUBJECT } from "../api/types";
import { describeSubject, subjectDomain } from "./SubjectClause";

describe("rule subject clause", () => {
  it("derives the recognition domain from the rule's classes", () => {
    expect(subjectDomain([])).toBe("mixed");
    expect(subjectDomain(["person"])).toBe("person");
    expect(subjectDomain(["car", "truck"])).toBe("vehicle");
    expect(subjectDomain(["person", "car"])).toBe("mixed");
  });

  it("describes a subject in words", () => {
    const ctx = { people: [{ id: "p1", display_name: "Employee 001" } as never], vehicles: [{ id: "v1", plate: "ABC12345" } as never], groups: [], hasToken: true };
    expect(describeSubject(undefined)).toBe("");
    expect(describeSubject({ ...ANY_SUBJECT, mode: "recognized" })).toBe("recognized");
    expect(describeSubject({ ...ANY_SUBJECT, mode: "specific", identity_ids: ["p1"] }, ctx)).toBe("is Employee 001");
    expect(describeSubject({ ...ANY_SUBJECT, mode: "specific", plates: ["XYZ999"], vehicle_ids: ["v1"] }, ctx)).toBe("is ABC12345 or XYZ999");
    expect(describeSubject({ ...ANY_SUBJECT, mode: "registered", groups: ["Delivery Fleet"] })).toBe("belongs to group Delivery Fleet");
    expect(describeSubject({ ...ANY_SUBJECT, mode: "registered" })).toBe("is registered");
  });
});
