import { describe, expect, it } from "vitest";
import { computeMetrics, aggregateByClient, groupByStaff } from "./aggregations";
import type { TimeEntry } from "./types/time-entry";

const sample: TimeEntry[] = [
  { id: 1, staff_name: "A", office: "GCD", client: "Admin", job_code: "Administrative", notes: "", entry_date: "2026-08-01", start_time: null, end_time: null, hours: 1, billable: false },
  { id: 2, staff_name: "A", office: "GCD", client: "C2", job_code: "Bookkeeping", notes: "", entry_date: "2026-08-01", start_time: null, end_time: null, hours: 2, billable: true },
];

describe("aggregations", () => {
  it("computes admin metrics", () => {
    const m = computeMetrics(sample);
    expect(m.adminHours).toBe(1);
    expect(m.clientCount).toBe(2);
    expect(m.adminPercent).toBe(33);
  });

  it("counts only Admin client for admin metrics", () => {
    const rows: TimeEntry[] = [
      {
        id: 1,
        staff_name: "N",
        office: "GCD",
        client: "Admin",
        job_code: "Administrative",
        notes: "",
        entry_date: "2026-09-09",
        start_time: null,
        end_time: null,
        hours: 0.5,
        billable: true,
      },
      {
        id: 2,
        staff_name: "N",
        office: "GCD",
        client: "TRI STATE",
        job_code: "Consulting",
        notes: "",
        entry_date: "2026-09-10",
        start_time: null,
        end_time: null,
        hours: 0.17,
        billable: true,
      },
    ];
    const m = computeMetrics(rows);
    expect(m.adminHours).toBe(0.5);
    expect(m.adminPercent).toBe(75);
  });

  it("excludes Staff Meeting with Administrative job code from admin metrics", () => {
    const rows: TimeEntry[] = [
      {
        id: 1,
        staff_name: "N",
        office: "GCD",
        client: "Staff Meeting",
        job_code: "Administrative",
        notes: "Timmy Time demo",
        entry_date: "2026-09-29",
        start_time: null,
        end_time: null,
        hours: 0.67,
        billable: false,
      },
      {
        id: 2,
        staff_name: "N",
        office: "GCD",
        client: "MCGUIRE, CHARLES T",
        job_code: "1040",
        notes: "",
        entry_date: "2026-09-29",
        start_time: null,
        end_time: null,
        hours: 2,
        billable: true,
      },
    ];
    const m = computeMetrics(rows);
    expect(m.adminHours).toBe(0);
    expect(m.adminPercent).toBe(0);
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
