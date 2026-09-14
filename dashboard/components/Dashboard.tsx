"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ClientChart } from "@/components/ClientChart";
import { DayEntriesTable } from "@/components/DayEntriesTable";
import { EntryEditorModal, type EntryEditorDefaults } from "@/components/EntryEditorModal";
import { JobChart } from "@/components/JobChart";
import { MetricCards } from "@/components/MetricCards";
import { OutOfWindowConfirm } from "@/components/OutOfWindowConfirm";
import { RangeToggle } from "@/components/RangeToggle";
import rangeStyles from "@/components/RangeToggle.module.css";
import { RemapUnassignedModal } from "@/components/RemapUnassignedModal";
import { WeekCalendar } from "@/components/WeekCalendar";
import { WeekChart } from "@/components/WeekChart";
import {
  aggregateByClient,
  aggregateByJob,
  computeMetrics,
  dailyTotals,
} from "@/lib/aggregations";
import { applyChartFilters } from "@/lib/chart-filters";
import { getEntriesProvider } from "@/lib/data/entries-provider";
import {
  defaultFocusDay,
  filterEntriesByRange,
  formatDisplayDate,
  resolveRange,
  todayISO,
  type RangeKey,
} from "@/lib/dates";
import { formatHoursHM } from "@/lib/hours-format";
import { isWithinEditWindow } from "@/lib/pay-period";
import type { CurrentlyWorking } from "@/lib/types/currently-working";
import type { DashboardUser, Employee } from "@/lib/types/employee";
import type { ClientOption, JobCodeOption } from "@/lib/types/reference-data";
import type { EntryWritePayload, TimeEntry } from "@/lib/types/time-entry";

const POLL_MS = 30_000;

type DetailView = "detail" | "calendar";

type EditorState =
  | { open: false }
  | {
      open: true;
      mode: "create" | "edit";
      entry?: TimeEntry | null;
      defaults?: EntryEditorDefaults | null;
      staffName: string;
    };

function elapsedLabel(startedAt: string): string {
  const start = new Date(startedAt).getTime();
  if (Number.isNaN(start)) return "";
  const hours = Math.max(0, (Date.now() - start) / 3_600_000);
  return formatHoursHM(hours);
}

export function Dashboard() {
  const provider = useMemo(() => getEntriesProvider(), []);
  const [me, setMe] = useState<DashboardUser | null>(null);
  const [range, setRange] = useState<RangeKey>("today");
  const [selectedDay, setSelectedDay] = useState(todayISO());
  const [dayFilter, setDayFilter] = useState<string | null>(null);
  const [clientFilter, setClientFilter] = useState<string | null>(null);
  const [jobFilter, setJobFilter] = useState<string | null>(null);
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [clients, setClients] = useState<ClientOption[]>([]);
  const [jobCodes, setJobCodes] = useState<JobCodeOption[]>([]);
  const [live, setLive] = useState<CurrentlyWorking[]>([]);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [detailView, setDetailView] = useState<DetailView>("detail");
  const [staffFilter, setStaffFilter] = useState("");
  const [officeFilter, setOfficeFilter] = useState("");
  const [tick, setTick] = useState(0);
  const [editor, setEditor] = useState<EditorState>({ open: false });
  const [pendingCreate, setPendingCreate] = useState<EntryEditorDefaults | null>(null);
  const [createWarnOpen, setCreateWarnOpen] = useState(false);
  const [remapOpen, setRemapOpen] = useState(false);

  const resolved = useMemo(() => resolveRange(range), [range]);

  const liveStaffName = useMemo(() => {
    if (!me) return "";
    if (me.is_admin && staffFilter) return staffFilter;
    return me.staff_name;
  }, [me, staffFilter]);

  const headerName = useMemo(() => {
    if (!me) return "";
    if (me.is_admin && staffFilter) return staffFilter;
    return me.staff_name;
  }, [me, staffFilter]);

  const loadPollable = useCallback(
    async (showLoading: boolean) => {
      if (showLoading) setLoading(true);
      try {
        const staffParam = me && !me.is_admin ? me.staff_name : staffFilter || undefined;
        const officeParam = me?.is_admin && officeFilter ? officeFilter : undefined;
        const [rows, liveRows] = await Promise.all([
          provider.fetchEntries({
            dateFrom: resolved.dateFrom,
            dateTo: resolved.dateTo,
            staffName: staffParam,
            office: officeParam,
          }),
          provider.fetchCurrentlyWorking(liveStaffName || undefined).catch(() => [] as CurrentlyWorking[]),
        ]);
        setEntries(rows);
        setLive(liveRows);
        setUpdatedAt(new Date());
      } catch {
        /* keep last snapshot */
      } finally {
        if (showLoading) setLoading(false);
      }
    },
    [provider, resolved.dateFrom, resolved.dateTo, me, staffFilter, officeFilter, liveStaffName],
  );

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch("/api/me");
        if (res.ok) {
          const user = (await res.json()) as DashboardUser;
          setMe(user);
          if (!user.is_admin) setStaffFilter(user.staff_name);
        }
      } catch {
        /* mock still works via API */
      }
    })();
  }, []);

  useEffect(() => {
    if (!me) return;
    void (async () => {
      setLoading(true);
      try {
        const staffParam = !me.is_admin ? me.staff_name : staffFilter || undefined;
        const officeParam = me.is_admin && officeFilter ? officeFilter : undefined;
        const [rows, liveRows, roster, clientRows, jobRows] = await Promise.all([
          provider.fetchEntries({
            dateFrom: resolved.dateFrom,
            dateTo: resolved.dateTo,
            staffName: staffParam,
            office: officeParam,
          }),
          provider.fetchCurrentlyWorking(liveStaffName || me.staff_name).catch(() => [] as CurrentlyWorking[]),
          provider.fetchEmployees().catch(() => [] as Employee[]),
          provider.fetchClients().catch(() => [] as ClientOption[]),
          provider.fetchJobCodes().catch(() => [] as JobCodeOption[]),
        ]);
        setEntries(rows);
        setLive(liveRows);
        setEmployees(roster);
        setClients(clientRows);
        setJobCodes(jobRows);
        setUpdatedAt(new Date());
      } finally {
        setLoading(false);
      }
    })();
  }, [provider, resolved.dateFrom, resolved.dateTo, me, staffFilter, officeFilter, liveStaffName]);

  useEffect(() => {
    const id = window.setInterval(() => setTick((t) => t + 1), 30_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    const tickPoll = () => {
      if (document.visibilityState !== "visible") return;
      void loadPollable(false);
    };
    const id = window.setInterval(tickPoll, POLL_MS);
    const onVis = () => {
      if (document.visibilityState === "visible") tickPoll();
    };
    window.addEventListener("focus", tickPoll);
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("focus", tickPoll);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [loadPollable]);

  useEffect(() => {
    setSelectedDay(defaultFocusDay(range, entries, todayISO()));
    setDayFilter(null);
    setClientFilter(null);
    setJobFilter(null);
  }, [range]);

  const staffOptions = useMemo(() => {
    const names = new Set<string>();
    const officeNorm = officeFilter.toUpperCase();
    for (const e of employees) {
      if (!e.active || !e.staff_name) continue;
      if (officeNorm && e.office.toUpperCase() !== officeNorm) continue;
      names.add(e.staff_name);
    }
    for (const e of entries) if (e.staff_name) names.add(e.staff_name);
    return [...names].sort((a, b) => a.localeCompare(b));
  }, [employees, entries, officeFilter]);

  const pickerClients = useMemo(() => {
    const officeNorm = officeFilter.toUpperCase();
    if (!officeNorm) return clients;
    return clients.filter((c) => c.office.toUpperCase() === officeNorm);
  }, [clients, officeFilter]);

  const scopedEntries = useMemo(() => {
    if (!me) return entries;
    if (!me.is_admin) return entries.filter((e) => e.staff_name === me.staff_name);
    if (staffFilter) return entries.filter((e) => e.staff_name === staffFilter);
    return entries;
  }, [entries, me, staffFilter]);

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

  const tableEntries = useMemo(
    () =>
      applyChartFilters(rangeEntries, {
        day: dayFilter,
        client: clientFilter,
        job: jobFilter,
      }),
    [rangeEntries, dayFilter, clientFilter, jobFilter],
  );

  const calendarEntries = useMemo(() => {
    const staff = staffFilter || me?.staff_name || "";
    if (!staff) return [];
    return scopedEntries.filter(
      (e) => e.staff_name === staff && resolved.chartDays.includes(e.entry_date),
    );
  }, [scopedEntries, resolved.chartDays, staffFilter, me]);

  const pickStaffForCalendar = () => {
    if (staffFilter || !me?.is_admin) return;
    const withHours = staffOptions.find((name) =>
      entries.some((e) => e.staff_name === name && resolved.chartDays.includes(e.entry_date)),
    );
    setStaffFilter(withHours ?? staffOptions[0] ?? me.staff_name);
  };

  const multiDay = resolved.chartDays.length > 1 && !dayFilter;

  const updatedLabel = updatedAt
    ? `Updated ${updatedAt.toLocaleDateString("en-US", {
        month: "numeric",
        day: "numeric",
        year: "numeric",
      })} ${updatedAt.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`
    : "";

  const liveSession = live[0];
  void tick;

  async function handleSave(id: number, payload: EntryWritePayload) {
    const row = entries.find((e) => e.id === id);
    const body =
      me?.is_admin
        ? {
            ...payload,
            staff_name: staffFilter || row?.staff_name || me.staff_name,
          }
        : payload;
    await provider.updateEntry(id, body);
    await loadPollable(false);
  }

  const calendarStaff = staffFilter || (me && !me.is_admin ? me.staff_name : "") || "";

  function openCreateEditor(defaults: EntryEditorDefaults) {
    if (!calendarStaff || !me) return;
    setEditor({
      open: true,
      mode: "create",
      defaults: {
        ...defaults,
        office: defaults.office || officeFilter || me.office || "GCD",
      },
      staffName: calendarStaff,
    });
  }

  function requestCalendarCreate(req: {
    entry_date: string;
    start_time: string;
    end_time: string;
  }) {
    if (!calendarStaff || !me) return;
    const defaults: EntryEditorDefaults = {
      entry_date: req.entry_date,
      start_time: req.start_time,
      end_time: req.end_time,
      hours: 1,
      office: officeFilter || me.office || "GCD",
    };
    if (me.is_admin && !isWithinEditWindow(req.entry_date)) {
      setPendingCreate(defaults);
      setCreateWarnOpen(true);
      return;
    }
    openCreateEditor(defaults);
  }

  function requestCalendarEdit(entry: TimeEntry) {
    if (!me) return;
    setEditor({
      open: true,
      mode: "edit",
      entry,
      staffName: entry.staff_name,
    });
  }

  async function handleEditorSave(payload: EntryWritePayload) {
    if (!editor.open || !me) return;
    if (editor.mode === "create") {
      await provider.createEntry({
        ...payload,
        staff_name: me.is_admin ? editor.staffName : me.staff_name,
      });
    } else if (editor.entry) {
      await provider.updateEntry(editor.entry.id, {
        ...payload,
        staff_name: me.is_admin ? editor.staffName : me.staff_name,
      });
    }
    await loadPollable(false);
  }

  if (!me && loading) {
    return (
      <div className="page">
        <p className="muted">Loading…</p>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand">
          <img src="/timmy-lockup-green.svg" alt="Timmy" className="brand-logo" height={44} />
        </div>
        <div className="staff-meta">
          <strong>{headerName || "…"}</strong>
          {me?.is_admin && staffFilter && staffFilter !== me.staff_name ? (
            <div className="muted" style={{ fontSize: "0.85rem" }}>
              Signed in as {me.staff_name}
            </div>
          ) : null}
          {updatedLabel ? <div className="muted">{updatedLabel}</div> : null}
          {liveSession ? (
            <div>
              Currently working on: {liveSession.client}{" "}
              {liveSession.started_at ? elapsedLabel(liveSession.started_at) : ""}
            </div>
          ) : null}
        </div>
      </header>

      <div className="section-head">
        <RangeToggle value={range} onChange={setRange} />
        {me?.is_admin ? (
          <>
            <label className="staff-filter">
              <span className="muted">Office</span>
              <select
                value={officeFilter}
                onChange={(e) => setOfficeFilter(e.target.value)}
                aria-label="Filter by office"
              >
                <option value="">All offices</option>
                <option value="GCD">GCD</option>
                <option value="MH">MH</option>
              </select>
            </label>
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
            <button type="button" className="chip" onClick={() => setRemapOpen(true)}>
              Remap Unassigned
            </button>
          </>
        ) : null}
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
                selectedDate={dayFilter}
                onSelectDate={(d) => {
                  setDayFilter(d);
                  setSelectedDay(d);
                }}
              />
              <ClientChart
                title="Hours by client"
                data={byClient}
                selectedName={clientFilter}
                onSelectName={setClientFilter}
              />
              <JobChart data={byJob} selectedName={jobFilter} onSelectName={setJobFilter} />
            </div>
          </section>

          {(dayFilter || clientFilter || jobFilter) && (
            <div className="filter-chips" aria-label="Active chart filters">
              {dayFilter ? (
                <button type="button" className="chip" onClick={() => setDayFilter(null)}>
                  Day: {formatDisplayDate(dayFilter)} ×
                </button>
              ) : null}
              {clientFilter ? (
                <button type="button" className="chip" onClick={() => setClientFilter(null)}>
                  Client: {clientFilter} ×
                </button>
              ) : null}
              {jobFilter ? (
                <button type="button" className="chip" onClick={() => setJobFilter(null)}>
                  Job: {jobFilter} ×
                </button>
              ) : null}
            </div>
          )}

          <section className="section" aria-label="Time entry detail or calendar">
            <div className="section-head">
              <h2 className="section-title" style={{ marginBottom: 0 }}>
                Time Entry Detail
              </h2>
              <div className={rangeStyles.wrap} role="tablist" aria-label="Detail view">
                <button
                  type="button"
                  role="tab"
                  aria-selected={detailView === "detail"}
                  className={detailView === "detail" ? rangeStyles.active : rangeStyles.btn}
                  onClick={() => setDetailView("detail")}
                >
                  Table View
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
                  Calendar View
                </button>
              </div>
            </div>
            {detailView === "detail" ? (
              <DayEntriesTable
                entries={tableEntries}
                multiDay={multiDay || new Set(tableEntries.map((e) => e.entry_date)).size > 1}
                viewerStaffName={me?.staff_name ?? ""}
                viewerIsAdmin={Boolean(me?.is_admin)}
                clients={pickerClients}
                jobCodes={jobCodes}
                onSave={handleSave}
              />
            ) : staffFilter || (me && !me.is_admin) ? (
              <WeekCalendar
                days={resolved.chartDays}
                entries={calendarEntries}
                targetStaffName={calendarStaff}
                viewerStaffName={me?.staff_name ?? ""}
                viewerIsAdmin={Boolean(me?.is_admin)}
                onCreateRequest={requestCalendarCreate}
                onEditRequest={requestCalendarEdit}
              />
            ) : (
              <p className="muted">Select an employee to view their calendar.</p>
            )}
          </section>
        </>
      )}

      <EntryEditorModal
        open={editor.open}
        mode={editor.open ? editor.mode : "create"}
        entry={editor.open ? editor.entry : null}
        defaults={editor.open ? editor.defaults : null}
        staffName={editor.open ? editor.staffName : ""}
        viewerIsAdmin={Boolean(me?.is_admin)}
        clients={clients}
        defaultOffice={officeFilter || me?.office || "GCD"}
        jobCodes={jobCodes}
        onClose={() => setEditor({ open: false })}
        onSave={handleEditorSave}
      />

      <RemapUnassignedModal
        open={remapOpen}
        clients={clients}
        defaultOffice={officeFilter || "GCD"}
        onClose={() => setRemapOpen(false)}
        onDone={() => {
          setRemapOpen(false);
          void loadPollable(true);
        }}
      />

      <OutOfWindowConfirm
        open={createWarnOpen}
        mode="create"
        onCancel={() => {
          setCreateWarnOpen(false);
          setPendingCreate(null);
        }}
        onConfirm={() => {
          setCreateWarnOpen(false);
          if (pendingCreate) openCreateEditor(pendingCreate);
          setPendingCreate(null);
        }}
      />
    </div>
  );
}
