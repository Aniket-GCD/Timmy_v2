import { durationHoursFromTimes, parseTimeInput } from "./hours-format";
import { isEditable } from "./pay-period";
import type { ClientOption, JobCodeOption } from "./types/reference-data";
import type { EntryWritePayload } from "./types/time-entry";

export type ValidationResult =
  | { ok: true; payload: EntryWritePayload; account: string }
  | { ok: false; error: string };

export function validateEntryWrite(
  draft: EntryWritePayload,
  refs: { clients: ClientOption[]; jobCodes: JobCodeOption[] },
  staffName: string,
): ValidationResult {
  const clientNames = new Set(refs.clients.map((c) => c.name));
  if (!clientNames.has(draft.client)) {
    return { ok: false, error: "Select a valid client from the firm roster." };
  }
  const job = refs.jobCodes.find((j) => j.job_code === draft.job_code);
  if (!job) {
    return { ok: false, error: "Select a valid job code." };
  }
  if (!isEditable(draft.entry_date, staffName)) {
    return { ok: false, error: "This entry date is outside the pay-period edit window." };
  }

  const start = draft.start_time ? parseTimeInput(draft.start_time) ?? draft.start_time : null;
  const end = draft.end_time ? parseTimeInput(draft.end_time) ?? draft.end_time : null;
  let hours = draft.hours;
  const fromTimes = durationHoursFromTimes(start, end);
  if (fromTimes != null) hours = fromTimes;
  if (hours <= 0) {
    return { ok: false, error: "Hours must be greater than zero." };
  }

  const billable = draft.job_code === "Admin" ? false : draft.billable;

  return {
    ok: true,
    account: job.account,
    payload: {
      ...draft,
      start_time: start,
      end_time: end,
      hours: Math.round(hours * 100) / 100,
      billable,
    },
  };
}
