import { describe, expect, it } from "vitest";
import { computeMetrics, aggregateByClient, groupByStaff } from "./aggregations";
import type { TimeEntry } from "./types/time-entry";

const sample: TimeEntry[] = [
  { id: 1, staff_name: "A", office: "GCD", client: "C1", job_code: "Admin", notes: "", entry_date: "2026-08-01", start_time: null, end_time: null, hours: 1, billable: false },
  { id: 2, staff_name: "A", office: "GCD", client: "C2", job_code: "Bookkeeping", notes: "", entry_date: "2026-08-01", start_time: null, end_time: null, hours: 2, billable: true },
];

describe("aggregations", () => {
  it("computes admin metrics", () => {
    const m = computeMetrics(sample);
    expect(m.adminHours).toBe(1);
    expect(m.clientCount).toBe(2);
    expect(m.adminPercent).toBe(33);
  });

  it("caps client chart at 8", () => {
    const many = Array.from({ length: 12 }, (_, i) => ({
      ...sample[0],
      id: i + 1,
      client: `Client ${i}`,
      hours: 12 - i,
    }));
    expect(aggregateByClient(many, 8)).toHaveLength(8);
  });

  it("groups day detail by staff_name", () => {
    const mixed = [
      sample[0],
      { ...sample[1], staff_name: "Hannah Curtis" },
    ];
    const groups = groupByStaff(mixed);
    expect(groups.map((g) => g.staff_name)).toEqual(["A", "Hannah Curtis"]);
  });
});
