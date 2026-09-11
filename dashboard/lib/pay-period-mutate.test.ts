import { describe, expect, it } from "vitest";
import {
  canDashboardMutateEntry,
  isWithinEditWindow,
} from "./pay-period";

describe("isWithinEditWindow", () => {
  it("period A entry on day 15 is open on day 20", () => {
    const now = new Date("2026-08-20T15:00:00Z");
    expect(isWithinEditWindow("2026-08-15", now)).toBe(true);
  });

  it("period A entry is closed after day 24", () => {
    const now = new Date("2026-08-25T15:00:00Z");
    expect(isWithinEditWindow("2026-08-15", now)).toBe(false);
  });

  it("period B entry open through day 9 of next month", () => {
    const now = new Date("2026-09-09T15:00:00Z");
    expect(isWithinEditWindow("2026-08-28", now)).toBe(true);
  });

  it("period B entry closed after day 9", () => {
    const now = new Date("2026-09-10T15:00:00Z");
    expect(isWithinEditWindow("2026-08-28", now)).toBe(false);
  });
});

describe("canDashboardMutateEntry", () => {
  const now = new Date("2026-09-10T15:00:00Z");

  it("admin can mutate any entry any date", () => {
    expect(
      canDashboardMutateEntry({
        entryDate: "2026-08-01",
        actorIsAdmin: true,
        actorStaffName: "Aniket De",
        entryStaffName: "Alex Daley",
        now,
      }),
    ).toBe(true);
  });

  it("employee can mutate own in-window entry", () => {
    expect(
      canDashboardMutateEntry({
        entryDate: "2026-09-10",
        actorIsAdmin: false,
        actorStaffName: "Alex Daley",
        entryStaffName: "Alex Daley",
        now,
      }),
    ).toBe(true);
  });

  it("employee cannot mutate out-of-window entry", () => {
    expect(
      canDashboardMutateEntry({
        entryDate: "2026-08-28",
        actorIsAdmin: false,
        actorStaffName: "Alex Daley",
        entryStaffName: "Alex Daley",
        now,
      }),
    ).toBe(false);
  });

  it("employee cannot mutate another person's entry", () => {
    expect(
      canDashboardMutateEntry({
        entryDate: "2026-09-10",
        actorIsAdmin: false,
        actorStaffName: "Alex Daley",
        entryStaffName: "Ken Green",
        now,
      }),
    ).toBe(false);
  });
});
