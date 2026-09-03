import { weekdayShort } from "./dates";
import { isAdminEntry, type TimeEntry } from "./types/time-entry";

export type Metrics = {
  totalHours: number;
  billableHours: number;
  adminHours: number;
  adminPercent: number;
  clientCount: number;
};

export function computeMetrics(entries: TimeEntry[]): Metrics {
  let totalHours = 0;
  let billableHours = 0;
  let adminHours = 0;
  const clients = new Set<string>();
  for (const e of entries) {
    totalHours += e.hours;
    if (e.billable) billableHours += e.hours;
    if (isAdminEntry(e)) adminHours += e.hours;
    clients.add(e.client);
  }
  return {
    totalHours: round2(totalHours),
    billableHours: round2(billableHours),
    adminHours: round2(adminHours),
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
    let admin = 0;
    let nonAdmin = 0;
    for (const e of dayEntries) {
      if (isAdminEntry(e)) admin += e.hours;
      else nonAdmin += e.hours;
    }
    return {
      date,
      label: weekdayShort(date),
      admin: round2(admin),
      nonAdmin: round2(nonAdmin),
      total: round2(admin + nonAdmin),
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
      subtotal: round2(rows.reduce((s, r) => s + r.hours, 0)),
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
      subtotal: round2(rows.reduce((s, r) => s + r.hours, 0)),
    }))
    .sort((a, b) => a.staff_name.localeCompare(b.staff_name));
}

function topNamed(
  entries: TimeEntry[],
  keyFn: (e: TimeEntry) => string,
  limit: number,
): NamedHours[] {
  const map = new Map<string, number>();
  for (const e of entries) {
    const k = keyFn(e);
    map.set(k, (map.get(k) ?? 0) + e.hours);
  }
  return Array.from(map.entries())
    .map(([name, hours], i) => ({
      name,
      hours: round2(hours),
      key: `${name}-${i}`,
    }))
    .sort((a, b) => b.hours - a.hours)
    .slice(0, limit);
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}
