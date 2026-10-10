import { describe, expect, it } from "vitest";
import { humanizeApiError } from "./humanize-api-error";
import { ENTRY_ERRORS, validateEntryWrite } from "./validate-entry";

const clients = [{ name: "0969 Ocean View Road", office: "GCD" }];
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
  it("rejects unknown client with plain language", () => {
    const r = validateEntryWrite(
      { ...base, client: "Bad" },
      { clients, jobCodes },
      "Aniket",
      { skipPayPeriodWindow: true },
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toBe(ENTRY_ERRORS.client);
  });

  it("saves the catalog spelling when case differs", () => {
    const r = validateEntryWrite(
      { ...base, job_code: "bookkeeping" },
      { clients, jobCodes },
      "Alex Daley",
      { skipPayPeriodWindow: true },
    );
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.payload.job_code).toBe("Bookkeeping");
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
    if (!r.ok) expect(r.error).toBe(ENTRY_ERRORS.lockedDate);
  });

  it("rejects start without end", () => {
    const r = validateEntryWrite(
      { ...base, end_time: null },
      { clients, jobCodes },
      "Alex Daley",
      { skipPayPeriodWindow: true },
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toBe(ENTRY_ERRORS.bothOrNeither);
  });

  it("rejects mangled time like 00:5:", () => {
    const r = validateEntryWrite(
      { ...base, start_time: "00:00", end_time: "00:5:" },
      { clients, jobCodes },
      "Alex Daley",
      { skipPayPeriodWindow: true },
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toBe(ENTRY_ERRORS.badTime);
  });

  it("rejects equal start and end", () => {
    const r = validateEntryWrite(
      { ...base, start_time: "09:00", end_time: "09:00" },
      { clients, jobCodes },
      "Alex Daley",
      { skipPayPeriodWindow: true },
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toBe(ENTRY_ERRORS.endBeforeStart);
  });

  it("derives hours from start and end", () => {
    const r = validateEntryWrite(
      { ...base, start_time: "00:00", end_time: "00:05", hours: 99 },
      { clients, jobCodes },
      "Alex Daley",
      { skipPayPeriodWindow: true },
    );
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.payload.hours).toBe(5 / 60);
  });

  it("keeps 8:25 as exact minutes instead of hundredths of an hour", () => {
    const r = validateEntryWrite(
      { ...base, start_time: null, end_time: null, hours: 8 + 25 / 60 },
      { clients, jobCodes },
      "Alex Daley",
      { skipPayPeriodWindow: true },
    );
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.payload.hours).toBe(8 + 25 / 60);
      expect(r.payload.hours).not.toBe(8.42);
    }
  });
});

describe("humanizeApiError", () => {
  it("maps JSON forbidden to own-only message", () => {
    expect(humanizeApiError(JSON.stringify({ error: "Forbidden" }))).toBe(ENTRY_ERRORS.ownOnly);
  });

  it("does not treat a Next 404 page as an edit denial", () => {
    const html = '<!DOCTYPE html><html><body>"forbidden":"$undefined"</body></html>';
    expect(humanizeApiError(html)).toBe(ENTRY_ERRORS.saveFailed);
  });

  it("maps locked date phrases", () => {
    expect(humanizeApiError(JSON.stringify({ error: ENTRY_ERRORS.lockedDate }))).toBe(
      ENTRY_ERRORS.lockedDate,
    );
  });

  it("hides raw PostgREST noise", () => {
    expect(humanizeApiError('{"code":"42501","message":"permission denied"}')).toBe(
      ENTRY_ERRORS.saveFailed,
    );
  });

  it("passes through validate-entry copy", () => {
    expect(humanizeApiError(JSON.stringify({ error: ENTRY_ERRORS.badTime }))).toBe(
      ENTRY_ERRORS.badTime,
    );
  });
});
