export type Employee = {
  id: string;
  first_name: string;
  last_name: string;
  staff_name: string;
  office: string;
  active: boolean;
  email: string | null;
  is_admin: boolean;
};

export type DashboardUser = {
  email: string;
  staff_name: string;
  office: string;
  is_admin: boolean;
  employee_id: string;
};
