import { NextRequest, NextResponse } from "next/server";
import { requireDashboardUser, resolveStaffScope } from "@/lib/auth/session";
import { normalizeSupabaseRow } from "@/lib/normalize-entry";
import { isWithinEditWindow } from "@/lib/pay-period";
import {
  entriesTable,
  fetchClientsFromSupabase,
  fetchJobCodesFromSupabase,
  requireRepresentationRow,
  supabaseFetch,
} from "@/lib/supabase-server";
import { ENTRY_ERRORS, validateEntryWrite } from "@/lib/validate-entry";
import { resolveEntryOffice } from "@/lib/resolve-entry-office";
import type { EntryWritePayload } from "@/lib/types/time-entry";

export async function GET(req: NextRequest) {
  try {
    const auth = await requireDashboardUser();
    if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });

    const from = req.nextUrl.searchParams.get("from") ?? "";
    const to = req.nextUrl.searchParams.get("to") ?? "";
    const staffParam = req.nextUrl.searchParams.get("staff")?.trim() ?? "";
    const officeParam = (req.nextUrl.searchParams.get("office")?.trim() ?? "").toUpperCase();
    const scope = resolveStaffScope(auth.user, staffParam);
    if (scope.error) return NextResponse.json({ error: scope.error }, { status: 403 });

    const table = entriesTable();
    const select =
      "id,staff_name,office,client,job_code,account,notes,task,entry_date,start_time,end_time,hours,billable,source_file,status";
    const filters = [
      `select=${select}`,
      `entry_date=gte.${from}`,
      `entry_date=lte.${to}`,
      "order=entry_date,start_time",
    ];
    if (scope.staffFilter) {
      filters.unshift(`staff_name=eq.${encodeURIComponent(scope.staffFilter)}`);
    }
    if (officeParam === "GCD" || officeParam === "MH") {
      filters.unshift(`office=eq.${officeParam}`);
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
      return NextResponse.json({ error: ENTRY_ERRORS.ownOnly }, { status: 403 });
    }

    if (!auth.user.is_admin && !isWithinEditWindow(body.entry_date)) {
      return NextResponse.json({ error: ENTRY_ERRORS.lockedDate }, { status: 403 });
    }

    const clients = await fetchClientsFromSupabase();
    const jobCodes = await fetchJobCodesFromSupabase();
    const result = validateEntryWrite(body, { clients, jobCodes }, targetStaff, {
      skipPayPeriodWindow: auth.user.is_admin,
    });
    if (!result.ok) return NextResponse.json({ error: result.error }, { status: 400 });

    const office = resolveEntryOffice(
      result.payload.client,
      clients,
      body.office || auth.user.office,
    );
    const table = entriesTable();
    const rows = await supabaseFetch<Array<Record<string, unknown>>>(table, {
      method: "POST",
      body: JSON.stringify({
        staff_name: targetStaff,
        office,
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
    try {
      return NextResponse.json(normalizeSupabaseRow(requireRepresentationRow(rows)));
    } catch (e) {
      if (e instanceof Error && e.message === "EMPTY_WRITE_REPRESENTATION") {
        return NextResponse.json({ error: ENTRY_ERRORS.saveFailed }, { status: 502 });
      }
      throw e;
    }
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
