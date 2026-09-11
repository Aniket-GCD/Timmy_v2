import { describe, expect, it } from "vitest";
import { validateEntryWrite } from "./validate-entry";

const clients = [{ name: "0969 Ocean View Road" }];
const jobCodes = [{ job_code: "Bookkeeping", account: "Accounting Services:Hourly" }];

const base = {
  client: "0969 Ocean View Road",
  job_code: "Bookkeeping",
  notes: "x",
  entry_date: "2026-08-15",
  start_time: "09:00:00",
  end_time: "10:00:00",
  hours: 1,
  billable: true,
};

describe("validate-entry", () => {
  it("rejects unknown client", () => {
    const r = validateEntryWrite(
      { ...base, client: "Bad" },
      { clients, jobCodes },
      "Aniket",
      { skipPayPeriodWindow: true },
    );
    expect(r.ok).toBe(false);
  });

  it("accepts valid entry when window skipped", () => {
    const r = validateEntryWrite(base, { clients, jobCodes }, "Alex Daley", {
      skipPayPeriodWindow: true,
    });
    expect(r.ok).toBe(true);
  });

  it("rejects out-of-window without skip", () => {
    const r = validateEntryWrite(
      { ...base, entry_date: "2020-01-15" },
      { clients, jobCodes },
      "Alex Daley",
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toMatch(/edit window/i);
  });

  it("rejects start without end", () => {
    const r = validateEntryWrite(
      { ...base, end_time: null },
      { clients, jobCodes },
      "Alex Daley",
      { skipPayPeriodWindow: true },
    );
    expect(r.ok).toBe(false);
  });
});
