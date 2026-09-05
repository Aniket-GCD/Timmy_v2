import { NextResponse } from "next/server";
import { requireDashboardUser } from "@/lib/auth/session";

export async function GET() {
  const auth = await requireDashboardUser();
  if (!auth.ok) {
    return NextResponse.json({ error: auth.error }, { status: auth.status });
  }
  return NextResponse.json(auth.user);
}
