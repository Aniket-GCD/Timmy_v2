export type LiveSessionStatus = "active" | "closed" | "canceled" | "overdue";

/** Live timer row — not submitted hours. */
export type CurrentlyWorking = {
  id: string;
  staff_name: string;
  office: string;
  client: string;
  job_code: string | null;
  notes: string | null;
  task: string | null;
  started_at: string;
  planned_end_at: string | null;
  status: LiveSessionStatus;
  local_session_id: string | null;
  updated_at: string | null;
};
