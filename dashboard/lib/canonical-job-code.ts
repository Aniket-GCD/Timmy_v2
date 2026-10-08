import type { JobCodeOption } from "./types/reference-data";

/** Spelling from job_codes when the name matches, ignoring case. */
export function canonicalJobCode(raw: string, catalog: Pick<JobCodeOption, "job_code">[]): string {
  const wanted = raw.trim().toLowerCase();
  if (!wanted) return raw;
  const hit = catalog.find((row) => row.job_code.trim().toLowerCase() === wanted);
  return hit?.job_code ?? raw;
}
