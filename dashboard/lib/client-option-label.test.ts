import { describe, expect, it } from "vitest";
import {
  clientLabels,
  formatClientLabel,
  parseClientLabel,
} from "./client-option-label";

describe("client-option-label", () => {
  it("formats office - name", () => {
    expect(formatClientLabel({ name: "Acme", office: "MH" })).toBe("MH - Acme");
  });

  it("parses labels", () => {
    expect(parseClientLabel("GCD - Ocean View")).toEqual({
      office: "GCD",
      name: "Ocean View",
    });
    expect(parseClientLabel("MH - A-1 EXPRESS")).toEqual({
      office: "MH",
      name: "A-1 EXPRESS",
    });
  });

  it("builds sorted unique labels", () => {
    const labels = clientLabels([
      { name: "Beta", office: "MH" },
      { name: "Alpha", office: "GCD" },
      { name: "Beta", office: "MH" },
    ]);
    expect(labels).toEqual(["GCD - Alpha", "MH - Beta"]);
  });

  it("shows only the home office for Holiday and both offices for other clients", () => {
    const labels = clientLabels(
      [
        { name: "Holiday", office: "GCD" },
        { name: "Holiday", office: "MH" },
        { name: "Acme", office: "GCD" },
        { name: "Acme", office: "MH" },
      ],
      "GCD",
    );
    expect(labels).toEqual(["GCD - Acme", "GCD - Holiday", "MH - Acme"]);
  });
});
