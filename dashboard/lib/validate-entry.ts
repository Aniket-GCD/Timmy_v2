import { durationHoursFromTimes, parseTimeInput } from "./hours-format";
import { isWithinEditWindow } from "./pay-period";
import type { ClientOption, JobCodeOption } from "./types/reference-data";
import { isAdminJobCode, type EntryWritePayload } from "./types/time-entry";

export type ValidationResult =
  | { ok: true; payload: EntryWritePayload; account: string }
  | { ok: false; error: string };

export type ValidateEntryOptions = {
  /** Dashboard admins skip pay-period window refusal. */
  skipPayPeriodWindow?: boolean;
};

export const ENTRY_ERRORS = {
  client: "Pick a client from the list.",
  job: "Pick a job code from the list.",
  lockedDate:
    "This date is locked for editing. Contact an admin if it needs to change.",
  bothOrNeither:
    "Enter both a start time and an end time, or clear both and enter the duration instead.",
  badTime: "Enter start and end as hours and minutes, like 9:00 and 9:05.",
  badDuration: "Enter how long the work took, like 0:05 or 1:30.",
  endBeforeStart: "End time needs to be after start time.",
  ownOnly: "You can only edit your own time entries.",
  notFound: "We could not find that time entry.",
  saveFailed: "We couldn’t save that change. Check the times and try again.",
} as const;

export function validateEntryWrite(
  draft: EntryWritePayload,
  refs: { clients: ClientOption[]; jobCodes: JobCodeOption[] },
  staffName: string,
  options: ValidateEntryOptions = {},
): ValidationResult {
  void staffName;
  const clientNames = new Set(refs.clients.map((c) => c.name));
  if (!clientNames.has(draft.client)) {
    return { ok: false, error: ENTRY_ERRORS.client };
  }
  const job = refs.jobCodes.find((j) => j.job_code === draft.job_code);
  if (!job) {
    return { ok: false, error: ENTRY_ERRORS.job };
  }
  if (!options.skipPayPeriodWindow && !isWithinEditWindow(draft.entry_date)) {
    return { ok: false, error: ENTRY_ERRORS.lockedDate };
  }

  const startRaw = draft.start_time?.trim() ?? "";
  const endRaw = draft.end_time?.trim() ?? "";
  const hasStart = Boolean(startRaw);
  const hasEnd = Boolean(endRaw);
  if (hasStart !== hasEnd) {
    return { ok: false, error: ENTRY_ERRORS.bothOrNeither };
  }

  let start: string | null = null;
  let end: string | null = null;
  if (hasStart && hasEnd) {
    start = parseTimeInput(startRaw);
    end = parseTimeInput(endRaw);
    if (!start || !end) {
      return { ok: false, error: ENTRY_ERRORS.badTime };
    }
  }

  let hours = draft.hours;
  const fromTimes = durationHoursFromTimes(start, end);
  if (fromTimes != null) {
    if (fromTimes <= 0) {
      return { ok: false, error: ENTRY_ERRORS.endBeforeStart };
    }
    hours = fromTimes;
  }
  if (!Number.isFinite(hours) || hours <= 0) {
    return { ok: false, error: ENTRY_ERRORS.badDuration };
  }

  const billable = isAdminJobCode(draft.job_code) ? false : draft.billable;

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
