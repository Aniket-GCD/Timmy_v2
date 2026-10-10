"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import styles from "./TimeByJobReport.module.css";
import { MultiCombobox } from "./MultiCombobox";
import { getEntriesProvider } from "@/lib/data/entries-provider";
import { lastMonthRange, resolveRange, thisMonthRange, type RangeKey } from "@/lib/dates";
import {
  formatDecimalHours,
  formatMinutes,
  formatReportDate,
  formatUsDate,
  groupTimeByJob,
  parseUsDate,
  monthSubtitle,
  toCsv,
  type DetailSort,
} from "@/lib/time-by-job";
import { decimalHoursToHM } from "@/lib/hours-format";
import type { DashboardUser, Employee } from "@/lib/types/employee";
import type { ClientOption, JobCodeOption } from "@/lib/types/reference-data";
import type { TimeEntry } from "@/lib/types/time-entry";

const FIRM = "GREEN CURTIS DALEY CPAS PLLC";
const NO_ACCESS = "You don't have access to Time by Job.";
const OFFICES = ["GCD", "MH"];

type Preset = "thisMonth" | "lastMonth" | "custom" | RangeKey;

const PRESETS: { id: Preset; label: string }[] = [
  { id: "thisMonth", label: "This Month" },
  { id: "lastMonth", label: "Last Month" },
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "week", label: "This Week" },
  { id: "thisPayPeriod", label: "This Pay Period" },
  { id: "lastPayPeriod", label: "Last Pay Period" },
  { id: "custom", label: "Custom" },
];

function rangeForPreset(preset: Preset): { dateFrom: string; dateTo: string } | null {
  if (preset === "custom") return null;
  if (preset === "thisMonth") return thisMonthRange();
  if (preset === "lastMonth") return lastMonthRange();
  const resolved = resolveRange(preset);
  return { dateFrom: resolved.dateFrom, dateTo: resolved.dateTo };
}

function chicagoStamp(when: Date): { date: string; time: string } {
  const date = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Chicago",
    month: "2-digit",
    day: "2-digit",
    year: "2-digit",
  }).format(when);
  const time = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Chicago",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(when);
  return { date, time };
}

function readLoadError(text: string): string {
  try {
    const parsed = JSON.parse(text) as { error?: unknown };
    if (typeof parsed.error === "string" && parsed.error.trim()) return parsed.error.trim();
  } catch {
    // HTML or empty body
  }
  return "Couldn't load time entries.";
}

function UsDateInput({
  value,
  ariaLabel,
  onChange,
}: {
  value: string;
  ariaLabel: string;
  onChange: (iso: string) => void;
}) {
  const [text, setText] = useState(() => formatUsDate(value));

  useEffect(() => {
    setText(formatUsDate(value));
  }, [value]);

  return (
    <span className={styles.dateWrap}>
      <input
        className={styles.dateText}
        value={text}
        inputMode="numeric"
        placeholder="MM-DD-YYYY"
        aria-label={ariaLabel}
        spellCheck={false}
        onChange={(event) => {
          const next = event.target.value;
          setText(next);
          const iso = parseUsDate(next);
          if (iso && iso !== value) onChange(iso);
        }}
        onBlur={() => setText(formatUsDate(value))}
      />
      <input
        className={styles.dateNative}
        type="date"
        tabIndex={-1}
        aria-label={`${ariaLabel} calendar`}
        value={value}
        onChange={(event) => {
          if (event.target.value) onChange(event.target.value);
        }}
      />
    </span>
  );
}

function downloadCsv(text: string) {
  const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "time-by-job.csv";
  a.click();
  URL.revokeObjectURL(url);
}

function officeMatches(selected: string[], office: string): boolean {
  if (selected.length === 0) return true;
  const norm = office.toUpperCase();
  return selected.some((item) => item.toUpperCase() === norm);
}

function selectionLabel(selected: string[], allLabel: string): string {
  return selected.length ? selected.join(", ") : allLabel;
}

function sortedNames(names: Set<string>): string[] {
  return [...names].sort((a, b) => a.localeCompare(b));
}

export function TimeByJobReport() {
  const provider = useMemo(() => getEntriesProvider(), []);
  const initial = useMemo(() => thisMonthRange(), []);
  const [me, setMe] = useState<DashboardUser | null>(null);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [clients, setClients] = useState<ClientOption[]>([]);
  const [jobCodes, setJobCodes] = useState<JobCodeOption[]>([]);
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [preset, setPreset] = useState<Preset>("thisMonth");
  const [dateFrom, setDateFrom] = useState(initial.dateFrom);
  const [dateTo, setDateTo] = useState(initial.dateTo);
  const [staffFilter, setStaffFilter] = useState<string[]>([]);
  const [officeFilter, setOfficeFilter] = useState<string[]>([]);
  const [clientFilter, setClientFilter] = useState<string[]>([]);
  const [jobCodeFilter, setJobCodeFilter] = useState<string[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [hideHeader, setHideHeader] = useState(false);
  const [zoom, setZoom] = useState(100);
  const [detailSort, setDetailSort] = useState<DetailSort>("date");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch("/api/me");
        if (!res.ok) {
          setLoadError("Please sign in to continue.");
          setLoading(false);
          return;
        }
        const user = (await res.json()) as DashboardUser;
        setMe(user);
        if (!user.can_view_time_by_job) setLoading(false);
      } catch (err) {
        setLoadError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (!me?.can_view_time_by_job) return;
    void (async () => {
      const [roster, clientRows, jobs] = await Promise.all([
        provider.fetchEmployees().catch(() => [] as Employee[]),
        provider.fetchClients().catch(() => [] as ClientOption[]),
        provider.fetchJobCodes().catch(() => [] as JobCodeOption[]),
      ]);
      setEmployees(roster);
      setClients(clientRows);
      setJobCodes(jobs);
    })();
  }, [provider, me]);

  useEffect(() => {
    if (!me?.can_view_time_by_job) return;
    let cancelled = false;
    setLoading(true);
    void (async () => {
      try {
        const q = new URLSearchParams({ from: dateFrom, to: dateTo });
        const res = await fetch(`/api/time-by-job?${q}`);
        if (!res.ok) throw new Error(readLoadError(await res.text()));
        const rows = (await res.json()) as TimeEntry[];
        if (cancelled) return;
        setEntries(rows);
        setUpdatedAt(new Date());
        setLoadError("");
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [me, dateFrom, dateTo, reloadKey]);

  const staffOptions = useMemo(() => {
    const names = new Set<string>();
    for (const employee of employees) {
      if (!employee.active || !employee.staff_name) continue;
      if (!officeMatches(officeFilter, employee.office)) continue;
      names.add(employee.staff_name);
    }
    for (const entry of entries) if (entry.staff_name) names.add(entry.staff_name);
    return sortedNames(names);
  }, [employees, entries, officeFilter]);

  const clientOptions = useMemo(() => {
    const names = new Set<string>();
    for (const client of clients) {
      if (!client.name) continue;
      if (!officeMatches(officeFilter, client.office)) continue;
      names.add(client.name);
    }
    for (const entry of entries) if (entry.client) names.add(entry.client);
    return sortedNames(names);
  }, [clients, entries, officeFilter]);

  const jobCodeOptions = useMemo(() => {
    const names = new Set<string>();
    for (const job of jobCodes) if (job.job_code) names.add(job.job_code);
    for (const entry of entries) if (entry.job_code) names.add(entry.job_code);
    return sortedNames(names);
  }, [jobCodes, entries]);

  const grouped = useMemo(
    () =>
      groupTimeByJob(entries, {
        clients: clientFilter,
        jobCodes: jobCodeFilter,
        staff: staffFilter,
        offices: officeFilter,
        search,
        detailSort,
      }),
    [entries, clientFilter, jobCodeFilter, staffFilter, officeFilter, search, detailSort],
  );

  function applyPreset(next: Preset) {
    setPreset(next);
    const range = rangeForPreset(next);
    if (!range) return;
    setDateFrom(range.dateFrom);
    setDateTo(range.dateTo);
  }

  function onSearch(event: FormEvent) {
    event.preventDefault();
    setSearch(searchInput.trim());
  }

  const stamp = updatedAt ? chicagoStamp(updatedAt) : null;

  if (!me && loading) {
    return (
      <div className={styles.wrap}>
        <p>Loading…</p>
      </div>
    );
  }

  if (me && !me.can_view_time_by_job) {
    return (
      <div className={styles.wrap}>
        <p>{NO_ACCESS}</p>
      </div>
    );
  }

  return (
    <div className={styles.wrap}>
      <div className={styles.chrome}>
        <div className={styles.toolRow}>
          <Link className={styles.homeLink} href="/">
            Hours dashboard
          </Link>
          <button type="button" className={styles.btn} onClick={() => setReloadKey((n) => n + 1)}>
            Refresh
          </button>
          <button type="button" className={styles.btn} onClick={() => window.print()}>
            Print
          </button>
          <button type="button" className={styles.btn} onClick={() => downloadCsv(toCsv(grouped))}>
            Excel
          </button>
          <button type="button" className={styles.btn} onClick={() => setHideHeader((v) => !v)}>
            {hideHeader ? "Show Header" : "Hide Header"}
          </button>
          <label className={styles.field}>
            Zoom
            <select value={zoom} onChange={(e) => setZoom(Number(e.target.value))} aria-label="Zoom">
              <option value={75}>75%</option>
              <option value={100}>100%</option>
              <option value={150}>150%</option>
            </select>
          </label>
        </div>

        <div className={styles.filterRow}>
          <label className={styles.field}>
            Dates
            <select
              className={styles.preset}
              value={preset}
              aria-label="Date preset"
              onChange={(e) => applyPreset(e.target.value as Preset)}
            >
              {PRESETS.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className={styles.field}>
            From
            <UsDateInput
              value={dateFrom}
              ariaLabel="From"
              onChange={(iso) => {
                setPreset("custom");
                setDateFrom(iso);
              }}
            />
          </label>
          <label className={styles.field}>
            To
            <UsDateInput
              value={dateTo}
              ariaLabel="To"
              onChange={(iso) => {
                setPreset("custom");
                setDateTo(iso);
              }}
            />
          </label>
          <label className={styles.field}>
            Employee
            <MultiCombobox
              className={styles.combo}
              values={staffFilter}
              options={staffOptions}
              onChange={setStaffFilter}
              placeholder="All"
              ariaLabel="Filter by employee"
            />
          </label>
          <label className={styles.field}>
            Client Office
            <MultiCombobox
              className={styles.combo}
              values={officeFilter}
              options={OFFICES}
              onChange={setOfficeFilter}
              placeholder="All"
              ariaLabel="Filter by client office"
            />
          </label>
          <label className={styles.field}>
            Client
            <MultiCombobox
              className={styles.combo}
              values={clientFilter}
              options={clientOptions}
              onChange={setClientFilter}
              placeholder="All"
              ariaLabel="Filter by client"
            />
          </label>
          <label className={styles.field}>
            Job Code
            <MultiCombobox
              className={styles.combo}
              values={jobCodeFilter}
              options={jobCodeOptions}
              onChange={setJobCodeFilter}
              placeholder="All"
              ariaLabel="Filter by job code"
            />
          </label>
          <button
            type="button"
            className={styles.btn}
            onClick={() => setDetailSort("date")}
            aria-pressed={detailSort === "date"}
          >
            Sort date
          </button>
          <button
            type="button"
            className={styles.btn}
            onClick={() => setDetailSort("duration")}
            aria-pressed={detailSort === "duration"}
          >
            Sort duration
          </button>
        </div>

        <form className={styles.searchRow} onSubmit={onSearch}>
          <button type="button" className={styles.showFilters} onClick={() => setShowFilters((v) => !v)}>
            {showFilters ? "Hide Filters" : "Show Filters"}
          </button>
          <label className={styles.field}>
            Look for
            <input
              value={searchInput}
              onChange={(e) => {
                const value = e.target.value;
                setSearchInput(value);
                if (!value.trim()) setSearch("");
              }}
              aria-label="Look for"
            />
          </label>
          <button type="submit" className={styles.btn}>
            Search
          </button>
          <button
            type="button"
            className={styles.btn}
            onClick={() => {
              setSearchInput("");
              setSearch("");
            }}
          >
            Reset
          </button>
        </form>
        {showFilters ? (
          <div className={styles.filterList}>
            <div>
              Dates: {formatReportDate(dateFrom)} – {formatReportDate(dateTo)}
            </div>
            <div>Employee: {selectionLabel(staffFilter, "All employees")}</div>
            <div>Client Office: {selectionLabel(officeFilter, "All client offices")}</div>
            <div>Client: {selectionLabel(clientFilter, "All clients")}</div>
            <div>Job Code: {selectionLabel(jobCodeFilter, "All job codes")}</div>
          </div>
        ) : null}
        {loadError ? <p className={styles.banner}>{loadError}</p> : null}
      </div>

      <div className={styles.sheet} style={{ fontSize: `${zoom}%` }}>
        {stamp ? (
          <div className={styles.stamp}>
            <div>{stamp.time}</div>
            <div>{stamp.date}</div>
          </div>
        ) : null}
        {hideHeader ? null : (
          <header className={styles.reportHead}>
            <h1>{FIRM}</h1>
            {officeFilter.length === 1 && officeFilter[0] === "MH" ? <p>MH</p> : null}
            <h2>Time by Job Detail</h2>
            <p>{monthSubtitle(dateFrom, dateTo)}</p>
          </header>
        )}
        {loading && entries.length === 0 ? <p>Loading…</p> : null}
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.colDate}>Date</th>
              <th className={styles.colName}>Name</th>
              <th className={styles.colDur}>Duration</th>
              <th className={styles.colDur}>Hours</th>
              <th className={styles.colNotes}>Notes</th>
            </tr>
          </thead>
          <tbody>
            {grouped.clients.map((client) => (
              <ClientBlock key={client.name || "(blank client)"} client={client} />
            ))}
            <tr className={styles.grand}>
              <td colSpan={2}>TOTAL</td>
              <td className={`${styles.colDur} ${styles.double}`}>{formatMinutes(grouped.totalMinutes)}</td>
              <td className={`${styles.colDur} ${styles.double}`}>{formatDecimalHours(grouped.totalHours)}</td>
              <td />
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ClientBlock({
  client,
}: {
  client: ReturnType<typeof groupTimeByJob>["clients"][number];
}) {
  return (
    <>
      <tr className={styles.clientBar}>
        <td colSpan={5}>{client.name}</td>
      </tr>
      {client.activities.map((activity) => (
        <ActivityBlock key={`${client.name}:${activity.name}`} activity={activity} />
      ))}
      <tr className={styles.clientTotal}>
        <td colSpan={2}>Total {client.name}</td>
        <td className={`${styles.colDur} ${styles.line}`}>{formatMinutes(client.totalMinutes)}</td>
        <td className={`${styles.colDur} ${styles.line}`}>{formatDecimalHours(client.totalHours)}</td>
        <td />
      </tr>
    </>
  );
}

function ActivityBlock({
  activity,
}: {
  activity: ReturnType<typeof groupTimeByJob>["clients"][number]["activities"][number];
}) {
  return (
    <>
      <tr className={styles.activityBar}>
        <td colSpan={5}>{activity.name}</td>
      </tr>
      {activity.entries.map((entry) => (
        <tr key={entry.id}>
          <td>{formatReportDate(entry.entry_date)}</td>
          <td className={styles.clip} title={entry.staff_name}>
            {entry.staff_name}
          </td>
          <td className={styles.colDur}>{decimalHoursToHM(entry.hours)}</td>
          <td className={styles.colDur}>{formatDecimalHours(entry.hours)}</td>
          <td className={styles.clip} title={entry.notes}>
            {entry.notes}
          </td>
        </tr>
      ))}
      <tr className={styles.subtotal}>
        <td colSpan={2}>Total {activity.name}</td>
        <td className={styles.colDur}>{formatMinutes(activity.totalMinutes)}</td>
        <td className={styles.colDur}>{formatDecimalHours(activity.totalHours)}</td>
        <td />
      </tr>
    </>
  );
}
