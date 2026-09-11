import type { ClientOption, JobCodeOption } from "./types/reference-data";

let warnedWeakKey = false;
let warnedSecretLacksGrants = false;

/** True when the server key is anon/publishable (Auth-safe) rather than service/secret. */
export function isPublishableOnlyKey(key: string): boolean {
  const k = key.trim();
  if (!k) return false;
  if (k.startsWith("sb_secret_")) return false;
  if (k.startsWith("sb_publishable_")) return true;
  return false;
}

export function isSecretKey(key: string): boolean {
  return key.trim().startsWith("sb_secret_");
}

function firstNonEmpty(...vals: Array<string | undefined>): string {
  for (const v of vals) {
    const t = (v ?? "").trim();
    if (t) return t;
  }
  return "";
}

/** Anon/publishable key used for Auth-aligned reads (has SELECT grants in this project). */
export function getPublishableKey(): string {
  const fromKey = (process.env.SUPABASE_KEY ?? "").trim();
  return firstNonEmpty(
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
    process.env.SUPABASE_ANON_KEY,
    isPublishableOnlyKey(fromKey) ? fromKey : "",
  );
}

/**
 * Elevated server key (service_role JWT or sb_secret_).
 * Note: some projects' sb_secret_ role lacks table GRANTs (42501); prefer publishable for reads.
 */
export function getElevatedKey(): string {
  return firstNonEmpty(process.env.SUPABASE_SERVICE_ROLE_KEY, process.env.SUPABASE_KEY);
}

export type SupabaseKeyPurpose = "read" | "write";

export function getSupabaseConfig(purpose: SupabaseKeyPurpose = "read") {
  const url = (process.env.SUPABASE_URL ?? "").trim().replace(/\/$/, "");
  const publishable = getPublishableKey();
  const elevated = getElevatedKey();
  const serviceRole = (process.env.SUPABASE_SERVICE_ROLE_KEY ?? "").trim();

  let key = "";
  if (purpose === "read") {
    // Prefer publishable for SELECT — sb_secret_ often has no table GRANTs (blank UI / 500s).
    key = publishable || elevated;
  } else if (serviceRole.startsWith("eyJ")) {
    // Classic service_role JWT — full access
    key = serviceRole;
  } else if (isSecretKey(serviceRole)) {
    if (!warnedSecretLacksGrants) {
      warnedSecretLacksGrants = true;
      console.warn(
        "[timmy-dashboard] SUPABASE_SERVICE_ROLE_KEY is sb_secret_. " +
          "If PostgREST returns 42501 privilege errors, that secret role needs GRANT on employees / " +
          "time_entries_timmy_v2 / currently_working, or use the legacy service_role JWT (eyJ…) from " +
          "Supabase → Settings → API. Using publishable key for writes when available so the dashboard stays up.",
      );
    }
    // Prefer publishable for writes when it has grants; fall back to secret.
    key = publishable || serviceRole || elevated;
  } else {
    key = elevated || publishable;
  }

  if (!warnedWeakKey && key && isPublishableOnlyKey(key) && purpose === "write") {
    warnedWeakKey = true;
    console.warn(
      "[timmy-dashboard] PostgREST writes are using a publishable key. " +
        "Prefer a privileged service_role JWT (eyJ…) in SUPABASE_SERVICE_ROLE_KEY for reliable updates.",
    );
  }

  return { url, key };
}

export function getDashboardStaff() {
  return {
    staffName: (process.env.DASHBOARD_STAFF_NAME ?? "Aniket").trim(),
    office: (process.env.DASHBOARD_OFFICE ?? "GCD").trim(),
  };
}

function headersForKey(key: string, init?: RequestInit & { prefer?: string }): Record<string, string> {
  const headers: Record<string, string> = {
    apikey: key,
    Accept: "application/json",
    // sb_secret_ keys are blocked unless UA looks like curl (same as Timmy supabase_ref).
    "User-Agent": isSecretKey(key) ? "curl/8.5.0" : "timmy-dashboard/1.0",
  };
  if (!isSecretKey(key)) {
    headers.Authorization = `Bearer ${key}`;
  }
  if (init?.body) headers["Content-Type"] = "application/json";
  if (init?.prefer) headers.Prefer = init.prefer;
  return headers;
}

export async function supabaseFetch<T>(
  path: string,
  init?: RequestInit & { prefer?: string },
): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const purpose: SupabaseKeyPurpose =
    method === "GET" || method === "HEAD" ? "read" : "write";
  const { url, key } = getSupabaseConfig(purpose);
  if (!url || !key) throw new Error("Supabase is not configured");

  const res = await fetch(`${url}/rest/v1/${path}`, {
    ...init,
    headers: headersForKey(key, init),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/** PostgREST return=representation must include at least one row after INSERT/UPDATE. */
export function requireRepresentationRow(
  rows: Array<Record<string, unknown>> | null | undefined,
): Record<string, unknown> {
  if (!Array.isArray(rows) || rows.length === 0 || !rows[0]) {
    throw new Error("EMPTY_WRITE_REPRESENTATION");
  }
  return rows[0];
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
