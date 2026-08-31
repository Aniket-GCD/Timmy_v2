import { describe, expect, it } from "vitest";
import { decimalHoursToHM, durationHoursFromTimes, formatPercent } from "./hours-format";

describe("hours-format", () => {
  it("formats decimal hours as h:mm", () => {
    expect(decimalHoursToHM(1.5)).toBe("1:30");
    expect(decimalHoursToHM(0.75)).toBe("0:45");
  });

  it("computes duration from times", () => {
    expect(durationHoursFromTimes("09:00:00", "10:30:00")).toBe(1.5);
  });

  it("formats percent", () => {
    expect(formatPercent(2, 8)).toBe("25%");
  });
});
