import { formatHoursHM, formatPercent } from "@/lib/hours-format";
import type { Metrics } from "@/lib/aggregations";
import styles from "./MetricCards.module.css";

type Props = { metrics: Metrics };

export function MetricCards({ metrics }: Props) {
  const cards = [
    { label: "Total hours", value: formatHoursHM(metrics.totalHours) },
    { label: "Billable", value: formatHoursHM(metrics.billableHours) },
    {
      label: "Admin",
      value: `${formatHoursHM(metrics.adminHours)} (${formatPercent(metrics.adminHours, metrics.totalHours)})`,
    },
    { label: "Clients", value: String(metrics.clientCount) },
  ];

  return (
    <div className={styles.grid}>
      {cards.map((card) => (
        <div key={card.label} className={styles.card}>
          <div className={styles.label}>{card.label}</div>
          <div className={styles.value}>{card.value}</div>
        </div>
      ))}
    </div>
  );
}
