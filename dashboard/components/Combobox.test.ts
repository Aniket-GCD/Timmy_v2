import { describe, expect, it } from "vitest";
import { filterComboboxOptions } from "@/components/Combobox";

describe("filterComboboxOptions", () => {
  const names = Array.from({ length: 40 }, (_, i) => `Client ${String(i).padStart(2, "0")}`);

  it("caps empty query preview", () => {
    expect(filterComboboxOptions(names, "").length).toBe(25);
  });

  it("returns many search hits (not stuck at 12)", () => {
    const hits = filterComboboxOptions(names, "Client");
    expect(hits.length).toBeGreaterThan(12);
    expect(hits.length).toBe(40);
  });
});
