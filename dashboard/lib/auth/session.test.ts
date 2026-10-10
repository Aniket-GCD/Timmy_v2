import { describe, expect, it } from "vitest";
import { findEmployeeByEmail, mapEmployeeRow } from "./session";
import { applyChartFilters } from "../chart-filters";
import type { Employee } from "../types/employee";

describe("findEmployeeByEmail", () => {
  const roster: Employee[] = [
    {
      id: "1",
      first_name: "Hannah",
      last_name: "Curtis",
      staff_name: "Hannah Curtis",
      office: "GCD",
      active: true,
      email: "Hannah@Firm.com",
      is_admin: true,
      can_view_time_by_job: true,
    },
    {
      id: "2",
      first_name: "Alex",
      last_name: "Daley",
      staff_name: "Alex Daley",
      office: "GCD",
      active: false,
      email: "alex@firm.com",
      is_admin: false,
      can_view_time_by_job: false,
    },
  ];

  it("matches case-insensitively", () => {
    expect(findEmployeeByEmail(roster, "hannah@firm.com")?.staff_name).toBe("Hannah Curtis");
  });

  it("ignores inactive", () => {
    expect(findEmployeeByEmail(roster, "alex@firm.com")).toBeNull();
  });

  it("returns null for unknown", () => {
    expect(findEmployeeByEmail(roster, "nobody@firm.com")).toBeNull();
  });
});

describe("mapEmployeeRow", () => {
  it("keeps can_view_time_by_job only when the column is true", () => {
    expect(mapEmployeeRow({ can_view_time_by_job: true }).can_view_time_by_job).toBe(true);
    expect(mapEmployeeRow({ can_view_time_by_job: "true" }).can_view_time_by_job).toBe(false);
    expect(mapEmployeeRow({ can_view_time_by_job: 1 }).can_view_time_by_job).toBe(false);
    expect(mapEmployeeRow({}).can_view_time_by_job).toBe(false);
  });
});

describe("applyChartFilters", () => {
  const rows = [
    { entry_date: "2026-09-04", client: "Acme", job_code: "books" },
    { entry_date: "2026-09-04", client: "Beta", job_code: "tax" },
    { entry_date: "2026-09-05", client: "Acme", job_code: "books" },
  ];

  it("filters by day client and job", () => {
    expect(applyChartFilters(rows, { day: "2026-09-04" })).toHaveLength(2);
    expect(applyChartFilters(rows, { client: "Acme" })).toHaveLength(2);
    expect(applyChartFilters(rows, { job: "tax" })).toHaveLength(1);
    expect(
      applyChartFilters(rows, { day: "2026-09-04", client: "Acme", job: "books" }),
    ).toHaveLength(1);
  });
});
