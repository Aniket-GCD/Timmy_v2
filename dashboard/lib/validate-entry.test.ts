import { describe, expect, it } from "vitest";
import { validateEntryWrite } from "./validate-entry";

const clients = [{ name: "0969 Ocean View Road" }];
const jobCodes = [{ job_code: "Bookkeeping", account: "Accounting Services:Hourly" }];

describe("validate-entry", () => {
  it("rejects unknown client", () => {
    const r = validateEntryWrite(
      { client: "Bad", job_code: "Bookkeeping", notes: "x", entry_date: "2026-08-15", start_time: "09:00:00", end_time: "10:00:00", hours: 1, billable: true },
      { clients, jobCodes },
      "Aniket",
    );
    expect(r.ok).toBe(false);
  });

  it("accepts valid entry in edit window", () => {
    const r = validateEntryWrite(
      { client: "0969 Ocean View Road", job_code: "Bookkeeping", notes: "x", entry_date: "2026-08-15", start_time: "09:00:00", end_time: "10:00:00", hours: 1, billable: true },
      { clients, jobCodes },
      "Hannah Curtis",
    );
    expect(r.ok).toBe(true);
  });
});
