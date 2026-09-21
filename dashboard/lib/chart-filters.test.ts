import { describe, expect, it } from "vitest";
import { applyChartFilters } from "./chart-filters";
import { computeMetrics } from "./aggregations";
import type { TimeEntry } from "./types/time-entry";

const sample: TimeEntry[] = [
  {
    id: 1,
    staff_name: "A",
    office: "GCD",
    client: "C1",
    job_code: "Admin",
    notes: "",
    entry_date: "2026-09-16",
    start_time: null,
    end_time: null,
    hours: 2,
    billable: true,
  },
  {
    id: 2,
    staff_name: "A",
    office: "GCD",
    client: "C2",
    job_code: "Bookkeeping",
    notes: "",
    entry_date: "2026-09-17",
    start_time: null,
    end_time: null,
    hours: 3,
    billable: true,
  },
];

describe("applyChartFilters + metrics", () => {
  it("day filter narrows metrics hours", () => {
    const filtered = applyChartFilters(sample, { day: "2026-09-17" });
    const m = computeMetrics(filtered);
    expect(m.totalHours).toBe(3);
    expect(m.clientCount).toBe(1);
  });

  it("client filter stacks with day", () => {
    const filtered = applyChartFilters(sample, { day: "2026-09-16", client: "C1" });
    expect(filtered).toHaveLength(1);
    expect(computeMetrics(filtered).totalHours).toBe(2);
  });
});
