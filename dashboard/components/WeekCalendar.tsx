"use client";

import { useEffect, useMemo, useRef, type MouseEvent } from "react";
import {
  assignLanes,
  calendarAxisMinutes,
  formatHourLabel,
  hourTicks,
  splitScheduled,
} from "@/lib/calendar-blocks";
import { slotFromDayColumnClick } from "@/lib/calendar-slot";
import { formatHoursHM } from "@/lib/hours-format";
import { canDashboardMutateEntry, isWithinEditWindow } from "@/lib/pay-period";
import { weekdayShort } from "@/lib/dates";
import { isAdminEntry, type TimeEntry } from "@/lib/types/time-entry";
import styles from "./WeekCalendar.module.css";

type CreateRequest = {
  entry_date: string;
  start_time: string;
  end_time: string;
};

type Props = {
  days: string[];
  entries: TimeEntry[];
  targetStaffName: string;
  viewerStaffName: string;
  viewerIsAdmin: boolean;
  onCreateRequest: (req: CreateRequest) => void;
  onEditRequest: (entry: TimeEntry) => void;
  onDeleteRequest: (entry: TimeEntry) => void;
};

const HOUR_PX = 48;
const SCROLL_TO_HOUR = 8;

function dayHeadLabel(iso: string): string {
  return `${Number(iso.slice(5, 7))}/${Number(iso.slice(8))}`;
}

export function WeekCalendar({
  days,
  entries,
  targetStaffName,
  viewerStaffName,
  viewerIsAdmin,
  onCreateRequest,
  onEditRequest,
  onDeleteRequest,
}: Props) {
  const { scheduled, unscheduled } = useMemo(() => splitScheduled(entries), [entries]);
  const axis = useMemo(() => calendarAxisMinutes(), []);
  const ticks = useMemo(() => hourTicks(axis.start, axis.end), [axis.start, axis.end]);
  const scrollRef = useRef<HTMLDivElement>(null);

  const byDay = useMemo(() => {
    const map = new Map<string, TimeEntry[]>();
    for (const d of days) map.set(d, []);
    for (const e of scheduled) {
      const list = map.get(e.entry_date);
      if (list) list.push(e);
    }
    return map;
  }, [days, scheduled]);

  const unscheduledByDay = useMemo(() => {
    const map = new Map<string, TimeEntry[]>();
    for (const d of days) map.set(d, []);
    for (const e of unscheduled) {
      const list = map.get(e.entry_date);
      if (list) list.push(e);
    }
    return map;
  }, [days, unscheduled]);

  const bodyHeight = ((axis.end - axis.start) / 60) * HOUR_PX;
  const span = axis.end - axis.start;
  const cols = `4.5rem repeat(${days.length}, minmax(9.5rem, 1fr))`;

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = SCROLL_TO_HOUR * HOUR_PX;
  }, [days.join(",")]);

  function canMutate(entry: TimeEntry): boolean {
    return canDashboardMutateEntry({
      entryDate: entry.entry_date,
      actorIsAdmin: viewerIsAdmin,
      actorStaffName: viewerStaffName,
      entryStaffName: entry.staff_name,
    });
  }

  function canCreate(date: string): boolean {
    if (!targetStaffName) return false;
    if (viewerIsAdmin) return true;
    return isWithinEditWindow(date);
  }

  function handleDayClick(day: string, e: MouseEvent<HTMLDivElement>) {
    if (!canCreate(day)) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const offsetY = e.clientY - rect.top;
    const slot = slotFromDayColumnClick(offsetY, bodyHeight, axis.start, axis.end);
    onCreateRequest({ entry_date: day, ...slot });
  }

  return (
    <div className={styles.shell}>
      <div className={styles.wrap} ref={scrollRef}>
        <div className={styles.grid} style={{ gridTemplateColumns: cols, minWidth: `max(100%, ${4.5 + days.length * 9.5}rem)` }}>
          <div className={styles.corner} />
          {days.map((d) => (
            <div key={d} className={styles.dayHead}>
              <span>{weekdayShort(d)}</span>
              <span className={styles.dayNum}>{dayHeadLabel(d)}</span>
            </div>
          ))}

          <div className={styles.axis} style={{ height: bodyHeight }}>
            {ticks.map((m) => (
              <div
                key={m}
                className={styles.tick}
                style={{ top: `${((m - axis.start) / span) * 100}%` }}
              >
                {formatHourLabel(m)}
              </div>
            ))}
          </div>

          {days.map((d) => {
            const blocks = assignLanes(byDay.get(d) ?? []);
            const createOk = canCreate(d);
            return (
              <div
                key={d}
                className={`${styles.dayCol} ${createOk ? styles.dayColEditable : styles.dayColLocked}`}
                style={{ height: bodyHeight }}
                onClick={(e) => handleDayClick(d, e)}
                title={createOk ? "Click empty space to add an entry" : "Outside edit window"}
              >
                {ticks.map((m) => (
                  <div
                    key={m}
                    className={styles.hourLine}
                    style={{ top: `${((m - axis.start) / span) * 100}%` }}
                  />
                ))}
                {blocks.map((b) => {
                  const top = ((b.startMin - axis.start) / span) * 100;
                  const height = ((b.endMin - b.startMin) / span) * 100;
                  const width = 100 / b.laneCount;
                  const left = b.lane * width;
                  const admin = isAdminEntry(b.entry);
                  const mutable = canMutate(b.entry);
                  return (
                    <div
                      key={b.entry.id}
                      className={`${admin ? styles.blockAdmin : styles.block} ${mutable ? styles.blockClickable : styles.blockLocked}`}
                      style={{
                        top: `${top}%`,
                        height: `${Math.max(height, 2)}%`,
                        left: `calc(${left}% + 2px)`,
                        width: `calc(${width}% - 4px)`,
                      }}
                      title={`${b.entry.client} · ${b.entry.job_code} · ${formatHoursHM(b.entry.hours)}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        if (mutable) onEditRequest(b.entry);
                      }}
                    >
                      <span className={styles.blockStaff}>{b.entry.client}</span>
                      <span className={styles.blockClient}>{b.entry.job_code}</span>
                      {mutable ? (
                        <button
                          type="button"
                          className={styles.blockDelete}
                          onClick={(ev) => {
                            ev.stopPropagation();
                            const label = `${b.entry.client}${b.entry.notes ? ` — ${b.entry.notes}` : ""}`;
                            if (!window.confirm(`Delete this time entry?\n${label}`)) return;
                            onDeleteRequest(b.entry);
                          }}
                        >
                          Delete
                        </button>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            );
          })}

          {unscheduled.length > 0 ? (
            <>
              <div className={styles.unscheduledLabelSticky}>
                <div className={styles.unscheduledLabel}>Duration only</div>
                <p className={styles.unscheduledHint}>No start/end — not on the clock grid</p>
              </div>
              {days.map((d) => {
                const rows = unscheduledByDay.get(d) ?? [];
                return (
                  <div key={`u-${d}`} className={styles.unscheduledDay}>
                    {rows.map((e) => {
                      const mutable = canMutate(e);
                      return (
                        <div
                          key={e.id}
                          className={`${isAdminEntry(e) ? styles.chipAdmin : styles.chip} ${mutable ? styles.blockClickable : styles.blockLocked}`}
                          onClick={() => {
                            if (mutable) onEditRequest(e);
                          }}
                          title={mutable ? "Click to edit" : "Outside edit window"}
                        >
                          <strong>{e.client}</strong>
                          <span>{e.job_code}</span>
                          <span>{formatHoursHM(e.hours)}</span>
                          {mutable ? (
                            <button
                              type="button"
                              className={styles.blockDelete}
                              onClick={(ev) => {
                                ev.stopPropagation();
                                const label = `${e.client}${e.notes ? ` — ${e.notes}` : ""}`;
                                if (!window.confirm(`Delete this time entry?\n${label}`)) return;
                                onDeleteRequest(e);
                              }}
                            >
                              Delete
                            </button>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                );
              })}
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
