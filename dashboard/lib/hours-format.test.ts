import { describe, expect, it } from "vitest";
import {
  formatHoursHM,
  formatTime12,
  hoursToMinutes,
  parseLocalStartMs,
  parseTimeInput,
} from "./hours-format";
import { aggregateByJob, computeMetrics, dailyTotals, groupByClient } from "./aggregations";
import type { TimeEntry } from "./types/time-entry";

describe("formatTime12", () => {
  it("formats 24h storage as AM/PM", () => {
    expect(formatTime12("09:05:00")).toBe("9:05 AM");
    expect(formatTime12("17:15:00")).toBe("5:15 PM");
    expect(formatTime12("00:00:00")).toBe("12:00 AM");
    expect(formatTime12("12:30:00")).toBe("12:30 PM");
  });

  it("round-trips with parseTimeInput", () => {
    const shown = formatTime12("13:45:00");
    expect(shown).toBe("1:45 PM");
    expect(parseTimeInput(shown)).toBe("13:45:00");
  });

  it("keeps stored 1 AM as AM", () => {
    expect(formatTime12("01:00:00")).toBe("1:00 AM");
  });
});

describe("parseTimeInput daytime defaults", () => {
  it("defaults 7–11 to AM and 12–6 to PM when AM/PM is omitted", () => {
    expect(parseTimeInput("9:00")).toBe("09:00:00");
    expect(parseTimeInput("7:00")).toBe("07:00:00");
    expect(parseTimeInput("11:30")).toBe("11:30:00");
    expect(parseTimeInput("1:00")).toBe("13:00:00");
    expect(parseTimeInput("6:15")).toBe("18:15:00");
    expect(parseTimeInput("12:00")).toBe("12:00:00");
  });

  it("lets explicit AM/PM and 24-hour times win", () => {
    expect(parseTimeInput("1:00 AM")).toBe("01:00:00");
    expect(parseTimeInput("9:00 PM")).toBe("21:00:00");
    expect(parseTimeInput("13:00")).toBe("13:00:00");
    expect(parseTimeInput("00:00")).toBe("00:00:00");
    expect(parseTimeInput("01:00")).toBe("01:00:00");
  });
});

describe("H:MM totals from stored hundredths", () => {
  it("adds displayed minutes so 0:05+0:30+0:15+0:50+1:35+0:20 is 3:35", () => {
    const hours = [0.08, 0.5, 0.25, 0.83, 1.58, 0.33];
    const entries = hours.map((h, i) => ({
      id: i,
      client: "3H TRUCKING, LLC",
      job_code: "Financial Stmts",
      hours: h,
    })) as TimeEntry[];
    expect(hours.map((h) => formatHoursHM(h))).toEqual([
      "0:05",
      "0:30",
      "0:15",
      "0:50",
      "1:35",
      "0:20",
    ]);
    const group = groupByClient(entries)[0];
    expect(formatHoursHM(group.subtotal)).toBe("3:35");
    expect(formatHoursHM(computeMetrics(entries).totalHours)).toBe("3:35");
    expect(formatHoursHM(aggregateByJob(entries, 8)[0].hours)).toBe("3:35");
    const day = dailyTotals(["2026-09-22"], entries.map((e) => ({ ...e, entry_date: "2026-09-22" })))[0];
    expect(formatHoursHM(day.total)).toBe("3:35");
    expect(hours.reduce((s, h) => s + hoursToMinutes(h), 0)).toBe(215);
  });
});

describe("parseLocalStartMs", () => {
  it("strips Z and parses as local wall clock", () => {
    const withZ = parseLocalStartMs("2026-09-16T14:00:00Z");
    const naive = parseLocalStartMs("2026-09-16T14:00:00");
    expect(withZ).toBe(naive);
    expect(Number.isNaN(withZ)).toBe(false);
  });

  it("strips numeric offsets", () => {
    const withOffset = parseLocalStartMs("2026-09-16T14:00:00-05:00");
    const naive = parseLocalStartMs("2026-09-16T14:00:00");
    expect(withOffset).toBe(naive);
  });
});
