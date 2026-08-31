import type { ClientOption, JobCodeOption } from "./types/reference-data";

export const MOCK_CLIENTS: ClientOption[] = [
  { name: "Internal — Firm Admin" },
  { name: "0969 Ocean View Road" },
  { name: "Harris Family Trust" },
  { name: "Greenfield Holdings LLC" },
  { name: "Cedar Ridge Properties" },
  { name: "Maple Street Dental" },
  { name: "Summit Retail Group" },
  { name: "Pinecrest HOA" },
  { name: "Lakeside Medical PLLC" },
  { name: "Northgate Construction" },
];

export const MOCK_JOB_CODES: JobCodeOption[] = [
  { job_code: "Admin", account: "Administrative:Non-Billable", description: "Firm admin" },
  { job_code: "Bookkeeping", account: "Accounting Services:Hourly", description: "Bookkeeping" },
  { job_code: "Tax Return", account: "Tax Services:Hourly", description: "Tax return" },
  { job_code: "Audit", account: "Audit Services:Hourly", description: "Audit" },
  { job_code: "Advisory", account: "Advisory Services:Hourly", description: "Advisory" },
  { job_code: "Payroll", account: "Payroll Services:Hourly", description: "Payroll" },
];
