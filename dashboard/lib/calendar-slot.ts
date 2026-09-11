import { DAY_END_MIN, DAY_START_MIN } from "./calendar-blocks";

const SNAP_MIN = 15;
const DEFAULT_DURATION_MIN = 60;

export function minutesToTime(totalMin: number): string {
  const clamped = Math.max(0, Math.min(DAY_END_MIN, totalMin));
  const h = Math.floor(clamped / 60);
  const m = clamped % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:00`;
}

/** Snap minutes to a 15-minute grid (floor). */
export function snapMinutes(totalMin: number, step = SNAP_MIN): number {
  return Math.floor(totalMin / step) * step;
}

/**
 * Map a Y offset within a day column (px) to a create slot.
 * Axis runs DAY_START_MIN → DAY_END_MIN over `bodyHeightPx`.
 */
export function slotFromDayColumnClick(
  offsetY: number,
  bodyHeightPx: number,
  axisStart = DAY_START_MIN,
  axisEnd = DAY_END_MIN,
): { start_time: string; end_time: string } {
  const span = axisEnd - axisStart;
  const ratio = Math.max(0, Math.min(1, offsetY / Math.max(1, bodyHeightPx)));
  let startMin = snapMinutes(axisStart + ratio * span);
  if (startMin >= axisEnd - SNAP_MIN) {
    startMin = axisEnd - DEFAULT_DURATION_MIN;
  }
  const endMin = Math.min(axisEnd, startMin + DEFAULT_DURATION_MIN);
  return {
    start_time: minutesToTime(startMin),
    end_time: minutesToTime(endMin),
  };
}
