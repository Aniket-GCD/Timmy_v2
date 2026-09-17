import { NextResponse } from "next/server";
import { requireDashboardUser } from "@/lib/auth/session";
import {
  parseQboOffice,
  qboAuthorizeUrl,
  qboClientId,
  qboClientSecret,
  qboRedirectUri,
} from "@/lib/qbo-oauth";

/**
 * Admin-only: redirect to Intuit authorize for one office.
 * GET /api/qbo/start?office=GCD|MH
 */
export async function GET(request: Request) {
  const auth = await requireDashboardUser();
  if (!auth.ok) {
    return NextResponse.json({ error: auth.error }, { status: auth.status });
  }
  if (!auth.user.is_admin) {
    return NextResponse.json({ error: "Admin only." }, { status: 403 });
  }

  const { searchParams, origin } = new URL(request.url);
  const office = parseQboOffice(searchParams.get("office"));
  if (!office) {
    return NextResponse.json(
      { error: "Query office=GCD or office=MH is required." },
      { status: 400 },
    );
  }

  const clientId = qboClientId();
  const clientSecret = qboClientSecret();
  if (!clientId || !clientSecret) {
    return NextResponse.json(
      {
        error:
          "Set QBO_CLIENT_ID and QBO_CLIENT_SECRET on Vercel (server env), then redeploy.",
      },
      { status: 500 },
    );
  }

  const redirectUri = qboRedirectUri(origin);
  const url = qboAuthorizeUrl({ clientId, redirectUri, office });
  return NextResponse.redirect(url);
}
