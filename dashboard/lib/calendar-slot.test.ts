import { describe, expect, it } from "vitest";
import { minutesToTime, slotFromDayColumnClick, snapMinutes } from "./calendar-slot";

describe("calendar-slot", () => {
  it("snaps down to 15 minutes", () => {
    expect(snapMinutes(67)).toBe(60);
    expect(snapMinutes(0)).toBe(0);
  });

  it("formats minutes as HH:MM:SS", () => {
    expect(minutesToTime(90)).toBe("01:30:00");
  });

  it("maps click Y to a 1-hour snapped slot", () => {
    // Midway through 24h axis at 720px height → noon-ish
    const slot = slotFromDayColumnClick(360, 720);
    expect(slot.start_time.endsWith(":00")).toBe(true);
    expect(slot.end_time > slot.start_time).toBe(true);
  });
});
