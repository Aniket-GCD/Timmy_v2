"use client";

import { useMemo, useState } from "react";
import { ClientChart } from "@/components/ClientChart";
import { DayEntriesTable } from "@/components/DayEntriesTable";
import { JobChart } from "@/components/JobChart";
import { MetricCards } from "@/components/MetricCards";
import { RangeToggle, type RangeKey } from "@/components/RangeToggle";
import { WeekChart } from "@/components/WeekChart";
import {
  aggregateByClient,
  aggregateByJob,
  computeMetrics,
  dailyTotals,
} from "@/lib/aggregations";
import { formatDisplayDate, todayISO, yesterdayISO } from "@/lib/dates";
import {
  entriesForDay,
  entriesForRange,
  entriesForWeek,
  MOCK_ENTRIES,
  MOCK_STAFF,
} from "@/lib/mock-data";

export function Dashboard() {
  const [range, setRange] = useState<RangeKey>("today");
  const [selectedDay, setSelectedDay] = useState(todayISO());

  const onRangeChange = (next: RangeKey) => {
    setRange(next);
    if (next === "today") setSelectedDay(todayISO());
    if (next === "yesterday") setSelectedDay(yesterdayISO());
    // week: keep selectedDay so chart click / prior selection sticks
  };

  const rangeEntries = useMemo(
    () => entriesForRange(range, selectedDay, new Date(), MOCK_ENTRIES),
    [range, selectedDay],
  );

  const weekEntries = useMemo(() => entriesForWeek(new Date(), MOCK_ENTRIES), []);
  const weekBars = useMemo(() => dailyTotals(new Date(), weekEntries), [weekEntries]);

  const metrics = useMemo(() => computeMetrics(rangeEntries), [rangeEntries]);
  const byClient = useMemo(() => aggregateByClient(rangeEntries), [rangeEntries]);
  const byJob = useMemo(() => aggregateByJob(rangeEntries), [rangeEntries]);

  const dayEntries = useMemo(() => entriesForDay(selectedDay, MOCK_ENTRIES), [selectedDay]);

  const contextLabel =
    range === "week"
      ? `This week · focusing ${formatDisplayDate(selectedDay)}`
      : formatDisplayDate(selectedDay);

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">Timmy</div>
          <div className="brand-sub">Personal hours · mock preview for lead review</div>
        </div>
        <div className="staff-meta">
          <div>
            <strong>{MOCK_STAFF.staff_name}</strong> · {MOCK_STAFF.office}
          </div>
          <div className="muted">{contextLabel}</div>
        </div>
      </header>

      <div className="section-head">
        <RangeToggle value={range} onChange={onRangeChange} />
      </div>

      <section className="section" aria-label="Overview metrics">
        <MetricCards metrics={metrics} />
      </section>

      <section className="section" aria-label="Charts">
        <h2 className="section-title">
          {range === "week" ? "This week" : "This week so far"}
        </h2>
        <div className="charts-grid">
          <WeekChart
            data={weekBars}
            selectedDate={selectedDay}
            onSelectDate={(date) => {
              setSelectedDay(date);
              setRange("week");
            }}
          />
          <ClientChart title="Hours by client" data={byClient} />
          <JobChart data={byJob} />
        </div>
      </section>

      <section className="section" aria-label="Day detail">
        <DayEntriesTable dateISO={selectedDay} entries={dayEntries} />
      </section>
    </div>
  );
}
