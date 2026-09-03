import { describe, expect, it, beforeEach } from "vitest";
import { mockProvider, resetMockStore } from "./data/entries-provider";

describe("firm entries fetch", () => {
  beforeEach(() => {
    resetMockStore();
  });

  it("returns mixed staff when staffName is omitted", async () => {
    const rows = await mockProvider.fetchEntries({
      dateFrom: "2000-01-01",
      dateTo: "2100-01-01",
    });
    const names = new Set(rows.map((e) => e.staff_name));
    expect(names.size).toBeGreaterThan(1);
    expect(names.has("Hannah Curtis")).toBe(true);
    expect(names.has("Ken Green")).toBe(true);
  });

  it("filters to one staff when staffName is set", async () => {
    const rows = await mockProvider.fetchEntries({
      staffName: "Hannah Curtis",
      dateFrom: "2000-01-01",
      dateTo: "2100-01-01",
    });
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.every((e) => e.staff_name === "Hannah Curtis")).toBe(true);
  });
});
