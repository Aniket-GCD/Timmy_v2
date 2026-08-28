import styles from "./StatusChip.module.css";
import type { EntryStatus } from "@/lib/mock-data";

const LABELS: Record<EntryStatus, string> = {
  submitted: "Submitted",
};

export function StatusChip({ status }: { status: EntryStatus }) {
  return <span className={styles.chip}>{LABELS[status]}</span>;
}
