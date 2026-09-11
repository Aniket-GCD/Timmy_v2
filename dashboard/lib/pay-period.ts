/** Pay period + edit windows — mirrors timeassist/pay_period.py (America/Chicago). */

const SUPERUSER_NAMES = new Set([
  "shanya schweitzer",
  "nathan moorhead",
  "hannah curtis",
  "alex daley",
  "julia moorhead",
]);

export type ChicagoParts = {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
};

export function chicagoParts(now: Date = new Date()): ChicagoParts {
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Chicago",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "numeric",
    second: "numeric",
    hour12: false,
  });
  const parts = formatter.formatToParts(now);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  return {
    year: get("year"),
    month: get("month"),
    day: get("day"),
    hour: get("hour"),
    minute: get("minute"),
    second: get("second"),
  };
}

export function chicagoTodayISO(now: Date = new Date()): string {
  const p = chicagoParts(now);
  return isoDate(p.year, p.month, p.day);
}

function isoDate(y: number, m: number, d: number): string {
  return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

function parseISO(iso: string): { y: number; m: number; d: number } {
  const [y, m, d] = iso.split("-").map(Number);
  return { y, m, d };
}

export type PeriodBounds = { startISO: string; endISO: string };

/** Entry-date bounds for the pay period containing `iso`. */
export function payPeriodForDate(iso: string): PeriodBounds {
  const { y, m, d } = parseISO(iso);
  if (d >= 9 && d <= 23) {
    return { startISO: isoDate(y, m, 9), endISO: isoDate(y, m, 23) };
  }
  if (d >= 24) {
    const endMonth = m === 12 ? 1 : m + 1;
    const endYear = m === 12 ? y + 1 : y;
    return { startISO: isoDate(y, m, 24), endISO: isoDate(endYear, endMonth, 8) };
  }
  const startMonth = m === 1 ? 12 : m - 1;
  const startYear = m === 1 ? y - 1 : y;
  return { startISO: isoDate(startYear, startMonth, 24), endISO: isoDate(y, m, 8) };
}

export function thisPayPeriod(anchorISO?: string): PeriodBounds {
  return payPeriodForDate(anchorISO ?? chicagoTodayISO());
}

export function lastPayPeriod(anchorISO?: string): PeriodBounds {
  const current = payPeriodForDate(anchorISO ?? chicagoTodayISO());
  const dayBefore = addDaysISO(current.startISO, -1);
  return payPeriodForDate(dayBefore);
}

function addDaysISO(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  dt.setDate(dt.getDate() + days);
  return isoDate(dt.getFullYear(), dt.getMonth() + 1, dt.getDate());
}

export function dateISOsInRange(startISO: string, endISO: string): string[] {
  const out: string[] = [];
  let cur = startISO;
  while (cur <= endISO) {
    out.push(cur);
    cur = addDaysISO(cur, 1);
  }
  return out;
}

export type EditWindow = { startMs: number; endMs: number };

function chicagoWallToComparable(
  y: number,
  mo: number,
  d: number,
  h: number,
  mi: number,
  s: number,
): number {
  // Compare using ISO string sort in Chicago local components
  return Number(
    `${y}${String(mo).padStart(2, "0")}${String(d).padStart(2, "0")}${String(h).padStart(2, "0")}${String(mi).padStart(2, "0")}${String(s).padStart(2, "0")}`,
  );
}

function editWindowForChicagoWall(entryDateISO: string): EditWindow {
  const { y, m, d } = parseISO(entryDateISO);
  if (d >= 9 && d <= 23) {
    return {
      startMs: chicagoWallToComparable(y, m, 9, 0, 0, 0),
      endMs: chicagoWallToComparable(y, m, 24, 23, 59, 59),
    };
  }
  if (d >= 24) {
    const endMonth = m === 12 ? 1 : m + 1;
    const endYear = m === 12 ? y + 1 : y;
    return {
      startMs: chicagoWallToComparable(y, m, 24, 0, 0, 0),
      endMs: chicagoWallToComparable(endYear, endMonth, 9, 23, 59, 59),
    };
  }
  const startMonth = m === 1 ? 12 : m - 1;
  const startYear = m === 1 ? y - 1 : y;
  return {
    startMs: chicagoWallToComparable(startYear, startMonth, 24, 0, 0, 0),
    endMs: chicagoWallToComparable(y, m, 9, 23, 59, 59),
  };
}

export function chicagoNowComparable(now: Date = new Date()): number {
  const p = chicagoParts(now);
  return chicagoWallToComparable(p.year, p.month, p.day, p.hour, p.minute, p.second);
}

/** Chicago pay-period edit window only — no staff / superuser / is_admin. */
export function isWithinEditWindow(entryDateISO: string, now: Date = new Date()): boolean {
  const win = editWindowForChicagoWall(entryDateISO);
  const cur = chicagoNowComparable(now);
  return cur >= win.startMs && cur <= win.endMs;
}

/** Timmy parity: named superusers OR within edit window. */
export function isEditable(entryDateISO: string, staffName: string, now: Date = new Date()): boolean {
  if (isSuperuser(staffName)) return true;
  return isWithinEditWindow(entryDateISO, now);
}

export function isSuperuser(staffName: string): boolean {
  return SUPERUSER_NAMES.has((staffName || "").trim().toLowerCase());
}

export type DashboardMutateArgs = {
  entryDate: string;
  actorIsAdmin: boolean;
  actorStaffName: string;
  entryStaffName: string;
  now?: Date;
};

/**
 * Dashboard mutation gate: admins may always mutate any row;
 * employees only their own rows inside the edit window.
 */
export function canDashboardMutateEntry(args: DashboardMutateArgs): boolean {
  if (args.actorIsAdmin) return true;
  if ((args.entryStaffName || "").trim() !== (args.actorStaffName || "").trim()) {
    return false;
  }
  return isWithinEditWindow(args.entryDate, args.now);
}
