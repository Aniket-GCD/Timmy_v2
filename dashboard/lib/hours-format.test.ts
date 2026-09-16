import { describe, expect, it } from "vitest";
import { formatTime12, parseLocalStartMs, parseTimeInput } from "./hours-format";

describe("formatTime12", () => {
  it("formats 24h storage as AM/PM", () => {
    expect(formatTime12("09:05:00")).toBe("9:05 AM");
    expect(formatTime12("17:15:00")).toBe("5:15 PM");
    expect(formatTime12("00:00:00")).toBe("12:00 AM");
    expect(formatTime12("12:30:00")).toBe("12:30 PM");
  });

  it("round-trips with parseTimeInput", () => {
    const shown = formatTime12("13:45:00");
    expect(shown).toBe("1:45 PM");
    expect(parseTimeInput(shown)).toBe("13:45:00");
  });
});

describe("parseLocalStartMs", () => {
  it("strips Z and parses as local wall clock", () => {
    const withZ = parseLocalStartMs("2026-09-16T14:00:00Z");
    const naive = parseLocalStartMs("2026-09-16T14:00:00");
    expect(withZ).toBe(naive);
    expect(Number.isNaN(withZ)).toBe(false);
  });

  it("strips numeric offsets", () => {
    const withOffset = parseLocalStartMs("2026-09-16T14:00:00-05:00");
    const naive = parseLocalStartMs("2026-09-16T14:00:00");
    expect(withOffset).toBe(naive);
  });
});
