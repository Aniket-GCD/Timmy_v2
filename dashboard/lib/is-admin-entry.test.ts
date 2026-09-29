import { describe, expect, it } from "vitest";
import { isAdminEntry, isAdminJobCode } from "./types/time-entry";

describe("isAdminJobCode", () => {
  it("matches Admin and Administrative", () => {
    expect(isAdminJobCode("Admin")).toBe(true);
    expect(isAdminJobCode("Administrative")).toBe(true);
    expect(isAdminJobCode("administrative")).toBe(true);
    expect(isAdminJobCode("Consulting")).toBe(false);
  });
});

describe("isAdminEntry", () => {
  it("matches client named Admin regardless of job code", () => {
    expect(isAdminEntry({ job_code: "Administrative", client: "Admin" })).toBe(true);
    expect(isAdminEntry({ job_code: "Consulting", client: "Admin" })).toBe(true);
  });

  it("does not match Administrative job code on other clients", () => {
    expect(isAdminEntry({ job_code: "Administrative", client: "Staff Meeting" })).toBe(false);
    expect(isAdminEntry({ job_code: "Admin", client: "Acme" })).toBe(false);
  });

  it("does not match unrelated billable work", () => {
    expect(isAdminEntry({ job_code: "Consulting", client: "TRI STATE" })).toBe(false);
  });
});
