/** Server-only QuickBooks Online OAuth helpers for dashboard admin connect. */

export type QboOffice = "GCD" | "MH";

export function parseQboOffice(raw: string | null | undefined): QboOffice | null {
  const v = (raw ?? "").trim().toUpperCase();
  if (v === "GCD" || v === "MH") return v;
  return null;
}

export function qboClientId(): string {
  return (process.env.QBO_CLIENT_ID ?? "").trim();
}

export function qboClientSecret(): string {
  return (process.env.QBO_CLIENT_SECRET ?? "").trim();
}

/** Must match Intuit app Redirect URI exactly (Production HTTPS on Vercel). */
export function qboRedirectUri(origin: string): string {
  const fromEnv = (process.env.QBO_REDIRECT_URI ?? "").trim();
  if (fromEnv) return fromEnv.replace(/\/$/, "");
  return `${origin.replace(/\/$/, "")}/api/qbo/callback`;
}

export function qboAuthorizeUrl(params: {
  clientId: string;
  redirectUri: string;
  office: QboOffice;
}): string {
  const q = new URLSearchParams({
    client_id: params.clientId,
    redirect_uri: params.redirectUri,
    response_type: "code",
    scope: "com.intuit.quickbooks.accounting",
    state: params.office,
  });
  return `https://appcenter.intuit.com/connect/oauth2?${q.toString()}`;
}

export async function exchangeAuthorizationCode(params: {
  clientId: string;
  clientSecret: string;
  code: string;
  redirectUri: string;
}): Promise<{ refresh_token: string; access_token: string }> {
  const basic = Buffer.from(`${params.clientId}:${params.clientSecret}`).toString("base64");
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    code: params.code,
    redirect_uri: params.redirectUri,
  });
  const res = await fetch("https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer", {
    method: "POST",
    headers: {
      Authorization: `Basic ${basic}`,
      "Content-Type": "application/x-www-form-urlencoded",
      Accept: "application/json",
      "User-Agent": "curl/8.5.0",
    },
    body: body.toString(),
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`Intuit token exchange failed HTTP ${res.status}: ${text.slice(0, 240)}`);
  }
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(text) as Record<string, unknown>;
  } catch {
    throw new Error("Intuit token exchange returned non-JSON");
  }
  const access = String(payload.access_token ?? "").trim();
  const refresh = String(payload.refresh_token ?? "").trim();
  if (!access || !refresh) {
    throw new Error("Intuit token exchange missing access_token or refresh_token");
  }
  return { access_token: access, refresh_token: refresh };
}

export async function upsertQboTokenRow(params: {
  office: QboOffice;
  realmId: string;
  refreshToken: string;
}): Promise<void> {
  const { supabaseFetch } = await import("@/lib/supabase-server");
  await supabaseFetch("qbo_tokens", {
    method: "POST",
    prefer: "resolution=merge-duplicates,return=minimal",
    body: JSON.stringify({
      office: params.office,
      realm_id: params.realmId,
      refresh_token: params.refreshToken,
      updated_at: new Date().toISOString(),
    }),
  });
}
