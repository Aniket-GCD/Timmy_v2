import { describe, expect, it } from "vitest";
import {
  parseQboOffice,
  qboAuthorizeUrl,
  qboRedirectUri,
} from "@/lib/qbo-oauth";

describe("qbo-oauth helpers", () => {
  it("parses office", () => {
    expect(parseQboOffice("gcd")).toBe("GCD");
    expect(parseQboOffice("MH")).toBe("MH");
    expect(parseQboOffice("x")).toBeNull();
  });

  it("builds redirect from env or origin", () => {
    const prev = process.env.QBO_REDIRECT_URI;
    delete process.env.QBO_REDIRECT_URI;
    expect(qboRedirectUri("https://dashboard-gcd1.vercel.app")).toBe(
      "https://dashboard-gcd1.vercel.app/api/qbo/callback",
    );
    process.env.QBO_REDIRECT_URI = "https://dashboard-gcd1.vercel.app/api/qbo/callback/";
    expect(qboRedirectUri("https://ignored.example")).toBe(
      "https://dashboard-gcd1.vercel.app/api/qbo/callback",
    );
    if (prev === undefined) delete process.env.QBO_REDIRECT_URI;
    else process.env.QBO_REDIRECT_URI = prev;
  });

  it("includes state office in authorize URL", () => {
    const url = qboAuthorizeUrl({
      clientId: "cid",
      redirectUri: "https://dashboard-gcd1.vercel.app/api/qbo/callback",
      office: "GCD",
    });
    expect(url).toContain("appcenter.intuit.com/connect/oauth2");
    expect(url).toContain("state=GCD");
    expect(url).toContain(encodeURIComponent("https://dashboard-gcd1.vercel.app/api/qbo/callback"));
  });
});
