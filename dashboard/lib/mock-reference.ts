import type { ClientOption, JobCodeOption } from "./types/reference-data";

export const MOCK_CLIENTS: ClientOption[] = [
  { name: "Internal — Firm Admin", office: "GCD" },
  { name: "0969 Ocean View Road", office: "GCD" },
  { name: "Harris Family Trust", office: "GCD" },
  { name: "Greenfield Holdings LLC", office: "GCD" },
  { name: "Cedar Ridge Properties", office: "GCD" },
  { name: "Maple Street Dental", office: "MH" },
  { name: "Summit Retail Group", office: "MH" },
  { name: "Pinecrest HOA", office: "MH" },
  { name: "Lakeside Medical PLLC", office: "MH" },
  { name: "Northgate Construction", office: "MH" },
  { name: "Unassigned", office: "GCD" },
  { name: "Unassigned", office: "MH" },
];

export const MOCK_JOB_CODES: JobCodeOption[] = [
  { job_code: "Admin", account: "Administrative:Non-Billable", description: "Firm admin" },
  { job_code: "Bookkeeping", account: "Accounting Services:Hourly", description: "Bookkeeping" },
  { job_code: "Tax Return", account: "Tax Services:Hourly", description: "Tax return" },
  { job_code: "Audit", account: "Audit Services:Hourly", description: "Audit" },
  { job_code: "Advisory", account: "Advisory Services:Hourly", description: "Advisory" },
  { job_code: "Payroll", account: "Payroll Services:Hourly", description: "Payroll" },
];
