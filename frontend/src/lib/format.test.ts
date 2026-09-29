import { describe, expect, it } from "vitest";
import { bytes, classLabel, clock, eventLabel, num, pct, seconds } from "./format";

describe("format helpers", () => {
  it("formats bytes", () => {
    expect(bytes(0)).toBe("0 B");
    expect(bytes(1536)).toBe("1.5 KB");
    expect(bytes(12 * 1024 ** 3)).toBe("12.0 GB");
    expect(bytes(null)).toBe("–");
  });

  it("formats durations", () => {
    expect(seconds(4.25)).toBe("4.3 s");
    expect(seconds(90)).toBe("1m 30s");
    expect(seconds(3660)).toBe("1h 1m");
    expect(seconds(undefined)).toBe("–");
  });

  it("formats media clocks", () => {
    expect(clock(0)).toBe("00:00.0");
    expect(clock(65.4)).toBe("01:05.4");
    expect(clock(3725)).toBe("1:02:05.0");
    expect(clock(null)).toBe("--:--");
  });

  it("formats numbers and percentages", () => {
    expect(num(3.14159, 2)).toBe("3.14");
    expect(pct(12.345)).toBe("12.3%");
    expect(num(null)).toBe("–");
  });

  it("maps labels", () => {
    expect(classLabel("person")).toBe("Person");
    expect(classLabel("hot_dog")).toBe("Hot Dog");
    expect(eventLabel("zone_entry")).toBe("Zone entry");
    expect(eventLabel("route")).toBe("Route");
  });
});
