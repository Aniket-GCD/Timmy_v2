import { describe, expect, it } from "vitest";
import { resolveEntryOffice } from "./resolve-entry-office";

describe("resolveEntryOffice", () => {
  const clients = [
    { name: "Acme", office: "MH" },
    { name: "Beta", office: "GCD" },
    { name: "Unassigned", office: "GCD" },
    { name: "Unassigned", office: "MH" },
  ];

  it("uses client office for real clients", () => {
    expect(resolveEntryOffice("Acme", clients, "GCD")).toBe("MH");
    expect(resolveEntryOffice("Beta", clients, "MH")).toBe("GCD");
  });

  it("uses staff fallback for Unassigned", () => {
    expect(resolveEntryOffice("Unassigned", clients, "MH")).toBe("MH");
    expect(resolveEntryOffice("Unassigned", clients, "GCD")).toBe("GCD");
  });
});
