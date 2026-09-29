export type EntryStatus = "submitted" | "draft" | "locked" | "saving" | "error";

/** Mirrors time_entries_timmy_v2 / Timmy submit payload. */
export type TimeEntry = {
  id: number;
  staff_name: string;
  office: string;
  client: string;
  job_code: string;
  account?: string;
  notes: string;
  entry_date: string;
  start_time: string | null;
  end_time: string | null;
  hours: number;
  billable: boolean;
  source_file?: string;
  /** UI status; submitted entries from Timmy default to submitted. */
  status?: EntryStatus;
};

export type EntryWritePayload = {
  client: string;
  job_code: string;
  notes: string;
  entry_date: string;
  start_time: string | null;
  end_time: string | null;
  hours: number;
  billable: boolean;
  /** Optional; server still resolves from client when possible. */
  office?: string;
};

/** Job codes that count as admin time (Timmy uses both "Admin" and "Administrative"). */
export function isAdminJobCode(jobCode: string): boolean {
  const j = jobCode.trim().toLowerCase();
  return j === "admin" || j === "administrative";
}

/** True when client is the Timmy Admin bucket (top-card Admin % uses this only). */
export function isAdminEntry(entry: Pick<TimeEntry, "job_code" | "client">): boolean {
  return entry.client.trim().toLowerCase() === "admin";
}
