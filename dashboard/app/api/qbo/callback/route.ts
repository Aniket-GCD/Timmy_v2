import { NextResponse } from "next/server";
import {
  exchangeAuthorizationCode,
  parseQboOffice,
  qboClientId,
  qboClientSecret,
  qboRedirectUri,
  upsertQboTokenRow,
} from "@/lib/qbo-oauth";

/**
 * Intuit OAuth redirect target (no login cookie required).
 * Register exactly: https://<dashboard-host>/api/qbo/callback
 */
export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const error = searchParams.get("error");
  if (error) {
    const desc = searchParams.get("error_description") ?? error;
    return htmlPage(400, "QuickBooks connect failed", desc);
  }

  const code = (searchParams.get("code") ?? "").trim();
  const realmId = (searchParams.get("realmId") ?? searchParams.get("realm_id") ?? "").trim();
  const office = parseQboOffice(searchParams.get("state"));

  if (!code || !realmId || !office) {
    return htmlPage(
      400,
      "Missing OAuth parameters",
      "Expected code, realmId, and state (GCD or MH). Start from /qbo-connect while signed in as admin.",
    );
  }

  const clientId = qboClientId();
  const clientSecret = qboClientSecret();
  if (!clientId || !clientSecret) {
    return htmlPage(
      500,
      "Server misconfigured",
      "QBO_CLIENT_ID / QBO_CLIENT_SECRET are not set on this deployment.",
    );
  }

  const redirectUri = qboRedirectUri(origin);

  try {
    const tokens = await exchangeAuthorizationCode({
      clientId,
      clientSecret,
      code,
      redirectUri,
    });
    await upsertQboTokenRow({
      office,
      realmId,
      refreshToken: tokens.refresh_token,
    });
  } catch (e) {
    return htmlPage(500, "Could not save QuickBooks tokens", String(e));
  }

  return htmlPage(
    200,
    `${office} connected`,
    `Saved realm ${realmId} into qbo_tokens. You can close this tab, then run the client sync (or wait for the GitHub Action).`,
  );
}

function htmlPage(status: number, title: string, body: string) {
  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${escapeHtml(title)}</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 36rem; margin: 3rem auto; padding: 0 1rem; line-height: 1.5; }
    h1 { font-size: 1.35rem; }
    p { color: #333; }
    a { color: #0b6; }
  </style>
</head>
<body>
  <h1>${escapeHtml(title)}</h1>
  <p>${escapeHtml(body)}</p>
  <p><a href="/qbo-connect">Back to QBO connect</a> · <a href="/">Dashboard</a></p>
</body>
</html>`;
  return new NextResponse(html, {
    status,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
