import { describe, expect, it } from "vitest";
import { addHoursToTime, subtractHoursFromTime } from "./hours-format";
import { reconcileTimeFields } from "./time-field-sync";

describe("addHoursToTime / subtractHoursFromTime", () => {
  it("adds duration onto start", () => {
    expect(addHoursToTime("00:00:00", 0.25)).toBe("00:15:00");
  });

  it("subtracts duration from end", () => {
    expect(subtractHoursFromTime("00:15:00", 0.25)).toBe("00:00:00");
  });
});

describe("reconcileTimeFields", () => {
  it("updates duration when start changes and end is set", () => {
    const r = reconcileTimeFields({
      startHm: "09:00",
      endHm: "10:30",
      hoursHm: "1:00",
      touched: "start",
    });
    expect(r.hoursHm).toBe("1:30");
    expect(r.hours).toBe(1.5);
    expect(r.endHm).toBe("10:30 AM");
  });

  it("updates end when duration changes and start is set", () => {
    const r = reconcileTimeFields({
      startHm: "00:00",
      endHm: "00:05",
      hoursHm: "0:15",
      touched: "duration",
    });
    expect(r.endHm).toBe("12:15 AM");
    expect(r.hours).toBe(0.25);
    expect(r.startHm).toBe("12:00 AM");
  });

  it("updates duration when end changes and start is set", () => {
    const r = reconcileTimeFields({
      startHm: "00:00",
      endHm: "00:10",
      hoursHm: "0:05",
      touched: "end",
    });
    expect(r.hoursHm).toBe("0:10");
    expect(r.hours).toBeCloseTo(10 / 60, 5);
  });

  it("does not clobber siblings on incomplete start type", () => {
    const r = reconcileTimeFields({
      startHm: "00:1",
      endHm: "00:05",
      hoursHm: "0:05",
      touched: "start",
    });
    expect(r.startHm).toBe("00:1");
    expect(r.endHm).toBe("00:05");
    expect(r.hoursHm).toBe("0:05");
  });

  it("handles overnight start/end for duration", () => {
    const r = reconcileTimeFields({
      startHm: "23:00",
      endHm: "01:00",
      hoursHm: "0:00",
      touched: "end",
    });
    expect(r.hoursHm).toBe("2:00");
    expect(r.hours).toBe(2);
  });

  it("sets end from start + duration when end empty", () => {
    const r = reconcileTimeFields({
      startHm: "09:00",
      endHm: "",
      hoursHm: "1:00",
      touched: "start",
    });
    expect(r.endHm).toBe("10:00 AM");
    expect(r.hoursHm).toBe("1:00");
  });
});
