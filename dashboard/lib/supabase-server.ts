import type { ClientOption, JobCodeOption } from "./types/reference-data";

export function getSupabaseConfig() {
  const url = (process.env.SUPABASE_URL ?? "").trim().replace(/\/$/, "");
  const key =
    (process.env.SUPABASE_SERVICE_ROLE_KEY ?? "").trim() ||
    (process.env.SUPABASE_KEY ?? "").trim() ||
    (process.env.SUPABASE_ANON_KEY ?? "").trim();
  return { url, key };
}

export function getDashboardStaff() {
  return {
    staffName: (process.env.DASHBOARD_STAFF_NAME ?? "Aniket").trim(),
    office: (process.env.DASHBOARD_OFFICE ?? "GCD").trim(),
  };
}

export async function supabaseFetch<T>(
  path: string,
  init?: RequestInit & { prefer?: string },
): Promise<T> {
  const { url, key } = getSupabaseConfig();
  if (!url || !key) throw new Error("Supabase is not configured");

  const headers: Record<string, string> = {
    apikey: key,
    Accept: "application/json",
    "User-Agent": "timmy-dashboard/1.0",
  };
  if (!key.startsWith("sb_secret_")) {
    headers.Authorization = `Bearer ${key}`;
  }
  if (init?.body) headers["Content-Type"] = "application/json";
  if (init?.prefer) headers.Prefer = init.prefer;

  const res = await fetch(`${url}/rest/v1/${path}`, { ...init, headers });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const ENTRIES_TABLE = process.env.SUPABASE_ENTRIES_TABLE ?? "time_entries_timmy_v2";
const CLIENTS_TABLE = process.env.SUPABASE_CLIENTS_TABLE ?? "clients";
const JOB_CODES_TABLE = process.env.SUPABASE_JOB_CODES_TABLE ?? "job_codes";
const EMPLOYEES_TABLE = process.env.SUPABASE_EMPLOYEES_TABLE ?? "employees";
const CURRENTLY_WORKING_TABLE =
  process.env.SUPABASE_CURRENTLY_WORKING_TABLE ?? "currently_working";

export function entriesTable() {
  return ENTRIES_TABLE;
}

export function employeesTable() {
  return EMPLOYEES_TABLE;
}

export function currentlyWorkingTable() {
  return CURRENTLY_WORKING_TABLE;
}

export async function fetchClientsFromSupabase(): Promise<ClientOption[]> {
  const rows = await supabaseFetch<Array<Record<string, unknown>>>(
    `${CLIENTS_TABLE}?select=name&order=name`,
  );
  return rows.map((r) => ({ name: String(r.name ?? r.display_name ?? "") })).filter((c) => c.name);
}

export async function fetchJobCodesFromSupabase(): Promise<JobCodeOption[]> {
  const rows = await supabaseFetch<Array<Record<string, unknown>>>(
    `${JOB_CODES_TABLE}?select=job_code,account,description&order=job_code`,
  );
  return rows.map((r) => ({
    job_code: String(r.job_code ?? ""),
    account: String(r.account ?? ""),
    description: r.description ? String(r.description) : undefined,
  }));
}
