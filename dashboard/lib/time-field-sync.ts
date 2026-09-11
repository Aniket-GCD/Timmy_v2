import {
  addHoursToTime,
  displayHm,
  durationHoursFromTimes,
  formatHoursHM,
  parseHoursInput,
  parseTimeInput,
  subtractHoursFromTime,
} from "./hours-format";

export type TimeFieldTouched = "start" | "end" | "duration";

export type TimeFieldState = {
  startHm: string;
  endHm: string;
  hoursHm: string;
  hours: number | null;
};

/**
 * Reconcile Start / End / Duration after the user edits one field.
 * Incomplete parses leave siblings unchanged (no thrash mid-typing).
 */
export function reconcileTimeFields(input: {
  startHm: string;
  endHm: string;
  hoursHm: string;
  touched: TimeFieldTouched;
}): TimeFieldState {
  const startHm = input.startHm;
  const endHm = input.endHm;
  const hoursHm = input.hoursHm;
  const start = startHm.trim() ? parseTimeInput(startHm) : null;
  const end = endHm.trim() ? parseTimeInput(endHm) : null;
  const hoursParsed = hoursHm.trim() ? parseHoursInput(hoursHm) : null;

  // Touched field must parse before we rewrite siblings.
  if (input.touched === "start" && startHm.trim() && !start) {
    return { startHm, endHm, hoursHm, hours: hoursParsed };
  }
  if (input.touched === "end" && endHm.trim() && !end) {
    return { startHm, endHm, hoursHm, hours: hoursParsed };
  }
  if (input.touched === "duration" && hoursHm.trim() && (hoursParsed == null || hoursParsed <= 0)) {
    return { startHm, endHm, hoursHm, hours: hoursParsed };
  }

  if (input.touched === "start") {
    if (!start) {
      return { startHm, endHm, hoursHm, hours: hoursParsed };
    }
    if (end) {
      const hours = durationHoursFromTimes(start, end);
      if (hours != null && hours > 0) {
        return {
          startHm: displayHm(start),
          endHm: displayHm(end),
          hoursHm: formatHoursHM(hours),
          hours,
        };
      }
      return { startHm: displayHm(start), endHm, hoursHm, hours: hoursParsed };
    }
    if (hoursParsed != null && hoursParsed > 0) {
      const nextEnd = addHoursToTime(start, hoursParsed);
      return {
        startHm: displayHm(start),
        endHm: displayHm(nextEnd),
        hoursHm: formatHoursHM(hoursParsed),
        hours: hoursParsed,
      };
    }
    return { startHm: displayHm(start), endHm, hoursHm, hours: hoursParsed };
  }

  if (input.touched === "end") {
    if (!end) {
      return { startHm, endHm, hoursHm, hours: hoursParsed };
    }
    if (start) {
      const hours = durationHoursFromTimes(start, end);
      if (hours != null && hours > 0) {
        return {
          startHm: displayHm(start),
          endHm: displayHm(end),
          hoursHm: formatHoursHM(hours),
          hours,
        };
      }
      return { startHm, endHm: displayHm(end), hoursHm, hours: hoursParsed };
    }
    if (hoursParsed != null && hoursParsed > 0) {
      const nextStart = subtractHoursFromTime(end, hoursParsed);
      return {
        startHm: displayHm(nextStart),
        endHm: displayHm(end),
        hoursHm: formatHoursHM(hoursParsed),
        hours: hoursParsed,
      };
    }
    return { startHm, endHm: displayHm(end), hoursHm, hours: hoursParsed };
  }

  // touched === "duration"
  if (hoursParsed == null || hoursParsed <= 0) {
    return { startHm, endHm, hoursHm, hours: hoursParsed };
  }
  if (start) {
    const nextEnd = addHoursToTime(start, hoursParsed);
    return {
      startHm: displayHm(start),
      endHm: displayHm(nextEnd),
      hoursHm: formatHoursHM(hoursParsed),
      hours: hoursParsed,
    };
  }
  if (end) {
    const nextStart = subtractHoursFromTime(end, hoursParsed);
    return {
      startHm: displayHm(nextStart),
      endHm: displayHm(end),
      hoursHm: formatHoursHM(hoursParsed),
      hours: hoursParsed,
    };
  }
  // Duration-only
  return {
    startHm: "",
    endHm: "",
    hoursHm: formatHoursHM(hoursParsed),
    hours: hoursParsed,
  };
}
