import { durationHoursFromTimes, parseTimeInput } from "./hours-format";
import { isWithinEditWindow } from "./pay-period";
import type { ClientOption, JobCodeOption } from "./types/reference-data";
import type { EntryWritePayload } from "./types/time-entry";

export type ValidationResult =
  | { ok: true; payload: EntryWritePayload; account: string }
  | { ok: false; error: string };

export type ValidateEntryOptions = {
  /** Dashboard admins skip pay-period window refusal. */
  skipPayPeriodWindow?: boolean;
};

export function validateEntryWrite(
  draft: EntryWritePayload,
  refs: { clients: ClientOption[]; jobCodes: JobCodeOption[] },
  staffName: string,
  options: ValidateEntryOptions = {},
): ValidationResult {
  void staffName;
  const clientNames = new Set(refs.clients.map((c) => c.name));
  if (!clientNames.has(draft.client)) {
    return { ok: false, error: "Select a valid client from the firm roster." };
  }
  const job = refs.jobCodes.find((j) => j.job_code === draft.job_code);
  if (!job) {
    return { ok: false, error: "Select a valid job code." };
  }
  if (!options.skipPayPeriodWindow && !isWithinEditWindow(draft.entry_date)) {
    return { ok: false, error: "This entry date is outside the pay-period edit window." };
  }

  const hasStart = Boolean(draft.start_time?.trim());
  const hasEnd = Boolean(draft.end_time?.trim());
  if (hasStart !== hasEnd) {
    return { ok: false, error: "Provide both start and end times, or leave both blank for duration-only." };
  }

  const start = hasStart ? parseTimeInput(draft.start_time!) ?? draft.start_time : null;
  const end = hasEnd ? parseTimeInput(draft.end_time!) ?? draft.end_time : null;
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
