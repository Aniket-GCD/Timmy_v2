import { NextRequest, NextResponse } from "next/server";
import { isSupabaseDataSource, requireDashboardUser } from "@/lib/auth/session";
import { mockProvider } from "@/lib/data/entries-provider";
import { normalizeSupabaseRow } from "@/lib/normalize-entry";
import { entriesTable, supabaseFetch } from "@/lib/supabase-server";

const NO_ACCESS = "You don't have access to Time by Job.";

export async function GET(req: NextRequest) {
  try {
    const auth = await requireDashboardUser();
    if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });
    if (!auth.user.can_view_time_by_job) {
      return NextResponse.json({ error: NO_ACCESS }, { status: 403 });
    }

    const from = req.nextUrl.searchParams.get("from") ?? "";
    const to = req.nextUrl.searchParams.get("to") ?? "";

    if (!isSupabaseDataSource()) {
      const rows = await mockProvider.fetchEntries({ dateFrom: from, dateTo: to });
      return NextResponse.json(rows);
    }

    const table = entriesTable();
    const filters = [`entry_date=gte.${from}`, `entry_date=lte.${to}`, "order=entry_date,start_time,id"];
    const pageSize = 1000;
    const all: Array<Record<string, unknown>> = [];
    let offset = 0;
    for (;;) {
      const rows = await supabaseFetch<Array<Record<string, unknown>>>(
        `${table}?${filters.join("&")}&limit=${pageSize}&offset=${offset}`,
      );
      if (!Array.isArray(rows) || rows.length === 0) break;
      all.push(...rows);
      if (rows.length < pageSize) break;
      offset += pageSize;
    }
    return NextResponse.json(all.map(normalizeSupabaseRow));
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
