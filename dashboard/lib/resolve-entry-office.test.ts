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

  it("uses the only client office even when the employee is at the other office", () => {
    expect(resolveEntryOffice("Acme", clients, "GCD")).toBe("MH");
    expect(resolveEntryOffice("Beta", [{ name: "Beta", office: "GCD" }], "MH")).toBe("GCD");
  });

  it("uses the employee home office for Holiday even when both offices exist", () => {
    const both = [
      { name: "Holiday", office: "GCD" },
      { name: "Holiday", office: "MH" },
    ];
    expect(resolveEntryOffice("Holiday", both, "GCD")).toBe("GCD");
    expect(resolveEntryOffice("Holiday", [{ name: "Holiday", office: "MH" }], "GCD")).toBe("GCD");
  });

  it("uses the chosen label when the same name is in both offices", () => {
    const both = [
      { name: "Acme", office: "GCD" },
      { name: "Acme", office: "MH" },
    ];
    expect(resolveEntryOffice("Acme", both, "GCD")).toBe("GCD");
    expect(resolveEntryOffice("Acme", both, "MH")).toBe("MH");
  });
});
