"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ClientChart } from "@/components/ClientChart";
import { DayEntriesTable } from "@/components/DayEntriesTable";
import { JobChart } from "@/components/JobChart";
import { MetricCards } from "@/components/MetricCards";
import { RangeToggle } from "@/components/RangeToggle";
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
import { isEditable } from "@/lib/pay-period";
import { MOCK_STAFF } from "@/lib/mock-data";
import type { ClientOption, JobCodeOption } from "@/lib/types/reference-data";
import type { EntryWritePayload, TimeEntry } from "@/lib/types/time-entry";

export function Dashboard() {
  const provider = useMemo(() => getEntriesProvider(), []);
  const [range, setRange] = useState<RangeKey>("today");
  const [selectedDay, setSelectedDay] = useState(todayISO());
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [clients, setClients] = useState<ClientOption[]>([]);
  const [jobCodes, setJobCodes] = useState<JobCodeOption[]>([]);
  const [loading, setLoading] = useState(true);

  const resolved = useMemo(() => resolveRange(range), [range]);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [rows, clientRows, jobRows] = await Promise.all([
        provider.fetchEntries({
          staffName: MOCK_STAFF.staff_name,
          dateFrom: resolved.dateFrom,
          dateTo: resolved.dateTo,
        }),
        provider.fetchClients(),
        provider.fetchJobCodes(),
      ]);
      setEntries(rows);
      setClients(clientRows);
      setJobCodes(jobRows);
    } finally {
      setLoading(false);
    }
  }, [provider, resolved.dateFrom, resolved.dateTo]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  useEffect(() => {
    setSelectedDay(defaultFocusDay(range, entries, todayISO()));
  }, [range, entries]);

  const onRangeChange = (next: RangeKey) => {
    setRange(next);
  };

  const rangeEntries = useMemo(
    () => filterEntriesByRange(entries, resolved),
    [entries, resolved],
  );

  const chartEntries = useMemo(() => {
    if (range === "today" || range === "yesterday") {
      return filterEntriesByRange(entries, resolveRange("week"));
    }
    return rangeEntries;
  }, [entries, range, rangeEntries]);

  const weekBars = useMemo(
    () => dailyTotals(resolved.chartDays, chartEntries),
    [resolved.chartDays, chartEntries],
  );

  const metrics = useMemo(() => computeMetrics(rangeEntries), [rangeEntries]);
  const byClient = useMemo(() => aggregateByClient(rangeEntries), [rangeEntries]);
  const byJob = useMemo(() => aggregateByJob(rangeEntries), [rangeEntries]);
  const dayEntries = useMemo(() => entriesForDay(selectedDay, entries), [selectedDay, entries]);

  const canEditDay = isEditable(selectedDay, MOCK_STAFF.staff_name);

  const contextLabel =
    range === "week" || range === "thisPayPeriod" || range === "lastPayPeriod"
      ? `${resolved.label} · ${formatDisplayDate(selectedDay)}`
      : formatDisplayDate(selectedDay);

  const handleCreate = async (payload: EntryWritePayload) => {
    await provider.createEntry(payload);
    await loadAll();
  };

  const handleUpdate = async (id: number, payload: EntryWritePayload) => {
    await provider.updateEntry(id, payload);
    await loadAll();
  };

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">{MOCK_STAFF.staff_name}</div>
          <div className="brand-sub">Timmy · personal hours · {MOCK_STAFF.office}</div>
        </div>
        <div className="staff-meta">
          <div className="muted">{contextLabel}</div>
        </div>
      </header>

      <div className="section-head">
        <RangeToggle value={range} onChange={onRangeChange} />
      </div>

      {loading ? (
        <p className="muted">Loading…</p>
      ) : (
        <>
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

          <section className="section" aria-label="Day detail">
            <DayEntriesTable
              dateISO={selectedDay}
              entries={dayEntries}
              staffName={MOCK_STAFF.staff_name}
              clients={clients}
              jobCodes={jobCodes}
              canEditDay={canEditDay}
              onCreate={handleCreate}
              onUpdate={handleUpdate}
            />
          </section>
        </>
      )}
    </div>
  );
}
