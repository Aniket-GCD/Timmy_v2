import { describe, expect, it } from "vitest";
import { groupByClient, sortEntriesByTime } from "./aggregations";
import type { TimeEntry } from "./types/time-entry";

const row = (partial: Partial<TimeEntry> & Pick<TimeEntry, "id" | "client" | "hours">): TimeEntry => ({
  staff_name: "Aniket",
  office: "GCD",
  job_code: "Bookkeeping",
  notes: "",
  entry_date: "2026-09-04",
  start_time: "09:00:00",
  end_time: "10:00:00",
  billable: true,
  ...partial,
});

describe("groupByClient", () => {
  it("groups and subtotals by client", () => {
    const groups = groupByClient([
      row({ id: 1, client: "Acme", hours: 1 }),
      row({ id: 2, client: "Acme", hours: 2 }),
      row({ id: 3, client: "Beta", hours: 0.5 }),
    ]);
    expect(groups).toHaveLength(2);
    expect(groups[0].client).toBe("Acme");
    expect(groups[0].subtotal).toBe(3);
    expect(groups[1].client).toBe("Beta");
  });
});

describe("sortEntriesByTime", () => {
  const sample = [
    row({ id: 1, client: "Acme", hours: 1, entry_date: "2026-09-05", start_time: "08:00:00" }),
    row({ id: 2, client: "Beta", hours: 1, entry_date: "2026-09-04", start_time: "11:00:00" }),
    row({ id: 3, client: "Acme", hours: 1, entry_date: "2026-09-04", start_time: "09:00:00" }),
    row({ id: 4, client: "Acme", hours: 1, entry_date: "2026-09-04", start_time: null }),
  ];

  it("defaults to earliest date and start time first, with a missing start last that day", () => {
    expect(sortEntriesByTime(sample).map((e) => e.id)).toEqual([3, 2, 4, 1]);
  });

  it("orders latest date and start time first when descending", () => {
    expect(sortEntriesByTime(sample, "desc").map((e) => e.id)).toEqual([1, 2, 3, 4]);
  });
});
