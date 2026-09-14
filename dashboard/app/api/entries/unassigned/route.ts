import { NextRequest, NextResponse } from "next/server";
import { requireDashboardUser } from "@/lib/auth/session";
import { normalizeSupabaseRow } from "@/lib/normalize-entry";
import { entriesTable, supabaseFetch } from "@/lib/supabase-server";

/** Admin: list Unassigned entries for remap UI. */
export async function GET(req: NextRequest) {
  try {
    const auth = await requireDashboardUser();
    if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });
    if (!auth.user.is_admin) {
      return NextResponse.json({ error: "Admins only." }, { status: 403 });
    }

    const office = (req.nextUrl.searchParams.get("office")?.trim() ?? "GCD").toUpperCase();
    const client = req.nextUrl.searchParams.get("client")?.trim() || "Unassigned";
    const notesContains = req.nextUrl.searchParams.get("notes_contains")?.trim() ?? "";

    if (office !== "GCD" && office !== "MH") {
      return NextResponse.json({ error: "office must be GCD or MH" }, { status: 400 });
    }

    const table = entriesTable();
    const filters = [
      `office=eq.${office}`,
      `client=eq.${encodeURIComponent(client)}`,
      "order=entry_date.desc",
      "limit=200",
    ];
    let rows = await supabaseFetch<Array<Record<string, unknown>>>(`${table}?${filters.join("&")}`);
    if (notesContains) {
      const needle = notesContains.toLowerCase();
      rows = rows.filter((r) => {
        const notes = String(r.notes ?? r.task ?? "").toLowerCase();
        return notes.includes(needle);
      });
    }
    return NextResponse.json(rows.map(normalizeSupabaseRow));
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
