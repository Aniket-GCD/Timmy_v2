import { NextRequest, NextResponse } from "next/server";
import { requireDashboardUser } from "@/lib/auth/session";
import { normalizeSupabaseRow, toSupabasePayload } from "@/lib/normalize-entry";
import { isEditable } from "@/lib/pay-period";
import {
  entriesTable,
  fetchClientsFromSupabase,
  fetchJobCodesFromSupabase,
  supabaseFetch,
} from "@/lib/supabase-server";
import { validateEntryWrite } from "@/lib/validate-entry";
import type { EntryWritePayload } from "@/lib/types/time-entry";

type RouteParams = { params: Promise<{ id: string }> };

export async function PATCH(req: NextRequest, { params }: RouteParams) {
  try {
    const auth = await requireDashboardUser();
    if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });

    const { id } = await params;
    const body = (await req.json()) as EntryWritePayload & { staff_name?: string };

    const table = entriesTable();
    const existing = await supabaseFetch<Array<Record<string, unknown>>>(
      `${table}?id=eq.${id}&select=*`,
    );
    if (!existing.length) {
      return NextResponse.json({ error: "Entry not found" }, { status: 404 });
    }
    const current = normalizeSupabaseRow(existing[0]);

    if (!auth.user.is_admin && current.staff_name !== auth.user.staff_name) {
      return NextResponse.json({ error: "Forbidden" }, { status: 403 });
    }

    // Dashboard admins (employees.is_admin) bypass the pay-period window; others use Timmy parity.
    if (!auth.user.is_admin && !isEditable(current.entry_date, auth.user.staff_name)) {
      return NextResponse.json({ error: "Entry is outside the edit window" }, { status: 403 });
    }

    const targetStaff =
      auth.user.is_admin && body.staff_name?.trim()
        ? body.staff_name.trim()
        : current.staff_name;

    const clients = await fetchClientsFromSupabase();
    const jobCodes = await fetchJobCodesFromSupabase();
    const result = validateEntryWrite(body, { clients, jobCodes }, targetStaff);
    if (!result.ok) return NextResponse.json({ error: result.error }, { status: 400 });

    const entry = {
      id: Number(id),
      staff_name: targetStaff,
      office: current.office || auth.user.office,
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
