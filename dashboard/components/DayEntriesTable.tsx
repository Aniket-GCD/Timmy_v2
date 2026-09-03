"use client";

import { useMemo, useState } from "react";
import { groupByStaff } from "@/lib/aggregations";
import { formatDisplayDate } from "@/lib/dates";
import { formatHoursHM } from "@/lib/hours-format";
import type { TimeEntry } from "@/lib/types/time-entry";
import { StatusChip } from "./StatusChip";
import styles from "./DayEntriesTable.module.css";

type Props = {
  dateISO: string;
  entries: TimeEntry[];
};

function displayTime(value: string | null): string {
  return value ? value.slice(0, 5) : "—";
}

export function DayEntriesTable({ dateISO, entries }: Props) {
  const [showDetail, setShowDetail] = useState(true);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const groups = useMemo(() => groupByStaff(entries), [entries]);
  const dailyTotal = useMemo(
    () => formatHoursHM(entries.reduce((s, e) => s + e.hours, 0)),
    [entries],
  );
  const colCount = showDetail ? 8 : 6;

  const toggleDetail = () => {
    setShowDetail((v) => {
      const next = !v;
      if (!next) {
        const allCollapsed: Record<string, boolean> = {};
        for (const g of groups) allCollapsed[g.staff_name] = true;
        setCollapsed(allCollapsed);
      } else {
        setCollapsed({});
      }
      return next;
    });
  };

  return (
    <div className={styles.wrap}>
      <div className={styles.toolbar}>
        <div>
          <p className="muted" style={{ margin: 0, fontSize: "0.9rem" }}>{formatDisplayDate(dateISO)}</p>
        </div>
        <div className={styles.actions}>
          {entries.length > 0 && (
            <button type="button" className={styles.toggle} onClick={toggleDetail} aria-pressed={showDetail}>
              {showDetail ? "Hide detail" : "Show detail"}
            </button>
          )}
        </div>
      </div>

      {entries.length === 0 ? (
        <div className="empty">No submitted hours for this day.</div>
      ) : (
        <div className={styles.tableScroll}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Staff</th>
                <th className={styles.clientCol}>Client</th>
                <th>Job Code</th>
                <th>Notes</th>
                {showDetail && (
                  <>
                    <th className={styles.num}>Start</th>
                    <th className={styles.num}>End</th>
                    <th className={styles.num}>Duration</th>
                  </>
                )}
                {!showDetail && <th className={styles.num}>Hours</th>}
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((group) => {
                const isCollapsed = Boolean(collapsed[group.staff_name]);
                return (
                  <StaffGroupBlock
                    key={group.staff_name}
                    group={group}
                    collapsed={isCollapsed}
                    showDetail={showDetail}
                    colCount={colCount}
                    onToggle={() =>
                      setCollapsed((p) => ({ ...p, [group.staff_name]: !p[group.staff_name] }))
                    }
                  />
                );
              })}
            </tbody>
            <tfoot>
              <tr className={styles.footer}>
                <td colSpan={showDetail ? 6 : 4}><strong>Daily total</strong></td>
                <td className={styles.num}><strong>{dailyTotal}</strong></td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  );
}

function StaffGroupBlock({
  group,
  collapsed,
  showDetail,
  colCount,
  onToggle,
}: {
  group: ReturnType<typeof groupByStaff>[0];
  collapsed: boolean;
  showDetail: boolean;
  colCount: number;
  onToggle: () => void;
}) {
  return (
    <>
      <tr className={styles.groupHeader}>
        <td colSpan={colCount}>
          <button type="button" className={styles.groupBtn} onClick={onToggle}>
            <span className={styles.chevron}>{collapsed ? "▸" : "▾"}</span>
            <span className={styles.groupName}>{group.staff_name}</span>
            <span className={styles.groupMeta}>
              {group.entries.length} entries · {formatHoursHM(group.subtotal)}
            </span>
          </button>
        </td>
      </tr>
      {!collapsed &&
        group.entries.map((entry) => (
          <tr key={entry.id} className={styles.row}>
            <td className={styles.indent}>{entry.staff_name}</td>
            <td>{entry.client}</td>
            <td>{entry.job_code}</td>
            <td>{entry.notes}</td>
            {showDetail && (
              <>
                <td className={styles.num}>{displayTime(entry.start_time)}</td>
                <td className={styles.num}>{displayTime(entry.end_time)}</td>
                <td className={styles.num}>{formatHoursHM(entry.hours)}</td>
              </>
            )}
            {!showDetail && <td className={styles.num}>{formatHoursHM(entry.hours)}</td>}
            <td><StatusChip status="submitted" /></td>
          </tr>
        ))}
      {!collapsed && (
        <tr className={styles.subtotal}>
          <td colSpan={showDetail ? 6 : 4} className={styles.indent}>Subtotal — {group.staff_name}</td>
          <td className={styles.num}>{formatHoursHM(group.subtotal)}</td>
          <td />
        </tr>
      )}
    </>
  );
}
