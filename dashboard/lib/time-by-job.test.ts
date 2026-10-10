import { describe, expect, it } from "vitest";
import { lastMonthRange, thisMonthRange } from "./dates";
import {
  formatDecimalHours,
  formatReportDate,
  formatUsDate,
  parseUsDate,
  groupTimeByJob,
  monthSubtitle,
  toCsv,
  type TimeByJobFilters,
} from "./time-by-job";
import type { TimeEntry } from "./types/time-entry";

const baseFilters: TimeByJobFilters = {
  clients: [],
  jobCodes: [],
  staff: [],
  offices: [],
  search: "",
  detailSort: "date",
};

function row(partial: Pick<TimeEntry, "id" | "entry_date" | "job_code" | "hours" | "billable" | "notes"> & Partial<TimeEntry>): TimeEntry {
  return {
    staff_name: "Ashley Klugman",
    office: "GCD",
    client: "Cathys Barber Studio LLC",
    start_time: null,
    end_time: null,
    ...partial,
  };
}

/** Minute-exact hours from the Time by Job screenshot. */
const screenshot: TimeEntry[] = [
  row({ id: 1, entry_date: "2026-08-18", job_code: "Administrative", hours: 15 / 60, billable: false, notes: "research how DBA name should appear in QBO" }),
  row({ id: 2, entry_date: "2026-08-20", job_code: "Client Meeting", hours: 90 / 60, billable: true, notes: "connect bank acct. Had to import missing bc wells fargo" }),
  row({ id: 3, entry_date: "2026-08-19", job_code: "Client Meeting", hours: 25 / 60, billable: true, notes: "set up QBO/ import COA" }),
  row({ id: 4, entry_date: "2026-08-24", job_code: "Email", hours: 5 / 60, billable: true, notes: "respond to client question" }),
  row({ id: 5, entry_date: "2026-08-13", job_code: "Email", hours: 15 / 60, billable: false, notes: "email with client to set up QBO creation" }),
  row({ id: 6, entry_date: "2026-08-17", job_code: "Email", hours: 5 / 60, billable: true, notes: "email time for QBO set up" }),
];

describe("groupTimeByJob", () => {
  it("groups the screenshot into activity totals that sum to 2:35", () => {
    const grouped = groupTimeByJob(screenshot, baseFilters);
    expect(grouped.clients).toHaveLength(1);
    const [client] = grouped.clients;
    expect(client.name).toBe("Cathys Barber Studio LLC");
    expect(client.activities.map((a) => a.name)).toEqual(["Administrative", "Client Meeting", "Email"]);
    expect(client.activities.map((a) => a.totalMinutes)).toEqual([15, 115, 25]);
    expect(client.totalMinutes).toBe(155);
    expect(grouped.totalMinutes).toBe(155);
    expect(formatDecimalHours(client.activities[0].totalHours)).toBe("0.25");
    expect(formatDecimalHours(client.activities[1].totalHours)).toBe("1.92");
    expect(formatDecimalHours(client.activities[2].totalHours)).toBe("0.42");
    expect(formatDecimalHours(client.totalHours)).toBe("2.58");
    expect(formatDecimalHours(grouped.totalHours)).toBe("2.58");
    expect(client.activities[2].entries.map((e) => e.entry_date)).toEqual([
      "2026-08-13",
      "2026-08-17",
      "2026-08-24",
    ]);
    const csv = toCsv(grouped);
    expect(csv.split("\n")[0]).toBe("client,activity,date,name,duration,hours,notes");
    expect(csv).toContain("Total Administrative,,,0:15,0.25,");
    expect(csv).toContain("TOTAL,,,,2:35,2.58,");
  });

  it("search drops other groups and recomputes the client total", () => {
    const grouped = groupTimeByJob(screenshot, { ...baseFilters, search: "wells fargo" });
    expect(grouped.clients).toHaveLength(1);
    expect(grouped.clients[0].activities.map((a) => a.name)).toEqual(["Client Meeting"]);
    expect(grouped.clients[0].totalMinutes).toBe(90);
    expect(grouped.totalMinutes).toBe(90);
  });

  it("drops a client omitted from the multi-select", () => {
    const other = row({
      id: 7,
      entry_date: "2026-08-18",
      job_code: "Email",
      hours: 10 / 60,
      billable: true,
      notes: "other shop",
      client: "Other Shop LLC",
    });
    const grouped = groupTimeByJob([...screenshot, other], {
      ...baseFilters,
      clients: ["Other Shop LLC"],
    });
    expect(grouped.clients.map((c) => c.name)).toEqual(["Other Shop LLC"]);
  });

  it("keeps only the selected job code and recomputes the total", () => {
    const grouped = groupTimeByJob(screenshot, { ...baseFilters, jobCodes: ["Email"] });
    expect(grouped.clients[0].activities.map((a) => a.name)).toEqual(["Email"]);
    expect(grouped.totalMinutes).toBe(25);
    expect(formatDecimalHours(grouped.totalHours)).toBe("0.42");
  });
});

describe("report labels", () => {
  it("formats dates and a single-month subtitle", () => {
    expect(formatReportDate("2026-08-18")).toBe("August 18, 2026");
    expect(formatUsDate("2026-10-01")).toBe("10-01-2026");
    expect(parseUsDate("10-01-2026")).toBe("2026-10-01");
    expect(parseUsDate("02-31-2026")).toBeNull();
    expect(monthSubtitle("2026-08-01", "2026-08-31")).toBe("August 2026");
    expect(monthSubtitle("2026-08-01", "2026-09-15")).toBe("August 1, 2026 – September 15, 2026");
  });

  it("resolves this month and last month", () => {
    expect(thisMonthRange("2026-08-09")).toEqual({ dateFrom: "2026-08-01", dateTo: "2026-08-31" });
    expect(lastMonthRange("2026-08-09")).toEqual({ dateFrom: "2026-07-01", dateTo: "2026-07-31" });
    expect(lastMonthRange("2026-01-15")).toEqual({ dateFrom: "2025-12-01", dateTo: "2025-12-31" });
  });
});
