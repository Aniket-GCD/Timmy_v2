/** Date helpers for the mock Timmy dashboard. Week = Mon–Sun local. */

export function todayISO(now = new Date()): string {
  return toISODate(now);
}

export function yesterdayISO(now = new Date()): string {
  const d = new Date(now);
  d.setDate(d.getDate() - 1);
  return toISODate(d);
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

/** Monday 00:00 of the week containing `anchor`. */
export function weekStartMonday(anchor: Date = new Date()): Date {
  const d = new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate());
  const day = d.getDay(); // 0 Sun .. 6 Sat
  const diff = day === 0 ? -6 : 1 - day;
  d.setDate(d.getDate() + diff);
  return d;
}

export function weekDateISOs(anchor: Date = new Date()): string[] {
  const start = weekStartMonday(anchor);
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return toISODate(d);
  });
}

export function addDaysISO(iso: string, days: number): string {
  const d = parseISODate(iso);
  d.setDate(d.getDate() + days);
  return toISODate(d);
}

/** Fixed locale so SSR and browser hydration match. */
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
