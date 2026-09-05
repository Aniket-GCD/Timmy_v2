import { describe, expect, it } from "vitest";
import { groupByClient } from "./aggregations";
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
