import { weekdayShort } from "./dates";
import { hoursToMinutes } from "./hours-format";
import { isAdminEntry, type TimeEntry } from "./types/time-entry";

function minuteHours(rows: TimeEntry[]): number {
  return rows.reduce((s, r) => s + hoursToMinutes(r.hours), 0) / 60;
}

export type Metrics = {
  totalHours: number;
  adminHours: number;
  adminPercent: number;
  clientCount: number;
};

export function computeMetrics(entries: TimeEntry[]): Metrics {
  const adminRows = entries.filter((e) => isAdminEntry(e));
  const totalHours = minuteHours(entries);
  const adminHours = minuteHours(adminRows);
  const clients = new Set(entries.map((e) => e.client));
  return {
    totalHours,
    adminHours,
    adminPercent: totalHours > 0 ? Math.round((adminHours / totalHours) * 100) : 0,
    clientCount: clients.size,
  };
}

export type DailyTotal = {
  date: string;
  label: string;
  admin: number;
  nonAdmin: number;
  total: number;
};

export function dailyTotals(chartDays: string[], entries: TimeEntry[]): DailyTotal[] {
  return chartDays.map((date) => {
    const dayEntries = entries.filter((e) => e.entry_date === date);
    const adminRows = dayEntries.filter((e) => isAdminEntry(e));
    const clientRows = dayEntries.filter((e) => !isAdminEntry(e));
    return {
      date,
      label: `${weekdayShort(date)} ${Number(date.slice(5, 7))}/${Number(date.slice(8))}`,
      admin: minuteHours(adminRows),
      nonAdmin: minuteHours(clientRows),
      total: minuteHours(dayEntries),
    };
  });
}

export type NamedHours = { name: string; hours: number; key: string };

export function aggregateByClient(entries: TimeEntry[], limit = 8): NamedHours[] {
  return topNamed(entries, (e) => e.client, limit);
}

export function aggregateByJob(entries: TimeEntry[], limit = 8): NamedHours[] {
  return topNamed(entries, (e) => e.job_code, limit);
}

export type ClientGroup = {
  client: string;
  entries: TimeEntry[];
  subtotal: number;
};

export function groupByClient(entries: TimeEntry[]): ClientGroup[] {
  const map = new Map<string, TimeEntry[]>();
  for (const e of entries) {
    const list = map.get(e.client) ?? [];
    list.push(e);
    map.set(e.client, list);
  }
  return Array.from(map.entries())
    .map(([client, rows]) => ({
      client,
      entries: rows,
      subtotal: minuteHours(rows),
    }))
    .sort((a, b) => a.client.localeCompare(b.client));
}

export type StaffGroup = {
  staff_name: string;
  entries: TimeEntry[];
  subtotal: number;
};

export function groupByStaff(entries: TimeEntry[]): StaffGroup[] {
  const map = new Map<string, TimeEntry[]>();
  for (const e of entries) {
    const list = map.get(e.staff_name) ?? [];
    list.push(e);
    map.set(e.staff_name, list);
  }
  return Array.from(map.entries())
    .map(([staff_name, rows]) => ({
      staff_name,
      entries: rows,
      subtotal: minuteHours(rows),
    }))
    .sort((a, b) => a.staff_name.localeCompare(b.staff_name));
}

function topNamed(
  entries: TimeEntry[],
  keyFn: (e: TimeEntry) => string,
  limit: number,
): NamedHours[] {
  const map = new Map<string, TimeEntry[]>();
  for (const e of entries) {
    const k = keyFn(e);
    const list = map.get(k) ?? [];
    list.push(e);
    map.set(k, list);
  }
  return Array.from(map.entries())
    .map(([name, rows], i) => ({
      name,
      hours: minuteHours(rows),
      key: `${name}-${i}`,
    }))
    .sort((a, b) => b.hours - a.hours)
    .slice(0, limit);
}
