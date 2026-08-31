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
};

export function isAdminEntry(entry: Pick<TimeEntry, "job_code">): boolean {
  return entry.job_code === "Admin";
}
