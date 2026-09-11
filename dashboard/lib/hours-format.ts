/** Decimal hours → H:MM (nearest minute). */
export function decimalHoursToHM(hours: number): string {
  const totalMinutes = Math.round(Math.max(0, hours) * 60);
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  return `${h}:${String(m).padStart(2, "0")}`;
}

export function formatHoursHM(hours: number): string {
  return decimalHoursToHM(hours);
}

export function formatPercent(part: number, total: number): string {
  if (total <= 0) return "0%";
  return `${Math.round((part / total) * 100)}%`;
}

/** Parse H:MM or decimal string to hours. */
export function parseHoursInput(raw: string): number | null {
  const t = raw.trim();
  if (!t) return null;
  if (t.includes(":")) {
    const [hs, ms] = t.split(":");
    const h = Number(hs);
    const m = Number(ms);
    if (Number.isNaN(h) || Number.isNaN(m)) return null;
    return h + m / 60;
  }
  const n = Number(t);
  return Number.isNaN(n) ? null : n;
}

/** Parse time input to HH:MM:SS or null. */
export function parseTimeInput(raw: string): string | null {
  const t = raw.trim();
  if (!t) return null;
  const match = t.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(am|pm)?$/i);
  if (!match) return null;
  let h = Number(match[1]);
  const m = Number(match[2]);
  const s = match[3] ? Number(match[3]) : 0;
  const ampm = match[4]?.toLowerCase();
  if (ampm === "pm" && h < 12) h += 12;
  if (ampm === "am" && h === 12) h = 0;
  if (h > 23 || m > 59 || s > 59) return null;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function durationHoursFromTimes(start: string | null, end: string | null): number | null {
  if (!start || !end) return null;
  const [sh, sm] = start.split(":").map(Number);
  const [eh, em] = end.split(":").map(Number);
  let mins = eh * 60 + em - (sh * 60 + sm);
  if (mins < 0) mins += 24 * 60;
  return mins / 60;
}

/** Minutes since midnight from HH:MM:SS (or HH:MM). */
export function timeToMinutes(time: string): number {
  const [h, m] = time.split(":").map(Number);
  return h * 60 + (m || 0);
}

/** HH:MM:SS from minutes since midnight, wrapped into 0..24h. */
export function minutesToTime(totalMinutes: number): string {
  const day = 24 * 60;
  let mins = ((Math.round(totalMinutes) % day) + day) % day;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:00`;
}

/** Add decimal hours to a clock time → HH:MM:SS. */
export function addHoursToTime(start: string, hours: number): string {
  return minutesToTime(timeToMinutes(start) + hours * 60);
}

/** Subtract decimal hours from a clock time → HH:MM:SS. */
export function subtractHoursFromTime(end: string, hours: number): string {
  return minutesToTime(timeToMinutes(end) - hours * 60);
}

/** Display HH:MM from HH:MM:SS. */
export function displayHm(value: string | null | undefined): string {
  return value ? value.slice(0, 5) : "";
}
