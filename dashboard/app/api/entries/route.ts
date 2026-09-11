import { NextRequest, NextResponse } from "next/server";
import { requireDashboardUser, resolveStaffScope } from "@/lib/auth/session";
import { normalizeSupabaseRow } from "@/lib/normalize-entry";
import { isWithinEditWindow } from "@/lib/pay-period";
import {
  entriesTable,
  fetchClientsFromSupabase,
  fetchJobCodesFromSupabase,
  supabaseFetch,
} from "@/lib/supabase-server";
import { validateEntryWrite } from "@/lib/validate-entry";
import type { EntryWritePayload } from "@/lib/types/time-entry";

export async function GET(req: NextRequest) {
  try {
    const auth = await requireDashboardUser();
    if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });

    const from = req.nextUrl.searchParams.get("from") ?? "";
    const to = req.nextUrl.searchParams.get("to") ?? "";
    const staffParam = req.nextUrl.searchParams.get("staff")?.trim() ?? "";
    const scope = resolveStaffScope(auth.user, staffParam);
    if (scope.error) return NextResponse.json({ error: scope.error }, { status: 403 });

    const table = entriesTable();
    const filters = [`entry_date=gte.${from}`, `entry_date=lte.${to}`, "order=entry_date,start_time"];
    if (scope.staffFilter) {
      filters.unshift(`staff_name=eq.${encodeURIComponent(scope.staffFilter)}`);
    }
    const rows = await supabaseFetch<Array<Record<string, unknown>>>(`${table}?${filters.join("&")}`);
    return NextResponse.json(rows.map(normalizeSupabaseRow));
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const auth = await requireDashboardUser();
    if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });

    const body = (await req.json()) as EntryWritePayload & { staff_name?: string };
    const targetStaff = auth.user.is_admin && body.staff_name?.trim()
      ? body.staff_name.trim()
      : auth.user.staff_name;
    if (!auth.user.is_admin && body.staff_name && body.staff_name.trim() !== auth.user.staff_name) {
      return NextResponse.json({ error: "Forbidden" }, { status: 403 });
    }

    if (!auth.user.is_admin && !isWithinEditWindow(body.entry_date)) {
      return NextResponse.json({ error: "Entry is outside the edit window" }, { status: 403 });
    }

    const clients = await fetchClientsFromSupabase();
    const jobCodes = await fetchJobCodesFromSupabase();
    const result = validateEntryWrite(body, { clients, jobCodes }, targetStaff, {
      skipPayPeriodWindow: auth.user.is_admin,
    });
    if (!result.ok) return NextResponse.json({ error: result.error }, { status: 400 });

    const table = entriesTable();
    const rows = await supabaseFetch<Array<Record<string, unknown>>>(table, {
      method: "POST",
      body: JSON.stringify({
        staff_name: targetStaff,
        office: auth.user.office,
        client: result.payload.client,
        job_code: result.payload.job_code,
        account: result.account,
        notes: result.payload.notes,
        task: result.payload.notes,
        entry_date: result.payload.entry_date,
        start_time: result.payload.start_time,
        end_time: result.payload.end_time,
        hours: result.payload.hours,
        billable: result.payload.billable,
        source_file: "timmy-dashboard",
      }),
      prefer: "return=representation",
    });
    return NextResponse.json(normalizeSupabaseRow(rows[0]));
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
