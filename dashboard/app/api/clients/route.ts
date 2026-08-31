import { NextResponse } from "next/server";
import { fetchClientsFromSupabase } from "@/lib/supabase-server";
import { MOCK_CLIENTS } from "@/lib/mock-reference";

export async function GET() {
  try {
    const source = process.env.NEXT_PUBLIC_DASHBOARD_DATA_SOURCE ?? "mock";
    if (source === "mock") return NextResponse.json(MOCK_CLIENTS);
    return NextResponse.json(await fetchClientsFromSupabase());
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
