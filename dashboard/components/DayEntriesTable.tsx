"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Combobox } from "@/components/Combobox";
import { groupByClient } from "@/lib/aggregations";
import { formatDisplayDate } from "@/lib/dates";
import {
  displayHm,
  durationHoursFromTimes,
  formatHoursHM,
  parseHoursInput,
  parseTimeInput,
} from "@/lib/hours-format";
import { clientLabels, formatClientLabelParts, parseClientLabel } from "@/lib/client-option-label";
import { canDashboardMutateEntry, isWithinEditWindow } from "@/lib/pay-period";
import { reconcileTimeFields, type TimeFieldTouched } from "@/lib/time-field-sync";
import type { ClientOption, JobCodeOption } from "@/lib/types/reference-data";
import type { EntryWritePayload, TimeEntry } from "@/lib/types/time-entry";
import { ENTRY_ERRORS } from "@/lib/validate-entry";
import { OutOfWindowConfirm } from "./OutOfWindowConfirm";
import { StatusChip } from "./StatusChip";
import styles from "./DayEntriesTable.module.css";

type Props = {
  entries: TimeEntry[];
  multiDay: boolean;
  viewerStaffName: string;
  viewerIsAdmin?: boolean;
  clients: ClientOption[];
  jobCodes: JobCodeOption[];
  onSave: (id: number, payload: EntryWritePayload) => Promise<void>;
};

function displayTime(value: string | null): string {
  return value ? value.slice(0, 5) : "—";
}

function draftFromEntry(entry: TimeEntry): EntryWritePayload {
  return {
    client: entry.client,
    job_code: entry.job_code,
    notes: entry.notes,
    entry_date: entry.entry_date,
    start_time: entry.start_time,
    end_time: entry.end_time,
    hours: entry.hours,
    billable: entry.billable,
    office: entry.office,
  };
}

export function DayEntriesTable({
  entries,
  multiDay,
  viewerStaffName,
  viewerIsAdmin = false,
  clients,
  jobCodes,
  onSave,
}: Props) {
  const [showDetail, setShowDetail] = useState(true);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const groups = useMemo(() => groupByClient(entries), [entries]);
  const dailyTotal = useMemo(
    () => formatHoursHM(entries.reduce((s, e) => s + e.hours, 0)),
    [entries],
  );

  const showDate = multiDay;
  const colCount =
    (showDate ? 1 : 0) +
    3 +
    (showDetail ? 3 : 1) +
    1;

  const toggleDetail = () => {
    setShowDetail((v) => {
      const next = !v;
      if (!next) {
        const allCollapsed: Record<string, boolean> = {};
        for (const g of groups) allCollapsed[g.client] = true;
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
          <p className="muted" style={{ margin: 0, fontSize: "0.9rem" }}>
            {entries.length} entries
          </p>
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
        <div className="empty">No submitted hours for this selection.</div>
      ) : (
        <div className={styles.tableScroll}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th className={styles.clientCol}>Client</th>
                <th>Job Code</th>
                <th>Notes</th>
                {showDate && <th>Date</th>}
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
                const isCollapsed = Boolean(collapsed[group.client]);
                return (
                  <ClientGroupBlock
                    key={group.client}
                    group={group}
                    collapsed={isCollapsed}
                    showDetail={showDetail}
                    showDate={showDate}
                    colCount={colCount}
                    viewerStaffName={viewerStaffName}
                    viewerIsAdmin={viewerIsAdmin}
                    clients={clients}
                    jobCodes={jobCodes}
                    onSave={onSave}
                    onToggle={() =>
                      setCollapsed((p) => ({ ...p, [group.client]: !p[group.client] }))
                    }
                  />
                );
              })}
            </tbody>
            <tfoot>
              <tr className={styles.footer}>
                <td colSpan={colCount - 2}>
                  <strong>Total</strong>
                </td>
                <td className={styles.num}>
                  <strong>{dailyTotal}</strong>
                </td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  );
}

function ClientGroupBlock({
  group,
  collapsed,
  showDetail,
  showDate,
  colCount,
  viewerStaffName,
  viewerIsAdmin,
  clients,
  jobCodes,
  onSave,
  onToggle,
}: {
  group: ReturnType<typeof groupByClient>[0];
  collapsed: boolean;
  showDetail: boolean;
  showDate: boolean;
  colCount: number;
  viewerStaffName: string;
  viewerIsAdmin: boolean;
  clients: ClientOption[];
  jobCodes: JobCodeOption[];
  onSave: (id: number, payload: EntryWritePayload) => Promise<void>;
  onToggle: () => void;
}) {
  return (
    <>
      <tr className={styles.groupHeader}>
        <td colSpan={colCount}>
          <button type="button" className={styles.groupBtn} onClick={onToggle}>
            <span className={styles.chevron}>{collapsed ? "▸" : "▾"}</span>
            <span className={styles.groupName}>{group.client}</span>
            <span className={styles.groupMeta}>
              {group.entries.length} entries · {formatHoursHM(group.subtotal)}
            </span>
          </button>
        </td>
      </tr>
      {!collapsed &&
        group.entries.map((entry) => (
          <EntryRow
            key={entry.id}
            entry={entry}
            showDetail={showDetail}
            showDate={showDate}
            viewerStaffName={viewerStaffName}
            viewerIsAdmin={viewerIsAdmin}
            clients={clients}
            jobCodes={jobCodes}
            onSave={onSave}
          />
        ))}
      {!collapsed && showDetail && (
        <tr className={styles.subtotal}>
          <td colSpan={(showDate ? 1 : 0) + 3} className={styles.indent}>
            Subtotal — {group.client}
          </td>
          <td className={styles.num}>{formatHoursHM(group.subtotal)}</td>
          <td colSpan={2} />
        </tr>
      )}
      {!collapsed && !showDetail && (
        <tr className={styles.subtotal}>
          <td colSpan={3} className={styles.indent}>
            Subtotal — {group.client}
          </td>
          {showDate && <td />}
          <td className={styles.num}>{formatHoursHM(group.subtotal)}</td>
          <td />
        </tr>
      )}
    </>
  );
}

function EntryRow({
  entry,
  showDetail,
  showDate,
  viewerStaffName,
  viewerIsAdmin,
  clients,
  jobCodes,
  onSave,
}: {
  entry: TimeEntry;
  showDetail: boolean;
  showDate: boolean;
  viewerStaffName: string;
  viewerIsAdmin: boolean;
  clients: ClientOption[];
  jobCodes: JobCodeOption[];
  onSave: (id: number, payload: EntryWritePayload) => Promise<void>;
}) {
  const editable = canDashboardMutateEntry({
    entryDate: entry.entry_date,
    actorIsAdmin: viewerIsAdmin,
    actorStaffName: viewerStaffName,
    entryStaffName: entry.staff_name,
  });
  const entryStatus = entry.status ?? "submitted";
  const [editing, setEditing] = useState(false);
  const editingRef = useRef(false);
  editingRef.current = editing;
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [draft, setDraft] = useState<EntryWritePayload>(() => draftFromEntry(entry));
  const [startHm, setStartHm] = useState(() => displayHm(entry.start_time));
  const [endHm, setEndHm] = useState(() => displayHm(entry.end_time));
  const [hoursHm, setHoursHm] = useState(() => formatHoursHM(entry.hours));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function applyEntryFields(next: TimeEntry) {
    setDraft(draftFromEntry(next));
    setStartHm(displayHm(next.start_time));
    setEndHm(displayHm(next.end_time));
    setHoursHm(formatHoursHM(next.hours));
  }

  useEffect(() => {
    // Poll refresh must not cancel an in-progress edit of the same row.
    if (editingRef.current) return;
    applyEntryFields(entry);
    setConfirmOpen(false);
    setError("");
  }, [entry]);

  function applyTimeFields(
    next: { startHm: string; endHm: string; hoursHm: string },
    touched: TimeFieldTouched,
  ) {
    const r = reconcileTimeFields({ ...next, touched });
    setStartHm(r.startHm);
    setEndHm(r.endHm);
    setHoursHm(r.hoursHm);
    const start = r.startHm.trim() ? parseTimeInput(r.startHm) : null;
    const end = r.endHm.trim() ? parseTimeInput(r.endHm) : null;
    setDraft((d) => ({
      ...d,
      start_time: start,
      end_time: end,
      hours: r.hours != null && r.hours > 0 ? r.hours : d.hours,
    }));
  }

  function buildPayload(): EntryWritePayload | null {
    const startTrim = startHm.trim();
    const endTrim = endHm.trim();
    if (Boolean(startTrim) !== Boolean(endTrim)) {
      setError(ENTRY_ERRORS.bothOrNeither);
      return null;
    }
    let start: string | null = null;
    let end: string | null = null;
    if (startTrim && endTrim) {
      start = parseTimeInput(startTrim);
      end = parseTimeInput(endTrim);
      if (!start || !end) {
        setError(ENTRY_ERRORS.badTime);
        return null;
      }
    }
    let hours = draft.hours;
    const fromTimes = durationHoursFromTimes(start, end);
    if (fromTimes != null) {
      if (fromTimes <= 0) {
        setError(ENTRY_ERRORS.endBeforeStart);
        return null;
      }
      hours = fromTimes;
    } else {
      const parsedHours = parseHoursInput(hoursHm);
      if (parsedHours == null || parsedHours <= 0) {
        setError(ENTRY_ERRORS.badDuration);
        return null;
      }
      hours = parsedHours;
    }
    return {
      ...draft,
      start_time: start,
      end_time: end,
      hours: Math.round(hours * 100) / 100,
    };
  }

  async function save() {
    const payload = buildPayload();
    if (!payload) return;
    setSaving(true);
    setError("");
    try {
      await onSave(entry.id, payload);
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  function requestEdit() {
    applyEntryFields(entry);
    setError("");
    if (viewerIsAdmin && !isWithinEditWindow(entry.entry_date)) {
      setConfirmOpen(true);
      return;
    }
    setEditing(true);
  }

  function requestSave() {
    const dateForWindow = draft.entry_date;
    if (viewerIsAdmin && !isWithinEditWindow(dateForWindow)) {
      setConfirmOpen(true);
      return;
    }
    void save();
  }

  const chipStatus = saving
    ? "saving"
    : error
      ? "error"
      : !isWithinEditWindow(entry.entry_date) && !viewerIsAdmin
        ? "locked"
        : entryStatus;

  if (!editing) {
    return (
      <>
        <tr className={styles.row}>
          <td className={styles.indent}>
            {entry.client}
            {editable ? (
              <button
                type="button"
                className={styles.toggle}
                style={{ marginLeft: 8, padding: "0.15rem 0.5rem", fontSize: "0.75rem" }}
                onClick={requestEdit}
              >
                Edit
              </button>
            ) : (
              <button
                type="button"
                className={styles.toggle}
                style={{ marginLeft: 8, padding: "0.15rem 0.5rem", fontSize: "0.75rem", opacity: 0.5 }}
                disabled
                title="Outside the pay-period edit window"
              >
                Edit
              </button>
            )}
          </td>
          <td>{entry.job_code}</td>
          <td>{entry.notes}</td>
          {showDate && <td>{formatDisplayDate(entry.entry_date)}</td>}
          {showDetail && (
            <>
              <td className={styles.num}>{displayTime(entry.start_time)}</td>
              <td className={styles.num}>{displayTime(entry.end_time)}</td>
              <td className={styles.num}>{formatHoursHM(entry.hours)}</td>
            </>
          )}
          {!showDetail && <td className={styles.num}>{formatHoursHM(entry.hours)}</td>}
          <td>
            <StatusChip status={chipStatus} />
          </td>
        </tr>
        <OutOfWindowConfirm
          open={confirmOpen}
          mode="edit"
          onCancel={() => setConfirmOpen(false)}
          onConfirm={() => {
            setConfirmOpen(false);
            setEditing(true);
          }}
        />
      </>
    );
  }

  const labeledOptions = useMemo(() => clientLabels(clients), [clients]);
  const clientDisplay = draft.client
    ? formatClientLabelParts(draft.office || entry.office || "GCD", draft.client)
    : "";

  return (
    <tr className={styles.row}>
      <td className={styles.indent}>
        <Combobox
          value={clientDisplay}
          options={labeledOptions}
          onChange={(label) => {
            const parsed = parseClientLabel(label);
            setDraft((d) => ({
              ...d,
              client: parsed.name,
              office: parsed.office,
            }));
          }}
        />
        {error ? <div className={styles.error}>{error}</div> : null}
      </td>
      <td>
        <Combobox
          value={draft.job_code}
          options={jobCodes.map((j) => j.job_code)}
          onChange={(job_code) => setDraft((d) => ({ ...d, job_code }))}
        />
      </td>
      <td>
        <input
          className={styles.cellInput}
          value={draft.notes}
          onChange={(e) => setDraft((d) => ({ ...d, notes: e.target.value }))}
        />
      </td>
      {showDate && (
        <td>
          <input
            className={styles.cellInput}
            type="date"
            value={draft.entry_date}
            onChange={(e) => setDraft((d) => ({ ...d, entry_date: e.target.value }))}
          />
        </td>
      )}
      {showDetail && (
        <>
          <td>
            <input
              className={styles.cellInput}
              value={startHm}
              placeholder="HH:MM"
              onChange={(e) =>
                applyTimeFields(
                  { startHm: e.target.value, endHm, hoursHm },
                  "start",
                )
              }
            />
          </td>
          <td>
            <input
              className={styles.cellInput}
              value={endHm}
              placeholder="HH:MM"
              onChange={(e) =>
                applyTimeFields(
                  { startHm, endHm: e.target.value, hoursHm },
                  "end",
                )
              }
            />
          </td>
          <td>
            <input
              className={styles.cellInput}
              value={hoursHm}
              placeholder="H:MM"
              onChange={(e) =>
                applyTimeFields(
                  { startHm, endHm, hoursHm: e.target.value },
                  "duration",
                )
              }
            />
          </td>
        </>
      )}
      {!showDetail && (
        <td>
          <input
            className={styles.cellInput}
            value={hoursHm}
            placeholder="H:MM"
            onChange={(e) =>
              applyTimeFields(
                { startHm, endHm, hoursHm: e.target.value },
                "duration",
              )
            }
          />
        </td>
      )}
      <td>
        <button type="button" className={styles.saveBtn} disabled={saving} onClick={requestSave}>
          {saving ? "…" : "Save"}
        </button>{" "}
        <button
          type="button"
          className={styles.cancelBtn}
          onClick={() => {
            applyEntryFields(entry);
            setEditing(false);
            setError("");
          }}
        >
          Cancel
        </button>
        <OutOfWindowConfirm
          open={confirmOpen}
          mode="edit"
          onCancel={() => setConfirmOpen(false)}
          onConfirm={() => {
            setConfirmOpen(false);
            if (editing) void save();
            else setEditing(true);
          }}
        />
      </td>
    </tr>
  );
}
