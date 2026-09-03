import { NextResponse } from "next/server";
import { employeesTable, supabaseFetch } from "@/lib/supabase-server";
import type { Employee } from "@/lib/types/employee";

export async function GET() {
  try {
    const table = employeesTable();
    const rows = await supabaseFetch<Array<Record<string, unknown>>>(
      `${table}?select=id,first_name,last_name,staff_name,office,active&active=eq.true&order=staff_name`,
    );
    const employees: Employee[] = rows.map((r) => ({
      id: String(r.id ?? ""),
      first_name: String(r.first_name ?? ""),
      last_name: String(r.last_name ?? ""),
      staff_name: String(r.staff_name ?? ""),
      office: String(r.office ?? "GCD"),
      active: r.active !== false,
    }));
    return NextResponse.json(employees);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
