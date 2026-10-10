import { NextResponse } from "next/server";
import { mapEmployeeRow, requireDashboardUser } from "@/lib/auth/session";
import { employeesTable, supabaseFetch } from "@/lib/supabase-server";
import type { Employee } from "@/lib/types/employee";

export async function GET() {
  try {
    const auth = await requireDashboardUser();
    if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });

    const table = employeesTable();
    const rows = await supabaseFetch<Array<Record<string, unknown>>>(
      `${table}?select=id,first_name,last_name,staff_name,office,active,email,is_admin,can_view_time_by_job&active=eq.true&order=staff_name`,
    );
    let employees: Employee[] = rows.map(mapEmployeeRow);
    if (!auth.user.is_admin && !auth.user.can_view_time_by_job) {
      employees = employees.filter((e) => e.staff_name === auth.user.staff_name);
    }
    return NextResponse.json(employees);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
