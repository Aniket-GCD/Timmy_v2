/** Apply chart / table filters to entries (pure — for tests + Dashboard). */

export type ChartTableFilters = {
  day?: string | null;
  client?: string | null;
  job?: string | null;
};

export function applyChartFilters<
  T extends { entry_date: string; client: string; job_code: string },
>(entries: T[], filters: ChartTableFilters): T[] {
  let out = entries;
  const day = filters.day?.trim();
  const client = filters.client?.trim();
  const job = filters.job?.trim();
  if (day) out = out.filter((e) => e.entry_date === day);
  if (client) out = out.filter((e) => e.client === client);
  if (job) out = out.filter((e) => e.job_code === job);
  return out;
}
