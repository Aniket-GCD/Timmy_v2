import type { TimeEntry } from "./types/time-entry";

/** Full civil day: 12:00 AM through 11:59 PM (axis end is next midnight). */
export const DAY_START_MIN = 0;
export const DAY_END_MIN = 24 * 60;

export function timeToMinutes(value: string): number {
  const [h, m] = value.split(":").map(Number);
  return h * 60 + (m || 0);
}

export function isScheduled(entry: Pick<TimeEntry, "start_time" | "end_time">): boolean {
  return Boolean(entry.start_time && entry.end_time);
}

export function splitScheduled(entries: TimeEntry[]): {
  scheduled: TimeEntry[];
  unscheduled: TimeEntry[];
} {
  const scheduled: TimeEntry[] = [];
  const unscheduled: TimeEntry[] = [];
  for (const e of entries) {
    if (isScheduled(e)) scheduled.push(e);
    else unscheduled.push(e);
  }
  return { scheduled, unscheduled };
}

export function calendarAxisMinutes(): { start: number; end: number } {
  return { start: DAY_START_MIN, end: DAY_END_MIN };
}

export type LanedBlock = {
  entry: TimeEntry;
  startMin: number;
  endMin: number;
  lane: number;
  laneCount: number;
};

/** Greedy overlap lanes per day (slight horizontal offset). */
export function assignLanes(entries: TimeEntry[]): LanedBlock[] {
  const timed = entries
    .filter(isScheduled)
    .map((entry) => ({
      entry,
      startMin: timeToMinutes(entry.start_time!),
      endMin: timeToMinutes(entry.end_time!),
      lane: 0,
      laneCount: 1,
    }))
    .sort((a, b) => a.startMin - b.startMin || a.endMin - b.endMin);

  const laneEnds: number[] = [];
  for (const block of timed) {
    let lane = laneEnds.findIndex((end) => end <= block.startMin);
    if (lane < 0) {
      lane = laneEnds.length;
      laneEnds.push(block.endMin);
    } else {
      laneEnds[lane] = block.endMin;
    }
    block.lane = lane;
  }
  const laneCount = Math.max(1, laneEnds.length);
  for (const block of timed) block.laneCount = laneCount;
  return timed;
}

export function hourTicks(startMin: number, endMin: number): number[] {
  const ticks: number[] = [];
  for (let m = startMin; m < endMin; m += 60) ticks.push(m);
  return ticks;
}

export function formatHourLabel(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const suffix = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12} ${suffix}`;
}
