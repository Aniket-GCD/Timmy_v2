"use client";

import { useMemo, useState } from "react";
import { formatHours, groupByClient } from "@/lib/aggregations";
import { formatDisplayDate } from "@/lib/dates";
import type { MockEntry } from "@/lib/mock-data";
import { StatusChip } from "./StatusChip";
import styles from "./DayEntriesTable.module.css";

type Props = {
  dateISO: string;
  entries: MockEntry[];
};

export function DayEntriesTable({ dateISO, entries }: Props) {
  const groups = useMemo(() => groupByClient(entries), [entries]);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [showTimes, setShowTimes] = useState(true);

  const dailyTotal = useMemo(
    () => formatHours(entries.reduce((s, e) => s + e.hours, 0)),
    [entries],
  );

  if (entries.length === 0) {
    return (
      <div className="empty">No submitted hours for this day.</div>
    );
  }

  const toggleClient = (client: string) => {
    setCollapsed((prev) => ({ ...prev, [client]: !prev[client] }));
  };

  return (
    <div className={styles.wrap}>
      <div className={styles.toolbar}>
        <div>
          <h2 className="section-title" style={{ marginBottom: 0 }}>
            Day detail
          </h2>
          <p className="muted" style={{ margin: "0.25rem 0 0", fontSize: "0.9rem" }}>
            {formatDisplayDate(dateISO)}
          </p>
        </div>
        <button
          type="button"
          className={styles.toggle}
          onClick={() => setShowTimes((v) => !v)}
          aria-pressed={showTimes}
        >
          {showTimes ? "Hide times" : "Show times"}
        </button>
      </div>

      <div className={styles.tableScroll}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.clientCol}>Client</th>
              <th>Job</th>
              <th>Description</th>
              {showTimes && (
                <>
                  <th className={styles.num}>Start</th>
                  <th className={styles.num}>End</th>
                  <th className={styles.num}>Duration</th>
                </>
              )}
              {!showTimes && <th className={styles.num}>Hours</th>}
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => {
              const isCollapsed = Boolean(collapsed[group.client]);
              return (
                <ClientBlock
                  key={group.client}
                  client={group.client}
                  entries={group.entries}
                  subtotal={group.subtotal}
                  collapsed={isCollapsed}
                  showTimes={showTimes}
                  onToggle={() => toggleClient(group.client)}
                />
              );
            })}
          </tbody>
          <tfoot>
            <tr className={styles.footer}>
              <td colSpan={showTimes ? 5 : 3}>
                <strong>Daily total</strong>
              </td>
              <td className={styles.num}>
                <strong>{dailyTotal}h</strong>
              </td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

function ClientBlock({
  client,
  entries,
  subtotal,
  collapsed,
  showTimes,
  onToggle,
}: {
  client: string;
  entries: MockEntry[];
  subtotal: number;
  collapsed: boolean;
  showTimes: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr className={styles.groupHeader}>
        <td colSpan={showTimes ? 7 : 5}>
          <button type="button" className={styles.groupBtn} onClick={onToggle}>
            <span className={styles.chevron} aria-hidden>
              {collapsed ? "▸" : "▾"}
            </span>
            <span className={styles.groupName}>{client}</span>
            <span className={styles.groupMeta}>
              {entries.length} {entries.length === 1 ? "entry" : "entries"} ·{" "}
              {formatHours(subtotal)}h
            </span>
          </button>
        </td>
      </tr>
      {!collapsed &&
        entries.map((e) => (
          <tr key={e.id} className={styles.row}>
            <td className={styles.indent} />
            <td>{e.job_code}</td>
            <td>{e.notes}</td>
            {showTimes && (
              <>
                <td className={styles.num}>{e.start_time ?? "—"}</td>
                <td className={styles.num}>{e.end_time ?? "—"}</td>
                <td className={styles.num}>{formatHours(e.hours)}h</td>
              </>
            )}
            {!showTimes && <td className={styles.num}>{formatHours(e.hours)}h</td>}
            <td>
              <StatusChip status={e.status} />
            </td>
          </tr>
        ))}
      {!collapsed && (
        <tr className={styles.subtotal}>
          <td colSpan={showTimes ? 5 : 3} className={styles.indent}>
            Subtotal — {client}
          </td>
          <td className={styles.num}>{formatHours(subtotal)}h</td>
          <td />
        </tr>
      )}
    </>
  );
}
