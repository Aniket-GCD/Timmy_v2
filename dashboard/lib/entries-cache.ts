import type { RangeKey } from "./dates";
import { resolveRange, weekDateISOs } from "./dates";
import type { TimeEntry } from "./types/time-entry";

export type EntriesCacheKeyParts = {
  staff: string;
  office: string;
  dateFrom: string;
  dateTo: string;
};

export type EntriesCacheEntry = {
  entries: TimeEntry[];
  fetchedAt: number;
};

/** Fetch window for API: week-scoped tabs share Sun–Sat; pay periods use their bounds. */
export function entriesFetchWindow(
  rangeKey: RangeKey,
  anchorISO?: string,
): { dateFrom: string; dateTo: string } {
  if (rangeKey === "today" || rangeKey === "yesterday" || rangeKey === "week") {
    const days = weekDateISOs(anchorISO);
    return { dateFrom: days[0], dateTo: days[6] };
  }
  const resolved = resolveRange(rangeKey, anchorISO);
  return { dateFrom: resolved.dateFrom, dateTo: resolved.dateTo };
}

export function buildEntriesCacheKey(parts: EntriesCacheKeyParts): string {
  const staff = parts.staff.trim() || "ALL";
  const office = parts.office.trim().toUpperCase() || "ALL";
  return `${staff}|${office}|${parts.dateFrom}|${parts.dateTo}`;
}

export function createEntriesCache() {
  const map = new Map<string, EntriesCacheEntry>();

  return {
    get(key: string): EntriesCacheEntry | undefined {
      return map.get(key);
    },
    set(key: string, entries: TimeEntry[]): void {
      map.set(key, { entries, fetchedAt: Date.now() });
    },
    /** Drop every cached window (simple invalidation after writes). */
    clear(): void {
      map.clear();
    },
    size(): number {
      return map.size;
    },
  };
}

export type EntriesCache = ReturnType<typeof createEntriesCache>;
