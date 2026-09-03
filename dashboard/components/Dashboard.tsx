"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ClientChart } from "@/components/ClientChart";
import { DayEntriesTable } from "@/components/DayEntriesTable";
import { JobChart } from "@/components/JobChart";
import { MetricCards } from "@/components/MetricCards";
import { OnTheClock } from "@/components/OnTheClock";
import { RangeToggle } from "@/components/RangeToggle";
import rangeStyles from "@/components/RangeToggle.module.css";
import { WeekCalendar } from "@/components/WeekCalendar";
import { WeekChart } from "@/components/WeekChart";
import {
  aggregateByClient,
  aggregateByJob,
  computeMetrics,
  dailyTotals,
} from "@/lib/aggregations";
import { getEntriesProvider } from "@/lib/data/entries-provider";
import {
  defaultFocusDay,
  entriesForDay,
  filterEntriesByRange,
  formatDisplayDate,
  resolveRange,
  todayISO,
  type RangeKey,
} from "@/lib/dates";
import type { CurrentlyWorking } from "@/lib/types/currently-working";
import type { Employee } from "@/lib/types/employee";
import type { TimeEntry } from "@/lib/types/time-entry";

const POLL_MS = 30_000;

type DetailView = "detail" | "calendar";

export function Dashboard() {
  const provider = useMemo(() => getEntriesProvider(), []);
  const [range, setRange] = useState<RangeKey>("today");
  const [selectedDay, setSelectedDay] = useState(todayISO());
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [live, setLive] = useState<CurrentlyWorking[]>([]);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [detailView, setDetailView] = useState<DetailView>("detail");
  const [staffFilter, setStaffFilter] = useState("");

  const resolved = useMemo(() => resolveRange(range), [range]);

  const loadPollable = useCallback(async (showLoading: boolean) => {
    if (showLoading) setLoading(true);
    try {
      const [rows, liveRows] = await Promise.all([
        provider.fetchEntries({
          dateFrom: resolved.dateFrom,
          dateTo: resolved.dateTo,
        }),
        provider.fetchCurrentlyWorking().catch(() => [] as CurrentlyWorking[]),
      ]);
      setEntries(rows);
      setLive(liveRows);
      setUpdatedAt(new Date());
    } catch {
      /* keep last snapshot */
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [provider, resolved.dateFrom, resolved.dateTo]);

  useEffect(() => {
    void (async () => {
      setLoading(true);
      try {
        const [rows, liveRows, roster] = await Promise.all([
          provider.fetchEntries({
            dateFrom: resolved.dateFrom,
            dateTo: resolved.dateTo,
          }),
          provider.fetchCurrentlyWorking().catch(() => [] as CurrentlyWorking[]),
          provider.fetchEmployees().catch(() => [] as Employee[]),
        ]);
        setEntries(rows);
        setLive(liveRows);
        setEmployees(roster);
        setUpdatedAt(new Date());
      } finally {
        setLoading(false);
      }
    })();
  }, [provider, resolved.dateFrom, resolved.dateTo]);

  useEffect(() => {
    const tick = () => {
      if (document.visibilityState !== "visible") return;
      void loadPollable(false);
    };
    const id = window.setInterval(tick, POLL_MS);
    const onVis = () => {
      if (document.visibilityState === "visible") tick();
    };
    window.addEventListener("focus", tick);
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("focus", tick);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [loadPollable]);

  useEffect(() => {
    setSelectedDay(defaultFocusDay(range, entries, todayISO()));
  }, [range, entries]);

  const staffOptions = useMemo(() => {
    const names = new Set<string>();
    for (const e of employees) if (e.active && e.staff_name) names.add(e.staff_name);
    for (const e of entries) if (e.staff_name) names.add(e.staff_name);
    return [...names].sort((a, b) => a.localeCompare(b));
  }, [employees, entries]);

  const scopedEntries = useMemo(
    () => (staffFilter ? entries.filter((e) => e.staff_name === staffFilter) : entries),
    [entries, staffFilter],
  );

  const rangeEntries = useMemo(
    () => filterEntriesByRange(scopedEntries, resolved),
    [scopedEntries, resolved],
  );

  const chartEntries = useMemo(() => {
    if (range === "today" || range === "yesterday") {
      return filterEntriesByRange(scopedEntries, resolveRange("week"));
    }
    return rangeEntries;
  }, [scopedEntries, range, rangeEntries]);

  const weekBars = useMemo(
    () => dailyTotals(resolved.chartDays, chartEntries),
    [resolved.chartDays, chartEntries],
  );

  const metrics = useMemo(() => computeMetrics(rangeEntries), [rangeEntries]);
  const byClient = useMemo(() => aggregateByClient(rangeEntries), [rangeEntries]);
  const byJob = useMemo(() => aggregateByJob(rangeEntries), [rangeEntries]);

  const dayEntries = useMemo(
    () => entriesForDay(selectedDay, scopedEntries),
    [selectedDay, scopedEntries],
  );
  const calendarEntries = useMemo(
    () =>
      staffFilter
        ? scopedEntries.filter((e) => resolved.chartDays.includes(e.entry_date))
        : [],
    [scopedEntries, resolved.chartDays, staffFilter],
  );

  const pickStaffForCalendar = () => {
    if (staffFilter) return;
    const withHours = staffOptions.find((name) =>
      entries.some((e) => e.staff_name === name && resolved.chartDays.includes(e.entry_date)),
    );
    setStaffFilter(withHours ?? staffOptions[0] ?? "");
  };

  const scopeLabel = staffFilter || "All staff";
  const contextLabel =
    range === "week" || range === "thisPayPeriod" || range === "lastPayPeriod"
      ? `${resolved.label} · ${formatDisplayDate(selectedDay)} · ${scopeLabel}`
      : `${formatDisplayDate(selectedDay)} · ${scopeLabel}`;

  const updatedLabel = updatedAt
    ? `Updated ${updatedAt.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`
    : "";

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">GCD · Firm hours</div>
          <div className="brand-sub">Founder admin · view-only</div>
        </div>
        <div className="staff-meta">
          <div className="muted">{contextLabel}</div>
          {updatedLabel && <div className="muted">{updatedLabel}</div>}
        </div>
      </header>

      <div className="section-head">
        <RangeToggle value={range} onChange={setRange} />
        <label className="staff-filter">
          <span className="muted">Employee</span>
          <select
            value={staffFilter}
            onChange={(e) => setStaffFilter(e.target.value)}
            aria-label="Filter by employee"
          >
            <option value="">All staff</option>
            {staffOptions.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {loading ? (
        <p className="muted">Loading…</p>
      ) : (
        <>
          <OnTheClock sessions={live} employees={employees} />

          <section className="section" aria-label="Overview metrics">
            <MetricCards metrics={metrics} />
          </section>

          <section className="section" aria-label="Charts">
            <h2 className="section-title">
              {range === "week" ? "This week" : range.includes("Pay") ? resolved.label : "This week so far"}
            </h2>
            <div className="charts-grid">
              <WeekChart
                data={weekBars}
                selectedDate={selectedDay}
                onSelectDate={setSelectedDay}
              />
              <ClientChart title="Hours by client" data={byClient} />
              <JobChart data={byJob} />
            </div>
          </section>

          <section className="section" aria-label="Day detail or calendar">
            <div className="section-head">
              <h2 className="section-title" style={{ marginBottom: 0 }}>
                {detailView === "calendar" ? "Calendar" : "Day detail"}
              </h2>
              <div className={rangeStyles.wrap} role="tablist" aria-label="Detail view">
                <button
                  type="button"
                  role="tab"
                  aria-selected={detailView === "detail"}
                  className={detailView === "detail" ? rangeStyles.active : rangeStyles.btn}
                  onClick={() => setDetailView("detail")}
                >
                  Day Detail
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={detailView === "calendar"}
                  className={detailView === "calendar" ? rangeStyles.active : rangeStyles.btn}
                  onClick={() => {
                    pickStaffForCalendar();
                    setDetailView("calendar");
                  }}
                >
                  Calendar
                </button>
              </div>
            </div>
            {detailView === "detail" ? (
              <DayEntriesTable dateISO={selectedDay} entries={dayEntries} />
            ) : staffFilter ? (
              <WeekCalendar days={resolved.chartDays} entries={calendarEntries} />
            ) : (
              <p className="muted">Select an employee to view their calendar.</p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
