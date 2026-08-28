import { addDaysISO, todayISO, weekDateISOs } from "./dates";

export type EntryStatus = "submitted";

/** Mirrors future time_entries_timmy_v2 row shape. */
export type MockEntry = {
  id: number;
  staff_name: string;
  office: string;
  client: string;
  job_code: string;
  notes: string;
  entry_date: string;
  start_time: string | null;
  end_time: string | null;
  hours: number;
  billable: boolean;
  status: EntryStatus;
};

export const MOCK_STAFF = {
  staff_name: "Aniket",
  office: "GCD",
} as const;

function seedEntries(anchorISO: string): MockEntry[] {
  // Relative to "today" so Yesterday / Today / This week always have data.
  const t = (offset: number) => addDaysISO(anchorISO, offset);
  let id = 1;
  const row = (
    partial: Omit<MockEntry, "id" | "staff_name" | "office" | "status">,
  ): MockEntry => ({
    id: id++,
    staff_name: MOCK_STAFF.staff_name,
    office: MOCK_STAFF.office,
    status: "submitted",
    ...partial,
  });

  return [
    // Today — multi-entry Admin + clients
    row({
      client: "Internal — Firm Admin",
      job_code: "Admin",
      notes: "Email triage and calendar",
      entry_date: t(0),
      start_time: "08:30",
      end_time: "09:15",
      hours: 0.75,
      billable: false,
    }),
    row({
      client: "Internal — Firm Admin",
      job_code: "Admin",
      notes: "Staff meeting notes",
      entry_date: t(0),
      start_time: "09:15",
      end_time: "10:00",
      hours: 0.75,
      billable: false,
    }),
    row({
      client: "0969 Ocean View Road",
      job_code: "Bookkeeping",
      notes: "Reconcile March bank feeds",
      entry_date: t(0),
      start_time: "10:15",
      end_time: "12:00",
      hours: 1.75,
      billable: true,
    }),
    row({
      client: "0969 Ocean View Road",
      job_code: "Bookkeeping",
      notes: "AP follow-ups",
      entry_date: t(0),
      start_time: "13:00",
      end_time: "14:30",
      hours: 1.5,
      billable: true,
    }),
    row({
      client: "Harris Family Trust",
      job_code: "Tax Return",
      notes: "Gather K-1 docs",
      entry_date: t(0),
      start_time: "14:45",
      end_time: "16:15",
      hours: 1.5,
      billable: true,
    }),
    row({
      client: "Greenfield Holdings LLC",
      job_code: "Advisory",
      notes: "Cash flow model review",
      entry_date: t(0),
      start_time: null,
      end_time: null,
      hours: 1.0,
      billable: true,
    }),

    // Yesterday
    row({
      client: "Internal — Firm Admin",
      job_code: "Admin",
      notes: "Timesheet cleanup",
      entry_date: t(-1),
      start_time: "08:45",
      end_time: "09:30",
      hours: 0.75,
      billable: false,
    }),
    row({
      client: "Cedar Ridge Properties",
      job_code: "Audit",
      notes: "PBC list updates",
      entry_date: t(-1),
      start_time: "09:45",
      end_time: "12:00",
      hours: 2.25,
      billable: true,
    }),
    row({
      client: "Cedar Ridge Properties",
      job_code: "Audit",
      notes: "Walkthrough controls memo",
      entry_date: t(-1),
      start_time: "13:00",
      end_time: "15:30",
      hours: 2.5,
      billable: true,
    }),
    row({
      client: "Maple Street Dental",
      job_code: "Bookkeeping",
      notes: "Payroll journal entry",
      entry_date: t(-1),
      start_time: "15:45",
      end_time: "17:00",
      hours: 1.25,
      billable: true,
    }),

    // Earlier this week / last few days
    row({
      client: "0969 Ocean View Road",
      job_code: "Bookkeeping",
      notes: "Vendor bill coding",
      entry_date: t(-2),
      start_time: "09:00",
      end_time: "11:30",
      hours: 2.5,
      billable: true,
    }),
    row({
      client: "Harris Family Trust",
      job_code: "Tax Return",
      notes: "Organizer follow-up call",
      entry_date: t(-2),
      start_time: "13:00",
      end_time: "14:00",
      hours: 1.0,
      billable: true,
    }),
    row({
      client: "Internal — Firm Admin",
      job_code: "Admin",
      notes: "CPE webinar",
      entry_date: t(-2),
      start_time: "14:30",
      end_time: "16:00",
      hours: 1.5,
      billable: false,
    }),
    row({
      client: "Summit Retail Group",
      job_code: "Tax Return",
      notes: "1040ES estimate worksheet",
      entry_date: t(-3),
      start_time: "08:30",
      end_time: "10:30",
      hours: 2.0,
      billable: true,
    }),
    row({
      client: "Summit Retail Group",
      job_code: "Bookkeeping",
      notes: "Sales tax remittance check",
      entry_date: t(-3),
      start_time: "10:45",
      end_time: "12:00",
      hours: 1.25,
      billable: true,
    }),
    row({
      client: "Greenfield Holdings LLC",
      job_code: "Advisory",
      notes: "Board deck numbers",
      entry_date: t(-3),
      start_time: null,
      end_time: null,
      hours: 2.0,
      billable: true,
    }),
    row({
      client: "Internal — Firm Admin",
      job_code: "Admin",
      notes: "New hire onboarding packet",
      entry_date: t(-4),
      start_time: "09:00",
      end_time: "10:00",
      hours: 1.0,
      billable: false,
    }),
    row({
      client: "Maple Street Dental",
      job_code: "Bookkeeping",
      notes: "Month-end close checklist",
      entry_date: t(-4),
      start_time: "10:15",
      end_time: "13:00",
      hours: 2.75,
      billable: true,
    }),
    row({
      client: "Pinecrest HOA",
      job_code: "Audit",
      notes: "Bank confirmations",
      entry_date: t(-4),
      start_time: "14:00",
      end_time: "16:30",
      hours: 2.5,
      billable: true,
    }),
    row({
      client: "0969 Ocean View Road",
      job_code: "Bookkeeping",
      notes: "Catch-up categorization",
      entry_date: t(-5),
      start_time: "09:30",
      end_time: "12:00",
      hours: 2.5,
      billable: true,
    }),
    row({
      client: "Harris Family Trust",
      job_code: "Tax Return",
      notes: "Basis schedule draft",
      entry_date: t(-5),
      start_time: "13:15",
      end_time: "16:00",
      hours: 2.75,
      billable: true,
    }),
    row({
      client: "Cedar Ridge Properties",
      job_code: "Audit",
      notes: "Lease abstract sample",
      entry_date: t(-6),
      start_time: "08:45",
      end_time: "11:45",
      hours: 3.0,
      billable: true,
    }),
    row({
      client: "Internal — Firm Admin",
      job_code: "Admin",
      notes: "Office supply order",
      entry_date: t(-6),
      start_time: "13:00",
      end_time: "13:30",
      hours: 0.5,
      billable: false,
    }),
    row({
      client: "Summit Retail Group",
      job_code: "Tax Return",
      notes: "Depreciation workbook",
      entry_date: t(-6),
      start_time: "13:45",
      end_time: "16:15",
      hours: 2.5,
      billable: true,
    }),
    // Prior week leftovers (still in seed for richer charts if week spans)
    row({
      client: "Pinecrest HOA",
      job_code: "Bookkeeping",
      notes: "Owner statement review",
      entry_date: t(-7),
      start_time: "10:00",
      end_time: "12:30",
      hours: 2.5,
      billable: true,
    }),
    row({
      client: "Greenfield Holdings LLC",
      job_code: "Advisory",
      notes: "Scenario sensitivity table",
      entry_date: t(-8),
      start_time: null,
      end_time: null,
      hours: 1.5,
      billable: true,
    }),
    row({
      client: "Maple Street Dental",
      job_code: "Tax Return",
      notes: "Q2 extension checklist",
      entry_date: t(-9),
      start_time: "09:00",
      end_time: "11:00",
      hours: 2.0,
      billable: true,
    }),
  ];
}

const ANCHOR = todayISO();
export const MOCK_ENTRIES: MockEntry[] = seedEntries(ANCHOR);

export function entriesForDay(dateISO: string, entries = MOCK_ENTRIES): MockEntry[] {
  return entries
    .filter((e) => e.entry_date === dateISO)
    .sort((a, b) => {
      const as = a.start_time ?? "99:99";
      const bs = b.start_time ?? "99:99";
      return as.localeCompare(bs) || a.id - b.id;
    });
}

export function entriesForWeek(anchor = new Date(), entries = MOCK_ENTRIES): MockEntry[] {
  const days = new Set(weekDateISOs(anchor));
  return entries.filter((e) => days.has(e.entry_date));
}

export function entriesForRange(
  range: "yesterday" | "today" | "week",
  selectedDayISO: string,
  anchor = new Date(),
  entries = MOCK_ENTRIES,
): MockEntry[] {
  if (range === "week") return entriesForWeek(anchor, entries);
  return entriesForDay(selectedDayISO, entries);
}
