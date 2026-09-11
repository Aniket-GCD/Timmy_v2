import { employeesTable, supabaseFetch } from "@/lib/supabase-server";
import type { DashboardUser, Employee } from "@/lib/types/employee";
import { createClient } from "@/lib/auth/supabase-server";

export function isSupabaseDataSource(): boolean {
  return (process.env.NEXT_PUBLIC_DASHBOARD_DATA_SOURCE ?? "mock") === "supabase";
}

export const MOCK_DASHBOARD_USER: DashboardUser = {
  email: "mock-admin@gcd.local",
  staff_name: "Aniket",
  office: "GCD",
  is_admin: true,
  employee_id: "e-aniket",
};

export function mapEmployeeRow(r: Record<string, unknown>): Employee {
  return {
    id: String(r.id ?? ""),
    first_name: String(r.first_name ?? ""),
    last_name: String(r.last_name ?? ""),
    staff_name: String(r.staff_name ?? ""),
    office: String(r.office ?? "GCD"),
    active: r.active !== false,
    email: r.email == null || r.email === "" ? null : String(r.email),
    is_admin: r.is_admin === true,
  };
}

/** Pure helper for tests — match roster by lowercased email. */
export function findEmployeeByEmail(
  employees: Employee[],
  email: string,
): Employee | null {
  const needle = email.trim().toLowerCase();
  if (!needle) return null;
  return (
    employees.find(
      (e) => e.active && e.email && e.email.trim().toLowerCase() === needle,
    ) ?? null
  );
}

export async function lookupEmployeeByEmail(email: string): Promise<Employee | null> {
  const table = employeesTable();
  const rows = await supabaseFetch<Array<Record<string, unknown>>>(
    `${table}?select=id,first_name,last_name,staff_name,office,active,email,is_admin&active=eq.true`,
  );
  return findEmployeeByEmail(rows.map(mapEmployeeRow), email);
}

export type AuthResult =
  | { ok: true; user: DashboardUser }
  | { ok: false; status: number; error: string };

export async function requireDashboardUser(): Promise<AuthResult> {
  if (!isSupabaseDataSource()) {
    return { ok: true, user: MOCK_DASHBOARD_USER };
  }

  try {
    const supabase = await createClient();
    const { data, error } = await supabase.auth.getUser();
    if (error || !data.user?.email) {
      return { ok: false, status: 401, error: "Please sign in to continue." };
    }
    const employee = await lookupEmployeeByEmail(data.user.email);
    if (!employee) {
      return {
        ok: false,
        status: 403,
        error: "This email is not on the Timmy employee list. Ask an admin to add you.",
      };
    }
    return {
      ok: true,
      user: {
        email: data.user.email,
        staff_name: employee.staff_name,
        office: employee.office,
        is_admin: employee.is_admin,
        employee_id: employee.id,
      },
    };
  } catch (e) {
    return { ok: false, status: 500, error: String(e) };
  }
}

/** Resolve which staff_name the request may view/edit. */
export function resolveStaffScope(
  user: DashboardUser,
  requestedStaff: string | null | undefined,
): { staffFilter: string | null; error?: string } {
  const requested = (requestedStaff ?? "").trim();
  if (!user.is_admin) {
    if (requested && requested !== user.staff_name) {
      return { staffFilter: user.staff_name, error: "You can only view your own time entries." };
    }
    return { staffFilter: user.staff_name };
  }
  return { staffFilter: requested || null };
}
