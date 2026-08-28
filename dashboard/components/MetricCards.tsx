import { formatHours, type Metrics } from "@/lib/aggregations";
import styles from "./MetricCards.module.css";

type Props = {
  metrics: Metrics;
};

const CARDS: { key: keyof Metrics; label: string; suffix?: string }[] = [
  { key: "totalHours", label: "Total hours", suffix: "h" },
  { key: "billableHours", label: "Billable", suffix: "h" },
  { key: "nonBillableHours", label: "Non-billable", suffix: "h" },
  { key: "entryCount", label: "Entries" },
];

export function MetricCards({ metrics }: Props) {
  return (
    <div className={styles.grid}>
      {CARDS.map((card) => {
        const raw = metrics[card.key];
        const value =
          card.key === "entryCount" ? String(raw) : `${formatHours(raw)}${card.suffix ?? ""}`;
        return (
          <div key={card.key} className={styles.card}>
            <div className={styles.label}>{card.label}</div>
            <div className={styles.value}>{value}</div>
          </div>
        );
      })}
    </div>
  );
}
