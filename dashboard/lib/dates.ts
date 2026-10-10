/** Date helpers — Sun–Sat weeks, US Central today for dashboard. */

import { chicagoTodayISO, dateISOsInRange, lastPayPeriod, thisPayPeriod } from "./pay-period";

export function todayISO(): string {
  return chicagoTodayISO();
}

export function yesterdayISO(): string {
  return addDaysISO(todayISO(), -1);
}

export function toISODate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function parseISODate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function addDaysISO(iso: string, days: number): string {
  const d = parseISODate(iso);
  d.setDate(d.getDate() + days);
  return toISODate(d);
}

/** Sunday 00:00 of the week containing `anchorISO`. */
export function weekStartSundayISO(anchorISO: string): string {
  const d = parseISODate(anchorISO);
  const day = d.getDay();
  d.setDate(d.getDate() - day);
  return toISODate(d);
}

/** Sun–Sat ISO dates for week containing anchor. */
export function weekDateISOs(anchorISO?: string): string[] {
  const anchor = anchorISO ?? todayISO();
  const start = weekStartSundayISO(anchor);
  return Array.from({ length: 7 }, (_, i) => addDaysISO(start, i));
}

const DISPLAY_LOCALE = "en-US";

export function formatDisplayDate(iso: string): string {
  const d = parseISODate(iso);
  return d.toLocaleDateString(DISPLAY_LOCALE, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function weekdayShort(iso: string): string {
  return parseISODate(iso).toLocaleDateString(DISPLAY_LOCALE, { weekday: "short" });
}

export type RangeKey = "today" | "yesterday" | "week" | "thisPayPeriod" | "lastPayPeriod";

export type ResolvedRange = {
  key: RangeKey;
  dateFrom: string;
  dateTo: string;
  chartDays: string[];
  label: string;
};

export function resolveRange(key: RangeKey, anchorISO?: string): ResolvedRange {
  const anchor = anchorISO ?? todayISO();
  switch (key) {
    case "today":
      return {
        key,
        dateFrom: anchor,
        dateTo: anchor,
        chartDays: weekDateISOs(anchor),
        label: formatDisplayDate(anchor),
      };
    case "yesterday": {
      const y = yesterdayISO();
      return {
        key,
        dateFrom: y,
        dateTo: y,
        chartDays: weekDateISOs(y),
        label: formatDisplayDate(y),
      };
    }
    case "week": {
      const days = weekDateISOs(anchor);
      return {
        key,
        dateFrom: days[0],
        dateTo: days[6],
        chartDays: days,
        label: "This week",
      };
    }
    case "thisPayPeriod": {
      const p = thisPayPeriod(anchor);
      return {
        key,
        dateFrom: p.startISO,
        dateTo: p.endISO,
        chartDays: dateISOsInRange(p.startISO, p.endISO),
        label: "This pay period",
      };
    }
    case "lastPayPeriod": {
      const p = lastPayPeriod(anchor);
      return {
        key,
        dateFrom: p.startISO,
        dateTo: p.endISO,
        chartDays: dateISOsInRange(p.startISO, p.endISO),
        label: "Last pay period",
      };
    }
  }
}

export function defaultFocusDay(
  key: RangeKey,
  entries: { entry_date: string }[],
  anchorISO?: string,
): string {
  const anchor = anchorISO ?? todayISO();
  if (key === "today") return anchor;
  if (key === "yesterday") return yesterdayISO();
  const range = resolveRange(key, anchor);
  if (range.dateFrom <= anchor && anchor <= range.dateTo) return anchor;
  const dated = entries
    .filter((e) => e.entry_date >= range.dateFrom && e.entry_date <= range.dateTo)
    .map((e) => e.entry_date)
    .sort();
  return dated.at(-1) ?? range.dateFrom;
}

export function filterEntriesByRange<T extends { entry_date: string }>(
  entries: T[],
  range: ResolvedRange,
): T[] {
  return entries.filter(
    (e) => e.entry_date >= range.dateFrom && e.entry_date <= range.dateTo,
  );
}

function monthBounds(year: number, month: number): { dateFrom: string; dateTo: string } {
  const last = new Date(year, month, 0).getDate();
  const mm = String(month).padStart(2, "0");
  return {
    dateFrom: `${year}-${mm}-01`,
    dateTo: `${year}-${mm}-${String(last).padStart(2, "0")}`,
  };
}

/** First and last day of the Chicago month containing `anchorISO`. */
export function thisMonthRange(anchorISO?: string): { dateFrom: string; dateTo: string } {
  const [y, m] = (anchorISO ?? todayISO()).split("-").map(Number);
  return monthBounds(y, m);
}

/** First and last day of the month before `anchorISO`. */
export function lastMonthRange(anchorISO?: string): { dateFrom: string; dateTo: string } {
  const [y, m] = (anchorISO ?? todayISO()).split("-").map(Number);
  const prev = new Date(y, m - 2, 1);
  return monthBounds(prev.getFullYear(), prev.getMonth() + 1);
}

export function entriesForDay<T extends { entry_date: string }>(
  dayISO: string,
  entries: T[],
): T[] {
  return entries
    .filter((e) => e.entry_date === dayISO)
    .sort((a, b) => {
      const aStart = ("start_time" in a && a.start_time) || "99:99:99";
      const bStart = ("start_time" in b && b.start_time) || "99:99:99";
      return String(aStart).localeCompare(String(bStart));
    });
}
