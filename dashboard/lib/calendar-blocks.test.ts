import { describe, expect, it } from "vitest";
import { calendarAxisMinutes, splitScheduled, timeToMinutes } from "./calendar-blocks";
import type { TimeEntry } from "./types/time-entry";

const base: TimeEntry = {
  id: 1,
  staff_name: "Hannah Curtis",
  office: "GCD",
  client: "C1",
  job_code: "Bookkeeping",
  notes: "",
  entry_date: "2026-09-01",
  start_time: "09:00:00",
  end_time: "11:00:00",
  hours: 2,
  billable: true,
};

describe("calendar blocks", () => {
  it("splits timed rows from duration-only", () => {
    const unscheduled = { ...base, id: 2, start_time: null, end_time: null, hours: 1 };
    const { scheduled, unscheduled: rest } = splitScheduled([base, unscheduled]);
    expect(scheduled).toHaveLength(1);
    expect(rest).toHaveLength(1);
    expect(rest[0].id).toBe(2);
  });

  it("uses a full 12:00 AM–11:59 PM axis", () => {
    const axis = calendarAxisMinutes();
    expect(axis.start).toBe(0);
    expect(axis.end).toBe(24 * 60);
    expect(timeToMinutes("21:30:00")).toBeLessThan(axis.end);
  });
});
