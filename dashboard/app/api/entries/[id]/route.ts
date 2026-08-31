import { NextRequest, NextResponse } from "next/server";
import { normalizeSupabaseRow, toSupabasePayload } from "@/lib/normalize-entry";
import {
  entriesTable,
  fetchClientsFromSupabase,
  fetchJobCodesFromSupabase,
  getDashboardStaff,
  supabaseFetch,
} from "@/lib/supabase-server";
import { validateEntryWrite } from "@/lib/validate-entry";
import type { EntryWritePayload } from "@/lib/types/time-entry";

type RouteParams = { params: Promise<{ id: string }> };

export async function PATCH(req: NextRequest, { params }: RouteParams) {
  try {
    const { id } = await params;
    const { staffName, office } = getDashboardStaff();
    const body = (await req.json()) as EntryWritePayload;
    const clients = await fetchClientsFromSupabase();
    const jobCodes = await fetchJobCodesFromSupabase();
    const result = validateEntryWrite(body, { clients, jobCodes }, staffName);
    if (!result.ok) return NextResponse.json({ error: result.error }, { status: 400 });

    const table = entriesTable();
    const entry = {
      id: Number(id),
      staff_name: staffName,
      office,
      ...result.payload,
      account: result.account,
      source_file: "timmy-dashboard",
    };
    const rows = await supabaseFetch<Array<Record<string, unknown>>>(
      `${table}?id=eq.${id}`,
      {
        method: "PATCH",
        body: JSON.stringify(toSupabasePayload(entry, result.account)),
        prefer: "return=representation",
      },
    );
    return NextResponse.json(normalizeSupabaseRow(rows[0]));
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
