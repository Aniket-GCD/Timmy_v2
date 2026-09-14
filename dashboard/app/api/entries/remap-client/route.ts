import { NextRequest, NextResponse } from "next/server";
import { requireDashboardUser } from "@/lib/auth/session";
import { resolveEntryOffice } from "@/lib/resolve-entry-office";
import {
  entriesTable,
  fetchClientsFromSupabase,
  supabaseFetch,
} from "@/lib/supabase-server";

type Body = {
  office?: string;
  to_client?: string;
  entry_ids?: number[];
  match_notes_contains?: string;
};

/** Admin: remap Unassigned (or other) entries to a real client name. */
export async function POST(req: NextRequest) {
  try {
    const auth = await requireDashboardUser();
    if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });
    if (!auth.user.is_admin) {
      return NextResponse.json({ error: "Admins only." }, { status: 403 });
    }

    const body = (await req.json()) as Body;
    const office = (body.office ?? "GCD").trim().toUpperCase();
    const toClient = (body.to_client ?? "").trim();
    if (office !== "GCD" && office !== "MH") {
      return NextResponse.json({ error: "office must be GCD or MH" }, { status: 400 });
    }
    if (!toClient || toClient.toLowerCase() === "unassigned") {
      return NextResponse.json({ error: "Pick a real client (not Unassigned)." }, { status: 400 });
    }

    const clients = await fetchClientsFromSupabase();
    const allowed = clients.some(
      (c) =>
        c.name.trim().toLowerCase() === toClient.toLowerCase() &&
        c.office.toUpperCase() === office,
    );
    if (!allowed) {
      return NextResponse.json(
        { error: `Client "${toClient}" is not on the ${office} roster.` },
        { status: 400 },
      );
    }

    const table = entriesTable();
    let ids = (body.entry_ids ?? []).map(Number).filter((n) => Number.isFinite(n));
    if (!ids.length && body.match_notes_contains?.trim()) {
      const needle = body.match_notes_contains.trim().toLowerCase();
      const rows = await supabaseFetch<Array<Record<string, unknown>>>(
        `${table}?office=eq.${office}&client=eq.${encodeURIComponent("Unassigned")}&select=id,notes,task&limit=500`,
      );
      ids = rows
        .filter((r) => String(r.notes ?? r.task ?? "").toLowerCase().includes(needle))
        .map((r) => Number(r.id))
        .filter((n) => Number.isFinite(n));
    }
    if (!ids.length) {
      return NextResponse.json({ error: "No entries selected." }, { status: 400 });
    }

    const entryOffice = resolveEntryOffice(toClient, clients, office);
    let updated = 0;
    for (const id of ids) {
      await supabaseFetch(`${table}?id=eq.${id}&client=eq.${encodeURIComponent("Unassigned")}`, {
        method: "PATCH",
        body: JSON.stringify({ client: toClient, office: entryOffice }),
        prefer: "return=minimal",
      });
      updated += 1;
    }
    return NextResponse.json({ updated, office: entryOffice, to_client: toClient });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
