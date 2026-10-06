import { NextRequest, NextResponse } from "next/server";
import { officeForStaffName, requireDashboardUser } from "@/lib/auth/session";
import { normalizeSupabaseRow, toSupabasePayload } from "@/lib/normalize-entry";
import { isHomeOfficeClient, resolveEntryOffice } from "@/lib/resolve-entry-office";
import { canDashboardMutateEntry, isWithinEditWindow } from "@/lib/pay-period";
import {
  entriesTable,
  fetchClientsFromSupabase,
  fetchJobCodesFromSupabase,
  requireRepresentationRow,
  supabaseFetch,
} from "@/lib/supabase-server";
import { ENTRY_ERRORS, validateEntryWrite } from "@/lib/validate-entry";
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
      return NextResponse.json({ error: ENTRY_ERRORS.notFound }, { status: 404 });
    }
    const current = normalizeSupabaseRow(existing[0]);

    if (!auth.user.is_admin && current.staff_name !== auth.user.staff_name) {
      return NextResponse.json({ error: ENTRY_ERRORS.ownOnly }, { status: 403 });
    }

    const newDate = (body.entry_date || current.entry_date).slice(0, 10);
    if (!auth.user.is_admin) {
      if (!isWithinEditWindow(current.entry_date) || !isWithinEditWindow(newDate)) {
        return NextResponse.json({ error: ENTRY_ERRORS.lockedDate }, { status: 403 });
      }
    }

    const targetStaff =
      auth.user.is_admin && body.staff_name?.trim()
        ? body.staff_name.trim()
        : current.staff_name;

    const clients = await fetchClientsFromSupabase();
    const jobCodes = await fetchJobCodesFromSupabase();
    const result = validateEntryWrite(body, { clients, jobCodes }, targetStaff, {
      skipPayPeriodWindow: auth.user.is_admin,
    });
    if (!result.ok) return NextResponse.json({ error: result.error }, { status: 400 });

    const labelOffice = (body.office || "").trim().toUpperCase();
    const actorOffice = auth.user.office === "MH" ? "MH" : "GCD";
    const hint = isHomeOfficeClient(result.payload.client)
      ? targetStaff === auth.user.staff_name
        ? actorOffice
        : await officeForStaffName(targetStaff, actorOffice)
      : labelOffice === "GCD" || labelOffice === "MH"
        ? labelOffice
        : current.office || actorOffice;
    const office = resolveEntryOffice(result.payload.client, clients, hint);
    const entry = {
      id: Number(id),
      staff_name: targetStaff,
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

export async function DELETE(_req: NextRequest, { params }: RouteParams) {
  try {
    const auth = await requireDashboardUser();
    if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });

    const { id } = await params;
    const table = entriesTable();
    const existing = await supabaseFetch<Array<Record<string, unknown>>>(
      `${table}?id=eq.${id}&select=*`,
    );
    if (!existing.length) {
      return NextResponse.json({ error: ENTRY_ERRORS.notFound }, { status: 404 });
    }
    const current = normalizeSupabaseRow(existing[0]);
    const allowed = canDashboardMutateEntry({
      entryDate: current.entry_date,
      actorIsAdmin: auth.user.is_admin,
      actorStaffName: auth.user.staff_name,
      entryStaffName: current.staff_name,
    });
    if (!allowed) {
      const own = current.staff_name === auth.user.staff_name;
      return NextResponse.json(
        { error: own ? ENTRY_ERRORS.lockedDate : ENTRY_ERRORS.ownOnly },
        { status: 403 },
      );
    }

    await supabaseFetch(`${table}?id=eq.${id}`, { method: "DELETE", prefer: "return=minimal" });
    return NextResponse.json({ ok: true });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
