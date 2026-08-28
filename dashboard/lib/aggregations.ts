import { weekdayShort, weekDateISOs } from "./dates";
import type { MockEntry } from "./mock-data";

export type Metrics = {
  totalHours: number;
  billableHours: number;
  nonBillableHours: number;
  entryCount: number;
};

export function computeMetrics(entries: MockEntry[]): Metrics {
  let totalHours = 0;
  let billableHours = 0;
  let nonBillableHours = 0;
  for (const e of entries) {
    totalHours += e.hours;
    if (e.billable) billableHours += e.hours;
    else nonBillableHours += e.hours;
  }
  return {
    totalHours: round1(totalHours),
    billableHours: round1(billableHours),
    nonBillableHours: round1(nonBillableHours),
    entryCount: entries.length,
  };
}

export type DailyTotal = {
  date: string;
  label: string;
  billable: number;
  nonBillable: number;
  total: number;
};

export function dailyTotals(anchor = new Date(), entries: MockEntry[]): DailyTotal[] {
  const days = weekDateISOs(anchor);
  return days.map((date) => {
    const dayEntries = entries.filter((e) => e.entry_date === date);
    let billable = 0;
    let nonBillable = 0;
    for (const e of dayEntries) {
      if (e.billable) billable += e.hours;
      else nonBillable += e.hours;
    }
    return {
      date,
      label: weekdayShort(date),
      billable: round1(billable),
      nonBillable: round1(nonBillable),
      total: round1(billable + nonBillable),
    };
  });
}

export type NamedHours = { name: string; hours: number };

export function aggregateByClient(entries: MockEntry[], limit = 8): NamedHours[] {
  return topNamed(entries, (e) => e.client, limit);
}

export function aggregateByJob(entries: MockEntry[], limit = 8): NamedHours[] {
  return topNamed(entries, (e) => e.job_code, limit);
}

export type ClientGroup = {
  client: string;
  entries: MockEntry[];
  subtotal: number;
};

export function groupByClient(entries: MockEntry[]): ClientGroup[] {
  const map = new Map<string, MockEntry[]>();
  for (const e of entries) {
    const list = map.get(e.client) ?? [];
    list.push(e);
    map.set(e.client, list);
  }
  return Array.from(map.entries())
    .map(([client, rows]) => ({
      client,
      entries: rows,
      subtotal: round1(rows.reduce((s, r) => s + r.hours, 0)),
    }))
    .sort((a, b) => a.client.localeCompare(b.client));
}

function topNamed(
  entries: MockEntry[],
  keyFn: (e: MockEntry) => string,
  limit: number,
): NamedHours[] {
  const map = new Map<string, number>();
  for (const e of entries) {
    const k = keyFn(e);
    map.set(k, (map.get(k) ?? 0) + e.hours);
  }
  return Array.from(map.entries())
    .map(([name, hours]) => ({ name, hours: round1(hours) }))
    .sort((a, b) => b.hours - a.hours)
    .slice(0, limit);
}

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

export function formatHours(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}
