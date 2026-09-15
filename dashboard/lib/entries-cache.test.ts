import { describe, expect, it } from "vitest";
import {
  buildEntriesCacheKey,
  createEntriesCache,
  entriesFetchWindow,
} from "./entries-cache";
import type { TimeEntry } from "./types/time-entry";

describe("entriesFetchWindow", () => {
  it("shares Sun–Sat week for today/yesterday/week", () => {
    const anchor = "2026-09-16"; // Tuesday
    const today = entriesFetchWindow("today", anchor);
    const yesterday = entriesFetchWindow("yesterday", anchor);
    const week = entriesFetchWindow("week", anchor);
    expect(today).toEqual(week);
    expect(yesterday).toEqual(week);
    expect(today.dateFrom).toBe("2026-09-13");
    expect(today.dateTo).toBe("2026-09-19");
  });

  it("uses pay-period bounds for thisPayPeriod", () => {
    const w = entriesFetchWindow("thisPayPeriod", "2026-09-16");
    expect(w.dateFrom <= "2026-09-16").toBe(true);
    expect(w.dateTo >= "2026-09-16").toBe(true);
    expect(w.dateFrom < w.dateTo || w.dateFrom === w.dateTo).toBe(true);
  });
});

describe("entries cache", () => {
  it("builds stable keys", () => {
    expect(
      buildEntriesCacheKey({
        staff: "Nathan",
        office: "gcd",
        dateFrom: "2026-09-13",
        dateTo: "2026-09-19",
      }),
    ).toBe("Nathan|GCD|2026-09-13|2026-09-19");
    expect(
      buildEntriesCacheKey({
        staff: "",
        office: "",
        dateFrom: "a",
        dateTo: "b",
      }),
    ).toBe("ALL|ALL|a|b");
  });

  it("stores and clears", () => {
    const cache = createEntriesCache();
    const rows = [{ id: 1 } as TimeEntry];
    cache.set("k", rows);
    expect(cache.get("k")?.entries).toEqual(rows);
    cache.clear();
    expect(cache.get("k")).toBeUndefined();
  });
});
