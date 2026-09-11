import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getSupabaseConfig,
  isPublishableOnlyKey,
  isSecretKey,
  requireRepresentationRow,
  supabaseFetch,
} from "./supabase-server";

describe("isPublishableOnlyKey", () => {
  it("detects sb_publishable_", () => {
    expect(isPublishableOnlyKey("sb_publishable_abc")).toBe(true);
  });

  it("allows sb_secret_", () => {
    expect(isPublishableOnlyKey("sb_secret_abc")).toBe(false);
  });
});

describe("isSecretKey", () => {
  it("detects sb_secret_", () => {
    expect(isSecretKey("sb_secret_abc")).toBe(true);
  });
});

describe("requireRepresentationRow", () => {
  it("returns first row", () => {
    const row = { id: 1, staff_name: "A" };
    expect(requireRepresentationRow([row])).toBe(row);
  });

  it("throws on empty array", () => {
    expect(() => requireRepresentationRow([])).toThrow("EMPTY_WRITE_REPRESENTATION");
  });

  it("throws on null", () => {
    expect(() => requireRepresentationRow(null)).toThrow("EMPTY_WRITE_REPRESENTATION");
  });
});

describe("getSupabaseConfig key selection", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("prefers publishable for reads when sb_secret service role is set", () => {
    vi.stubEnv("SUPABASE_URL", "https://example.supabase.co");
    vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_test");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "sb_publishable_test");
    vi.stubEnv("SUPABASE_KEY", "");
    expect(getSupabaseConfig("read").key).toBe("sb_publishable_test");
  });

  it("uses publishable for writes when service role is sb_secret_", () => {
    vi.stubEnv("SUPABASE_URL", "https://example.supabase.co");
    vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_test");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "sb_publishable_test");
    vi.stubEnv("SUPABASE_KEY", "");
    expect(getSupabaseConfig("write").key).toBe("sb_publishable_test");
  });

  it("uses eyJ service role for writes", () => {
    vi.stubEnv("SUPABASE_URL", "https://example.supabase.co");
    vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "eyJhbGciOiServiceRoleTest");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "sb_publishable_test");
    expect(getSupabaseConfig("write").key).toBe("eyJhbGciOiServiceRoleTest");
  });
});

describe("supabaseFetch secret key headers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("uses curl UA and omits Bearer when write key is sb_secret_ and no publishable", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(input), init });
        return new Response("[]", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
    vi.stubEnv("SUPABASE_URL", "https://example.supabase.co");
    vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_test_key");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "");
    vi.stubEnv("SUPABASE_ANON_KEY", "");
    vi.stubEnv("SUPABASE_KEY", "");

    await supabaseFetch("employees?select=id&limit=1", { method: "PATCH", body: "{}" });

    expect(calls).toHaveLength(1);
    const headers = new Headers(calls[0].init?.headers);
    expect(headers.get("apikey")).toBe("sb_secret_test_key");
    expect(headers.get("User-Agent")).toBe("curl/8.5.0");
    expect(headers.get("Authorization")).toBeNull();
  });
});
