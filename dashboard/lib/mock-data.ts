import { addDaysISO, todayISO } from "./dates";
import type { CurrentlyWorking } from "./types/currently-working";
import type { Employee } from "./types/employee";
import type { TimeEntry } from "./types/time-entry";

export const MOCK_STAFF = {
  staff_name: "Aniket",
  office: "GCD",
} as const;

export const MOCK_EMPLOYEES: Employee[] = [
  { id: "e-aniket", first_name: "Aniket", last_name: "", staff_name: "Aniket", office: "GCD", active: true },
  { id: "e-andrea", first_name: "Andrea", last_name: "Rottman", staff_name: "Andrea Rottman", office: "GCD", active: true },
  { id: "e-hannah", first_name: "Hannah", last_name: "Curtis", staff_name: "Hannah Curtis", office: "GCD", active: true },
  { id: "e-ken", first_name: "Ken", last_name: "Green", staff_name: "Ken Green", office: "GCD", active: true },
  { id: "e-weston", first_name: "Weston", last_name: "Brockbank", staff_name: "Weston Brockbank", office: "GCD", active: true },
];

function seedEntries(anchorISO: string): TimeEntry[] {
  const t = (offset: number) => addDaysISO(anchorISO, offset);
  let id = 1;
  const row = (
    partial: Omit<TimeEntry, "id" | "staff_name" | "office" | "source_file">,
  ): TimeEntry => ({
    id: id++,
    staff_name: MOCK_STAFF.staff_name,
    office: MOCK_STAFF.office,
    source_file: "timmy-dashboard-mock",
    ...partial,
  });

  return [
    row({ client: "Internal — Firm Admin", job_code: "Admin", notes: "Email triage", entry_date: t(0), start_time: "08:30:00", end_time: "09:15:00", hours: 0.75, billable: false }),
    row({ client: "Internal — Firm Admin", job_code: "Admin", notes: "Staff meeting", entry_date: t(0), start_time: "09:15:00", end_time: "10:00:00", hours: 0.75, billable: false }),
    row({ client: "0969 Ocean View Road", job_code: "Bookkeeping", notes: "Bank reconcile", entry_date: t(0), start_time: "10:15:00", end_time: "12:00:00", hours: 1.75, billable: true }),
    row({ client: "0969 Ocean View Road", job_code: "Bookkeeping", notes: "AP follow-ups", entry_date: t(0), start_time: "13:00:00", end_time: "14:30:00", hours: 1.5, billable: true }),
    row({ client: "Harris Family Trust", job_code: "Tax Return", notes: "K-1 docs", entry_date: t(0), start_time: "14:45:00", end_time: "16:15:00", hours: 1.5, billable: true }),
    row({ client: "Greenfield Holdings LLC", job_code: "Advisory", notes: "Cash flow review", entry_date: t(0), start_time: null, end_time: null, hours: 1.0, billable: true }),
    row({ client: "Internal — Firm Admin", job_code: "Admin", notes: "Timesheet cleanup", entry_date: t(-1), start_time: "08:45:00", end_time: "09:30:00", hours: 0.75, billable: false }),
    row({ client: "Cedar Ridge Properties", job_code: "Audit", notes: "PBC updates", entry_date: t(-1), start_time: "09:45:00", end_time: "12:00:00", hours: 2.25, billable: true }),
    row({ client: "Cedar Ridge Properties", job_code: "Audit", notes: "Controls memo", entry_date: t(-1), start_time: "13:00:00", end_time: "15:30:00", hours: 2.5, billable: true }),
    row({ client: "Maple Street Dental", job_code: "Bookkeeping", notes: "Payroll JE", entry_date: t(-1), start_time: "15:45:00", end_time: "17:00:00", hours: 1.25, billable: true }),
    row({ client: "0969 Ocean View Road", job_code: "Bookkeeping", notes: "Vendor coding", entry_date: t(-2), start_time: "09:00:00", end_time: "11:30:00", hours: 2.5, billable: true }),
    row({ client: "Harris Family Trust", job_code: "Tax Return", notes: "Organizer call", entry_date: t(-2), start_time: "13:00:00", end_time: "14:00:00", hours: 1.0, billable: true }),
    row({ client: "Internal — Firm Admin", job_code: "Admin", notes: "CPE webinar", entry_date: t(-2), start_time: "14:30:00", end_time: "16:00:00", hours: 1.5, billable: false }),
    row({ client: "Summit Retail Group", job_code: "Tax Return", notes: "1040ES worksheet", entry_date: t(-3), start_time: "08:30:00", end_time: "10:30:00", hours: 2.0, billable: true }),
    row({ client: "Summit Retail Group", job_code: "Bookkeeping", notes: "Sales tax check", entry_date: t(-3), start_time: "10:45:00", end_time: "12:00:00", hours: 1.25, billable: true }),
    row({ client: "Greenfield Holdings LLC", job_code: "Advisory", notes: "Board deck", entry_date: t(-3), start_time: null, end_time: null, hours: 2.0, billable: true }),
    row({ client: "Lakeside Medical PLLC", job_code: "Bookkeeping", notes: "Month-end", entry_date: t(-4), start_time: "09:00:00", end_time: "11:00:00", hours: 2.0, billable: true }),
    row({ client: "Northgate Construction", job_code: "Tax Return", notes: "Extension prep", entry_date: t(-4), start_time: "11:30:00", end_time: "13:00:00", hours: 1.5, billable: true }),
    row({ client: "Pinecrest HOA", job_code: "Audit", notes: "Confirmations", entry_date: t(-4), start_time: "14:00:00", end_time: "16:30:00", hours: 2.5, billable: true }),
    row({ client: "0969 Ocean View Road", job_code: "Bookkeeping", notes: "Catch-up coding", entry_date: t(-5), start_time: "09:30:00", end_time: "12:00:00", hours: 2.5, billable: true }),
    row({ client: "Harris Family Trust", job_code: "Tax Return", notes: "Basis schedule", entry_date: t(-5), start_time: "13:15:00", end_time: "16:00:00", hours: 2.75, billable: true }),
    row({ client: "Cedar Ridge Properties", job_code: "Audit", notes: "Lease abstract", entry_date: t(-6), start_time: "08:45:00", end_time: "11:45:00", hours: 3.0, billable: true }),
    row({ client: "Internal — Firm Admin", job_code: "Admin", notes: "Supply order", entry_date: t(-6), start_time: "13:00:00", end_time: "13:30:00", hours: 0.5, billable: false }),
    row({ client: "Summit Retail Group", job_code: "Tax Return", notes: "Depreciation WB", entry_date: t(-6), start_time: "13:45:00", end_time: "16:15:00", hours: 2.5, billable: true }),
    row({ client: "Pinecrest HOA", job_code: "Bookkeeping", notes: "Owner statements", entry_date: t(-7), start_time: "10:00:00", end_time: "12:30:00", hours: 2.5, billable: true }),
    row({ client: "Greenfield Holdings LLC", job_code: "Advisory", notes: "Sensitivity table", entry_date: t(-8), start_time: null, end_time: null, hours: 1.5, billable: true }),
    row({ client: "Maple Street Dental", job_code: "Tax Return", notes: "Q2 extension", entry_date: t(-9), start_time: "09:00:00", end_time: "11:00:00", hours: 2.0, billable: true }),
    row({ client: "Lakeside Medical PLLC", job_code: "Payroll", notes: "Payroll review", entry_date: t(-10), start_time: "08:00:00", end_time: "09:30:00", hours: 1.5, billable: true }),
    row({ client: "Northgate Construction", job_code: "Bookkeeping", notes: "Job costing", entry_date: t(-11), start_time: "10:00:00", end_time: "12:00:00", hours: 2.0, billable: true }),
    row({ client: "Internal — Firm Admin", job_code: "Admin", notes: "Training", entry_date: t(-12), start_time: "14:00:00", end_time: "15:00:00", hours: 1.0, billable: false }),
  ];
}

export function createMockSeed(): TimeEntry[] {
  const base = seedEntries(todayISO());
  const t = (offset: number) => addDaysISO(todayISO(), offset);
  let id = 500;
  const extra = (
    staff_name: string,
    partial: Omit<TimeEntry, "id" | "staff_name" | "office" | "source_file">,
  ): TimeEntry => ({
    id: id++,
    staff_name,
    office: "GCD",
    source_file: "timmy-dashboard-mock",
    ...partial,
  });
  return [
    ...base,
    extra("Hannah Curtis", { client: "Harris Family Trust", job_code: "Tax Return", notes: "Organizer review", entry_date: t(0), start_time: "08:00:00", end_time: "10:00:00", hours: 2, billable: true }),
    extra("Hannah Curtis", { client: "0969 Ocean View Road", job_code: "Bookkeeping", notes: "Reconcile", entry_date: t(0), start_time: "10:15:00", end_time: "12:00:00", hours: 1.75, billable: true }),
    extra("Hannah Curtis", { client: "Greenfield Holdings LLC", job_code: "Advisory", notes: "Cash memo", entry_date: t(0), start_time: null, end_time: null, hours: 1.0, billable: true }),
    extra("Ken Green", { client: "Cedar Ridge Properties", job_code: "Audit", notes: "PBC walkthrough", entry_date: t(0), start_time: "09:30:00", end_time: "11:30:00", hours: 2, billable: true }),
    extra("Ken Green", { client: "Internal — Firm Admin", job_code: "Admin", notes: "Partner huddle", entry_date: t(0), start_time: "13:00:00", end_time: "14:00:00", hours: 1, billable: false }),
    extra("Andrea Rottman", { client: "Maple Street Dental", job_code: "Payroll", notes: "Payroll review", entry_date: t(0), start_time: null, end_time: null, hours: 1.5, billable: true }),
    extra("Hannah Curtis", { client: "Summit Retail Group", job_code: "Tax Return", notes: "1040ES", entry_date: t(-1), start_time: "09:00:00", end_time: "11:00:00", hours: 2, billable: true }),
    extra("Weston Brockbank", { client: "Northgate Construction", job_code: "Bookkeeping", notes: "Job costing", entry_date: t(-1), start_time: "14:00:00", end_time: "16:30:00", hours: 2.5, billable: true }),
  ];
}

export function createMockLiveSessions(): CurrentlyWorking[] {
  const now = Date.now();
  const iso = (msAgo: number) => new Date(now - msAgo).toISOString();
  return [
    {
      id: "live-hannah",
      staff_name: "Hannah Curtis",
      office: "GCD",
      client: "Harris Family Trust",
      job_code: "Tax Return",
      notes: "K-1 follow-up",
      task: "K-1 follow-up",
      started_at: iso(47 * 60 * 1000),
      planned_end_at: new Date(now + 73 * 60 * 1000).toISOString(),
      status: "active",
      local_session_id: "sess-hannah",
      updated_at: iso(0),
    },
    {
      id: "live-ken",
      staff_name: "Ken Green",
      office: "GCD",
      client: "Cedar Ridge Properties",
      job_code: "Audit",
      notes: "Fieldwork",
      task: "Fieldwork",
      started_at: iso(12 * 60 * 1000),
      planned_end_at: null,
      status: "active",
      local_session_id: "sess-ken",
      updated_at: iso(0),
    },
  ];
}
