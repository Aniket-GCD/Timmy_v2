import type { TimeEntry } from "./types/time-entry";

export function normalizeSupabaseRow(row: Record<string, unknown>): TimeEntry {
  return {
    id: Number(row.id),
    staff_name: String(row.staff_name ?? ""),
    office: String(row.office ?? ""),
    client: String(row.client ?? ""),
    job_code: String(row.job_code ?? ""),
    account: row.account ? String(row.account) : undefined,
    notes: String(row.notes ?? row.task ?? ""),
    entry_date: String(row.entry_date ?? "").slice(0, 10),
    start_time: row.start_time ? String(row.start_time).slice(0, 8) : null,
    end_time: row.end_time ? String(row.end_time).slice(0, 8) : null,
    hours: Number(row.hours ?? 0),
    billable: Boolean(row.billable),
    source_file: row.source_file ? String(row.source_file) : undefined,
  };
}

export function toSupabasePayload(
  entry: TimeEntry,
  account: string,
): Record<string, unknown> {
  return {
    staff_name: entry.staff_name,
    office: entry.office,
    client: entry.client,
    job_code: entry.job_code,
    account,
    notes: entry.notes,
    task: entry.notes,
    entry_date: entry.entry_date,
    start_time: entry.start_time,
    end_time: entry.end_time,
    hours: entry.hours,
    billable: entry.billable,
    source_file: entry.source_file ?? "timmy-dashboard",
  };
}
