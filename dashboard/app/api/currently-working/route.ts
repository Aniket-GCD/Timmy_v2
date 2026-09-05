import { NextRequest, NextResponse } from "next/server";
import { requireDashboardUser, resolveStaffScope } from "@/lib/auth/session";
import { currentlyWorkingTable, supabaseFetch } from "@/lib/supabase-server";
import type { CurrentlyWorking, LiveSessionStatus } from "@/lib/types/currently-working";

function asStatus(value: unknown): LiveSessionStatus {
  if (value === "closed" || value === "canceled" || value === "overdue") return value;
  return "active";
}

export async function GET(req: NextRequest) {
  try {
    const auth = await requireDashboardUser();
    if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });

    const staffParam = req.nextUrl.searchParams.get("staff")?.trim() ?? "";
    const scope = resolveStaffScope(auth.user, staffParam);
    if (scope.error) return NextResponse.json({ error: scope.error }, { status: 403 });

    // Header shows one person: explicit staff, else signed-in user (even for admin All staff).
    const liveStaff = scope.staffFilter ?? auth.user.staff_name;

    const table = currentlyWorkingTable();
    const rows = await supabaseFetch<Array<Record<string, unknown>>>(
      `${table}?status=eq.active&staff_name=eq.${encodeURIComponent(liveStaff)}&order=started_at&limit=1`,
    );
    const sessions: CurrentlyWorking[] = rows.map((r) => ({
      id: String(r.id ?? ""),
      staff_name: String(r.staff_name ?? ""),
      office: String(r.office ?? "GCD"),
      client: String(r.client ?? ""),
      job_code: r.job_code == null ? null : String(r.job_code),
      notes: r.notes == null ? null : String(r.notes),
      task: r.task == null ? null : String(r.task),
      started_at: String(r.started_at ?? ""),
      planned_end_at: r.planned_end_at == null ? null : String(r.planned_end_at),
      status: asStatus(r.status),
      local_session_id: r.local_session_id == null ? null : String(r.local_session_id),
      updated_at: r.updated_at == null ? null : String(r.updated_at),
    }));
    return NextResponse.json(sessions);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
