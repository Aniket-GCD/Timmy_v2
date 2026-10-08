import { describe, expect, it } from "vitest";
import { canonicalJobCode } from "./canonical-job-code";

describe("canonicalJobCode", () => {
  it("uses the job_codes spelling and leaves unknown codes unchanged", () => {
    const catalog = [{ job_code: "ACCT" }];
    expect(canonicalJobCode("acct", catalog)).toBe("ACCT");
    expect(canonicalJobCode("Acct", catalog)).toBe("ACCT");
    expect(canonicalJobCode("Mystery", catalog)).toBe("Mystery");
  });
});
