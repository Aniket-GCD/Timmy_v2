import { describe, expect, it } from "vitest";
import { payPeriodForDate, thisPayPeriod, lastPayPeriod } from "./pay-period";

describe("pay-period", () => {
  it("period A is 9-23", () => {
    const p = payPeriodForDate("2026-08-15");
    expect(p.startISO).toBe("2026-08-09");
    expect(p.endISO).toBe("2026-08-23");
  });

  it("period B crosses month from 24th", () => {
    const p = payPeriodForDate("2026-08-28");
    expect(p.startISO).toBe("2026-08-24");
    expect(p.endISO).toBe("2026-09-08");
  });

  it("days 1-8 belong to prior month 24th period", () => {
    const p = payPeriodForDate("2026-09-05");
    expect(p.startISO).toBe("2026-08-24");
    expect(p.endISO).toBe("2026-09-08");
  });

  it("this and last pay period differ", () => {
    const cur = thisPayPeriod("2026-09-10");
    const prev = lastPayPeriod("2026-09-10");
    expect(cur.startISO).not.toBe(prev.startISO);
  });
});
