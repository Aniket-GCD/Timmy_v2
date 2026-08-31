"use client";

import { useEffect, useMemo, useState } from "react";
import { Combobox } from "./Combobox";
import { StatusChip, type StatusKind } from "./StatusChip";
import { groupByClient } from "@/lib/aggregations";
import { formatDisplayDate } from "@/lib/dates";
import {
  durationHoursFromTimes,
  formatHoursHM,
  parseHoursInput,
  parseTimeInput,
} from "@/lib/hours-format";
import { isEditable } from "@/lib/pay-period";
import type { ClientOption, JobCodeOption } from "@/lib/types/reference-data";
import type { EntryWritePayload, TimeEntry } from "@/lib/types/time-entry";
import styles from "./DayEntriesTable.module.css";

type DraftRow = EntryWritePayload & {
  tempId: string;
  status: StatusKind;
  error?: string;
};

type Props = {
  dateISO: string;
  entries: TimeEntry[];
  staffName: string;
  clients: ClientOption[];
  jobCodes: JobCodeOption[];
  canEditDay: boolean;
  onCreate: (payload: EntryWritePayload) => Promise<void>;
  onUpdate: (id: number, payload: EntryWritePayload) => Promise<void>;
};

function toDraft(entry: TimeEntry): EntryWritePayload {
  return {
    client: entry.client,
    job_code: entry.job_code,
    notes: entry.notes,
    entry_date: entry.entry_date,
    start_time: entry.start_time,
    end_time: entry.end_time,
    hours: entry.hours,
    billable: entry.billable,
  };
}

export function DayEntriesTable({
  dateISO,
  entries,
  staffName,
  clients,
  jobCodes,
  canEditDay,
  onCreate,
  onUpdate,
}: Props) {
  const [showDetail, setShowDetail] = useState(true);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [drafts, setDrafts] = useState<DraftRow[]>([]);
  const [rowStatus, setRowStatus] = useState<Record<number, StatusKind>>({});

  useEffect(() => {
    setDrafts([]);
    setRowStatus({});
  }, [dateISO]);

  const clientNames = useMemo(() => clients.map((c) => c.name), [clients]);
  const jobCodeNames = useMemo(() => jobCodes.map((j) => j.job_code), [jobCodes]);

  const groups = useMemo(() => groupByClient(entries), [entries]);

  const dailyTotal = useMemo(() => {
    const draftHours = drafts.reduce((s, d) => s + d.hours, 0);
    return formatHoursHM(entries.reduce((s, e) => s + e.hours, 0) + draftHours);
  }, [entries, drafts]);

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

  const addDraft = () => {
    setDrafts((prev) => [
      {
        tempId: `draft-${Date.now()}`,
        client: clientNames[0] ?? "",
        job_code: jobCodeNames[0] ?? "",
        notes: "",
        entry_date: dateISO,
        start_time: null,
        end_time: null,
        hours: 0,
        billable: true,
        status: "draft",
      },
      ...prev,
    ]);
    setShowDetail(true);
    setCollapsed({});
  };

  const saveDraft = async (draft: DraftRow) => {
    setDrafts((prev) => prev.map((d) => (d.tempId === draft.tempId ? { ...d, status: "saving" } : d)));
    try {
      const { tempId, status, error, ...payload } = draft;
      void tempId;
      void status;
      void error;
      await onCreate(payload);
      setDrafts((prev) => prev.filter((d) => d.tempId !== draft.tempId));
    } catch (e) {
      setDrafts((prev) =>
        prev.map((d) =>
          d.tempId === draft.tempId ? { ...d, status: "error", error: String(e) } : d,
        ),
      );
    }
  };

  const saveExisting = async (entry: TimeEntry, payload: EntryWritePayload) => {
    setRowStatus((s) => ({ ...s, [entry.id]: "saving" }));
    try {
      await onUpdate(entry.id, payload);
      setRowStatus((s) => ({ ...s, [entry.id]: "submitted" }));
    } catch (e) {
      setRowStatus((s) => ({ ...s, [entry.id]: "error" }));
      alert(String(e));
    }
  };

  if (entries.length === 0 && drafts.length === 0) {
    return (
      <div className={styles.wrap}>
        <div className={styles.toolbar}>
          <div>
            <h2 className="section-title" style={{ marginBottom: 0 }}>Day detail</h2>
            <p className="muted" style={{ margin: "0.25rem 0 0", fontSize: "0.9rem" }}>{formatDisplayDate(dateISO)}</p>
          </div>
          {canEditDay && (
            <button type="button" className={styles.toggle} onClick={addDraft}>+ Add entry</button>
          )}
        </div>
        <div className="empty">No submitted hours for this day.</div>
      </div>
    );
  }

  return (
    <div className={styles.wrap}>
      <div className={styles.toolbar}>
        <div>
          <h2 className="section-title" style={{ marginBottom: 0 }}>Day detail</h2>
          <p className="muted" style={{ margin: "0.25rem 0 0", fontSize: "0.9rem" }}>{formatDisplayDate(dateISO)}</p>
        </div>
        <div className={styles.actions}>
          {canEditDay && (
            <button type="button" className={styles.toggle} onClick={addDraft}>+ Add entry</button>
          )}
          <button type="button" className={styles.toggle} onClick={toggleDetail} aria-pressed={showDetail}>
            {showDetail ? "Hide detail" : "Show detail"}
          </button>
        </div>
      </div>

      <div className={styles.tableScroll}>
        <table className={styles.table}>
          <thead>
            <tr>
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
              <th />
            </tr>
          </thead>
          <tbody>
            {drafts.map((draft) => (
              <EditableRow
                key={draft.tempId}
                payload={draft}
                showDetail={showDetail}
                editable
                clientNames={clientNames}
                jobCodeNames={jobCodeNames}
                status={draft.status}
                error={draft.error}
                onChange={(patch) =>
                  setDrafts((p) => p.map((d) => (d.tempId === draft.tempId ? { ...d, ...patch } : d)))
                }
                onSave={(payload) => void saveDraft({ ...draft, ...payload })}
                onCancel={() => setDrafts((p) => p.filter((d) => d.tempId !== draft.tempId))}
              />
            ))}
            {groups.map((group) => (
              <GroupBlock
                key={group.client}
                group={group}
                collapsed={Boolean(collapsed[group.client])}
                showDetail={showDetail}
                staffName={staffName}
                clientNames={clientNames}
                jobCodeNames={jobCodeNames}
                rowStatus={rowStatus}
                onToggle={() => setCollapsed((p) => ({ ...p, [group.client]: !p[group.client] }))}
                onSaveExisting={saveExisting}
              />
            ))}
          </tbody>
          <tfoot>
            <tr className={styles.footer}>
              <td colSpan={showDetail ? 5 : 3}><strong>Daily total</strong></td>
              <td className={styles.num}><strong>{dailyTotal}</strong></td>
              <td colSpan={2} />
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

function GroupBlock({
  group,
  collapsed,
  showDetail,
  staffName,
  clientNames,
  jobCodeNames,
  rowStatus,
  onToggle,
  onSaveExisting,
}: {
  group: ReturnType<typeof groupByClient>[0];
  collapsed: boolean;
  showDetail: boolean;
  staffName: string;
  clientNames: string[];
  jobCodeNames: string[];
  rowStatus: Record<number, StatusKind>;
  onToggle: () => void;
  onSaveExisting: (entry: TimeEntry, payload: EntryWritePayload) => Promise<void>;
}) {
  return (
    <>
      <tr className={styles.groupHeader}>
        <td colSpan={showDetail ? 9 : 7}>
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
        group.entries.map((entry) => {
          const editable = isEditable(entry.entry_date, staffName);
          const status: StatusKind = editable ? (rowStatus[entry.id] ?? "submitted") : "locked";
          return (
            <EditableRow
              key={entry.id}
              payload={toDraft(entry)}
              showDetail={showDetail}
              editable={editable}
              clientNames={clientNames}
              jobCodeNames={jobCodeNames}
              status={status}
              onChange={() => {}}
              onSave={(payload) => onSaveExisting(entry, payload)}
            />
          );
        })}
      {!collapsed && (
        <tr className={styles.subtotal}>
          <td colSpan={showDetail ? 5 : 3} className={styles.indent}>Subtotal — {group.client}</td>
          <td className={styles.num}>{formatHoursHM(group.subtotal)}</td>
          <td colSpan={3} />
        </tr>
      )}
    </>
  );
}

function displayTime(value: string | null): string {
  return value ? value.slice(0, 5) : "";
}

function EditableRow({
  payload,
  showDetail,
  editable,
  clientNames,
  jobCodeNames,
  status,
  error,
  onChange,
  onSave,
  onCancel,
}: {
  payload: EntryWritePayload;
  showDetail: boolean;
  editable: boolean;
  clientNames: string[];
  jobCodeNames: string[];
  status: StatusKind;
  error?: string;
  onChange: (patch: Partial<EntryWritePayload>) => void;
  onSave: (payload: EntryWritePayload) => void | Promise<void>;
  onCancel?: () => void;
}) {
  const [local, setLocal] = useState(payload);
  // Free-text while typing; parse to HH:MM:SS only on blur/save.
  const [startText, setStartText] = useState(displayTime(payload.start_time));
  const [endText, setEndText] = useState(displayTime(payload.end_time));
  const [hoursText, setHoursText] = useState(formatHoursHM(payload.hours));

  useEffect(() => {
    setLocal(payload);
    setStartText(displayTime(payload.start_time));
    setEndText(displayTime(payload.end_time));
    setHoursText(formatHoursHM(payload.hours));
  }, [
    payload.client,
    payload.job_code,
    payload.notes,
    payload.entry_date,
    payload.start_time,
    payload.end_time,
    payload.hours,
    payload.billable,
  ]);

  const parsedStart = parseTimeInput(startText) ?? local.start_time;
  const parsedEnd = parseTimeInput(endText) ?? local.end_time;
  const duration = durationHoursFromTimes(parsedStart, parsedEnd) ?? local.hours;

  const patch = (p: Partial<EntryWritePayload>) => {
    setLocal((prev) => ({ ...prev, ...p }));
    onChange(p);
  };

  const commitTimes = () => {
    const start = startText.trim() ? parseTimeInput(startText) : null;
    const end = endText.trim() ? parseTimeInput(endText) : null;
    if (startText.trim() && !start) return;
    if (endText.trim() && !end) return;
    const fromTimes = durationHoursFromTimes(start, end);
    const nextHours = fromTimes ?? local.hours;
    setStartText(displayTime(start));
    setEndText(displayTime(end));
    setHoursText(formatHoursHM(nextHours));
    patch({ start_time: start, end_time: end, hours: nextHours });
  };

  const buildPayload = (): EntryWritePayload => {
    const start = startText.trim() ? parseTimeInput(startText) : null;
    const end = endText.trim() ? parseTimeInput(endText) : null;
    const fromTimes = durationHoursFromTimes(start, end);
    const hours = fromTimes ?? parseHoursInput(hoursText) ?? local.hours;
    return {
      ...local,
      start_time: start,
      end_time: end,
      hours,
      entry_date: local.entry_date,
    };
  };

  if (!editable) {
    return (
      <tr className={styles.row}>
        <td className={styles.indent}>{local.client}</td>
        <td>{local.job_code}</td>
        <td>{local.notes}</td>
        {showDetail && (
          <>
            <td className={styles.num}>{displayTime(local.start_time) || "—"}</td>
            <td className={styles.num}>{displayTime(local.end_time) || "—"}</td>
            <td className={styles.num}>{formatHoursHM(duration)}</td>
          </>
        )}
        {!showDetail && <td className={styles.num}>{formatHoursHM(duration)}</td>}
        <td><StatusChip status="locked" /></td>
        <td />
      </tr>
    );
  }

  return (
    <tr className={styles.row}>
      <td className={styles.indent}>
        <Combobox value={local.client} options={clientNames} onChange={(v) => patch({ client: v })} />
      </td>
      <td>
        <Combobox value={local.job_code} options={jobCodeNames} onChange={(v) => patch({ job_code: v, billable: v !== "Admin" })} />
      </td>
      <td>
        <input
          className={styles.cellInput}
          value={local.notes}
          onChange={(e) => patch({ notes: e.target.value })}
        />
      </td>
      {showDetail && (
        <>
          <td className={styles.num}>
            <input
              className={styles.cellInput}
              value={startText}
              onChange={(e) => setStartText(e.target.value)}
              onBlur={commitTimes}
              placeholder="9:00"
            />
          </td>
          <td className={styles.num}>
            <input
              className={styles.cellInput}
              value={endText}
              onChange={(e) => setEndText(e.target.value)}
              onBlur={commitTimes}
              placeholder="17:00"
            />
          </td>
          <td className={styles.num}>{formatHoursHM(duration)}</td>
        </>
      )}
      {!showDetail && (
        <td className={styles.num}>
          <input
            className={styles.cellInput}
            value={hoursText}
            onChange={(e) => setHoursText(e.target.value)}
            onBlur={() => {
              const h = parseHoursInput(hoursText);
              if (h != null) {
                setHoursText(formatHoursHM(h));
                patch({ hours: h });
              }
            }}
          />
        </td>
      )}
      <td>
        <StatusChip status={status} />
        {error && <div className={styles.error}>{error}</div>}
      </td>
      <td className={styles.actions}>
        <button type="button" className={styles.saveBtn} onClick={() => void onSave(buildPayload())}>
          Save
        </button>
        {onCancel && (
          <button type="button" className={styles.cancelBtn} onClick={onCancel}>Cancel</button>
        )}
      </td>
    </tr>
  );
}
