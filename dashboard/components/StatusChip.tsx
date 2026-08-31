import styles from "./StatusChip.module.css";

export type StatusKind = "submitted" | "draft" | "locked" | "saving" | "error";

const LABELS: Record<StatusKind, string> = {
  submitted: "Submitted",
  draft: "Draft",
  locked: "Locked",
  saving: "Saving…",
  error: "Error",
};

export function StatusChip({ status }: { status: StatusKind }) {
  return <span className={`${styles.chip} ${styles[status] ?? ""}`}>{LABELS[status]}</span>;
}
