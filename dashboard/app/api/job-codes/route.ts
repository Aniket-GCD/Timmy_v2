import { NextResponse } from "next/server";
import { requireDashboardUser } from "@/lib/auth/session";
import { fetchJobCodesFromSupabase } from "@/lib/supabase-server";
import { MOCK_JOB_CODES } from "@/lib/mock-reference";

export async function GET() {
  try {
    const auth = await requireDashboardUser();
    if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });
    const source = process.env.NEXT_PUBLIC_DASHBOARD_DATA_SOURCE ?? "mock";
    if (source === "mock") return NextResponse.json(MOCK_JOB_CODES);
    return NextResponse.json(await fetchJobCodesFromSupabase());
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
