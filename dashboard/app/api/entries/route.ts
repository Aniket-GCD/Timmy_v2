import { NextRequest, NextResponse } from "next/server";
import { normalizeSupabaseRow } from "@/lib/normalize-entry";
import {
  entriesTable,
  fetchClientsFromSupabase,
  fetchJobCodesFromSupabase,
  getDashboardStaff,
  supabaseFetch,
} from "@/lib/supabase-server";
import { validateEntryWrite } from "@/lib/validate-entry";
import type { EntryWritePayload } from "@/lib/types/time-entry";

export async function GET(req: NextRequest) {
  try {
    const { staffName } = getDashboardStaff();
    const from = req.nextUrl.searchParams.get("from") ?? "";
    const to = req.nextUrl.searchParams.get("to") ?? "";
    const staff = req.nextUrl.searchParams.get("staff") ?? staffName;
    const table = entriesTable();
    const rows = await supabaseFetch<Array<Record<string, unknown>>>(
      `${table}?staff_name=eq.${encodeURIComponent(staff)}&entry_date=gte.${from}&entry_date=lte.${to}&order=entry_date,start_time`,
    );
    return NextResponse.json(rows.map(normalizeSupabaseRow));
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const { staffName, office } = getDashboardStaff();
    const body = (await req.json()) as EntryWritePayload;
    const clients = await fetchClientsFromSupabase();
    const jobCodes = await fetchJobCodesFromSupabase();
    const result = validateEntryWrite(body, { clients, jobCodes }, staffName);
    if (!result.ok) return NextResponse.json({ error: result.error }, { status: 400 });

    const table = entriesTable();
    const rows = await supabaseFetch<Array<Record<string, unknown>>>(table, {
      method: "POST",
      body: JSON.stringify({
        staff_name: staffName,
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
    return NextResponse.json(normalizeSupabaseRow(rows[0]));
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
