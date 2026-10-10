import { decimalHoursToHM, hoursToMinutes } from "./hours-format";
import type { TimeEntry } from "./types/time-entry";

export type DetailSort = "date" | "duration";

export type TimeByJobFilters = {
  clients: string[];
  jobCodes: string[];
  staff: string[];
  offices: string[];
  search: string;
  detailSort: DetailSort;
};

export type TimeByJobActivity = {
  name: string;
  entries: TimeEntry[];
  totalMinutes: number;
  totalHours: number;
};

export type TimeByJobClient = {
  name: string;
  activities: TimeByJobActivity[];
  totalMinutes: number;
  totalHours: number;
};

export type TimeByJobGrouped = {
  clients: TimeByJobClient[];
  totalMinutes: number;
  totalHours: number;
};

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/** YYYY-MM-DD → MM-DD-YYYY. */
export function formatUsDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-");
  if (!y || !m || !d || y.length !== 4) return iso;
  return `${m}-${d}-${y}`;
}

/** MM-DD-YYYY → YYYY-MM-DD, or null when it is not a real calendar date. */
export function parseUsDate(text: string): string | null {
  const match = text.trim().match(/^(\d{2})-(\d{2})-(\d{4})$/);
  if (!match) return null;
  const month = Number(match[1]);
  const day = Number(match[2]);
  const year = Number(match[3]);
  const iso = `${match[3]}-${match[1]}-${match[2]}`;
  const utc = new Date(`${iso}T00:00:00Z`);
  if (utc.getUTCFullYear() !== year || utc.getUTCMonth() + 1 !== month || utc.getUTCDate() !== day) {
    return null;
  }
  return iso;
}

/** YYYY-MM-DD → "August 18, 2026". */
export function formatReportDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-");
  if (!y || !m || !d) return iso;
  const name = MONTHS[Number(m) - 1];
  const day = Number(d);
  if (!name || !Number.isFinite(day)) return iso;
  return `${name} ${day}, ${y}`;
}

/** Same calendar month → "August 2026". Otherwise the from–to range. */
export function monthSubtitle(from: string, to: string): string {
  const [fy, fm] = from.slice(0, 10).split("-");
  const [ty, tm] = to.slice(0, 10).split("-");
  if (fy && fm && fy === ty && fm === tm) {
    const name = MONTHS[Number(fm) - 1];
    if (name) return `${name} ${fy}`;
  }
  return `${formatReportDate(from)} – ${formatReportDate(to)}`;
}

export function formatMinutes(totalMinutes: number): string {
  return decimalHoursToHM(totalMinutes / 60);
}

/** Stored or summed hours, formatted once at two decimal places. */
export function formatDecimalHours(hours: number): string {
  return hours.toFixed(2);
}

function entryMinutes(entry: TimeEntry): number {
  return hoursToMinutes(entry.hours);
}

function selected(values: string[], value: string): boolean {
  return values.length === 0 || values.includes(value);
}

function matches(entry: TimeEntry, filters: TimeByJobFilters): boolean {
  if (!selected(filters.clients, entry.client)) return false;
  if (!selected(filters.jobCodes, entry.job_code)) return false;
  if (!selected(filters.staff, entry.staff_name)) return false;
  if (
    filters.offices.length > 0 &&
    !filters.offices.some((office) => office.toUpperCase() === entry.office.toUpperCase())
  ) {
    return false;
  }
  const q = filters.search.trim().toLowerCase();
  if (!q) return true;
  const hay = [entry.client, entry.job_code, entry.staff_name, entry.notes].join("\n").toLowerCase();
  return hay.includes(q);
}

function startKey(entry: TimeEntry): string {
  return entry.start_time ?? "99:99:99";
}

function compareDetail(a: TimeEntry, b: TimeEntry, sort: DetailSort): number {
  if (sort === "duration") {
    const byHours = b.hours - a.hours;
    if (byHours !== 0) return byHours;
  }
  const byDate = a.entry_date.localeCompare(b.entry_date);
  if (byDate !== 0) return byDate;
  return startKey(a).localeCompare(startKey(b));
}

export function groupTimeByJob(entries: TimeEntry[], filters: TimeByJobFilters): TimeByJobGrouped {
  const visible = entries.filter((entry) => matches(entry, filters));
  const byClient = new Map<string, TimeEntry[]>();
  for (const entry of visible) {
    const list = byClient.get(entry.client);
    if (list) list.push(entry);
    else byClient.set(entry.client, [entry]);
  }

  const clients: TimeByJobClient[] = [...byClient.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, rows]) => {
      const byActivity = new Map<string, TimeEntry[]>();
      for (const row of rows) {
        const list = byActivity.get(row.job_code);
        if (list) list.push(row);
        else byActivity.set(row.job_code, [row]);
      }
      const activities: TimeByJobActivity[] = [...byActivity.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([activityName, activityRows]) => {
          const sorted = [...activityRows].sort((a, b) => compareDetail(a, b, filters.detailSort));
          const totalMinutes = sorted.reduce((sum, row) => sum + entryMinutes(row), 0);
          const totalHours = sorted.reduce((sum, row) => sum + row.hours, 0);
          return { name: activityName, entries: sorted, totalMinutes, totalHours };
        });
      const totalMinutes = activities.reduce((sum, activity) => sum + activity.totalMinutes, 0);
      const totalHours = activities.reduce((sum, activity) => sum + activity.totalHours, 0);
      return { name, activities, totalMinutes, totalHours };
    });

  const totalMinutes = clients.reduce((sum, client) => sum + client.totalMinutes, 0);
  const totalHours = clients.reduce((sum, client) => sum + client.totalHours, 0);
  return { clients, totalMinutes, totalHours };
}

function csvCell(value: string): string {
  if (/[",\n\r]/.test(value)) return `"${value.replace(/"/g, '""')}"`;
  return value;
}

function csvLine(cells: string[]): string {
  return cells.map(csvCell).join(",");
}

/** Flat CSV of the grouped report, including activity, client, and grand totals. */
export function toCsv(grouped: TimeByJobGrouped): string {
  const lines = [csvLine(["client", "activity", "date", "name", "duration", "hours", "notes"])];
  for (const client of grouped.clients) {
    for (const activity of client.activities) {
      for (const entry of activity.entries) {
        lines.push(
          csvLine([
            client.name,
            activity.name,
            formatReportDate(entry.entry_date),
            entry.staff_name,
            decimalHoursToHM(entry.hours),
            formatDecimalHours(entry.hours),
            entry.notes,
          ]),
        );
      }
      lines.push(
        csvLine([
          client.name,
          `Total ${activity.name}`,
          "",
          "",
          formatMinutes(activity.totalMinutes),
          formatDecimalHours(activity.totalHours),
          "",
        ]),
      );
    }
    lines.push(
      csvLine([
        client.name,
        `Total ${client.name}`,
        "",
        "",
        formatMinutes(client.totalMinutes),
        formatDecimalHours(client.totalHours),
        "",
      ]),
    );
  }
  lines.push(
    csvLine([
      "TOTAL",
      "",
      "",
      "",
      formatMinutes(grouped.totalMinutes),
      formatDecimalHours(grouped.totalHours),
      "",
    ]),
  );
  return `${lines.join("\n")}\n`;
}
