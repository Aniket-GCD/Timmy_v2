"use client";

import { useEffect, useState } from "react";
import { Combobox } from "@/components/Combobox";
import {
  displayHm,
  durationHoursFromTimes,
  formatHoursHM,
  parseHoursInput,
  parseTimeInput,
} from "@/lib/hours-format";
import { isWithinEditWindow } from "@/lib/pay-period";
import { reconcileTimeFields, type TimeFieldTouched } from "@/lib/time-field-sync";
import type { ClientOption, JobCodeOption } from "@/lib/types/reference-data";
import type { EntryWritePayload, TimeEntry } from "@/lib/types/time-entry";
import { ENTRY_ERRORS } from "@/lib/validate-entry";
import { OutOfWindowConfirm } from "./OutOfWindowConfirm";
import styles from "./EntryEditorModal.module.css";

export type EntryEditorDefaults = {
  entry_date: string;
  start_time?: string | null;
  end_time?: string | null;
  hours?: number;
  office?: string;
};

type Props = {
  open: boolean;
  mode: "create" | "edit";
  entry?: TimeEntry | null;
  defaults?: EntryEditorDefaults | null;
  staffName: string;
  viewerIsAdmin: boolean;
  /** Full firm client list; filtered in-modal by selected office. */
  clients: ClientOption[];
  jobCodes: JobCodeOption[];
  defaultOffice?: string;
  onClose: () => void;
  onSave: (payload: EntryWritePayload) => Promise<void>;
};

function normalizeOffice(raw: string | undefined | null, fallback = "GCD"): "GCD" | "MH" {
  const o = (raw || fallback).trim().toUpperCase();
  return o === "MH" ? "MH" : "GCD";
}

function emptyDraft(defaults?: EntryEditorDefaults | null): EntryWritePayload {
  return {
    client: "",
    job_code: "",
    notes: "",
    entry_date: defaults?.entry_date ?? "",
    start_time: defaults?.start_time ?? null,
    end_time: defaults?.end_time ?? null,
    hours: defaults?.hours ?? 1,
    billable: true,
    office: normalizeOffice(defaults?.office),
  };
}

function fromEntry(entry: TimeEntry): EntryWritePayload {
  return {
    client: entry.client,
    job_code: entry.job_code,
    notes: entry.notes,
    entry_date: entry.entry_date,
    start_time: entry.start_time,
    end_time: entry.end_time,
    hours: entry.hours,
    billable: entry.billable,
    office: normalizeOffice(entry.office),
  };
}

export function EntryEditorModal({
  open,
  mode,
  entry,
  defaults,
  staffName,
  viewerIsAdmin,
  clients,
  jobCodes,
  defaultOffice = "GCD",
  onClose,
  onSave,
}: Props) {
  const [draft, setDraft] = useState<EntryWritePayload>(emptyDraft(defaults));
  const [office, setOffice] = useState<"GCD" | "MH">(normalizeOffice(defaults?.office, defaultOffice));
  const [startHm, setStartHm] = useState("");
  const [endHm, setEndHm] = useState("");
  const [hoursHm, setHoursHm] = useState("1:00");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const next =
      mode === "edit" && entry
        ? fromEntry(entry)
        : emptyDraft({
            entry_date: defaults?.entry_date ?? "",
            start_time: defaults?.start_time,
            end_time: defaults?.end_time,
            hours: defaults?.hours,
            office: defaults?.office || defaultOffice,
          });
    const nextOffice = normalizeOffice(next.office, defaultOffice);
    setDraft({ ...next, office: nextOffice });
    setOffice(nextOffice);
    setStartHm(displayHm(next.start_time));
    setEndHm(displayHm(next.end_time));
    setHoursHm(formatHoursHM(next.hours));
    setError("");
    setSaving(false);
    setConfirmOpen(false);
  }, [open, mode, entry, defaults, defaultOffice]);

  if (!open) return null;

  const officeClients = clients.filter((c) => c.office.toUpperCase() === office);
  const clientNames = Array.from(new Set(officeClients.map((c) => c.name)));

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

  function onOfficeChange(next: "GCD" | "MH") {
    setOffice(next);
    setDraft((d) => {
      const stillValid = clients.some(
        (c) => c.name === d.client && c.office.toUpperCase() === next,
      );
      return {
        ...d,
        office: next,
        client: stillValid ? d.client : "",
      };
    });
  }

  async function doSave() {
    setSaving(true);
    setError("");
    try {
      const startTrim = startHm.trim();
      const endTrim = endHm.trim();
      if (Boolean(startTrim) !== Boolean(endTrim)) {
        setError(ENTRY_ERRORS.bothOrNeither);
        setSaving(false);
        return;
      }
      let start: string | null = null;
      let end: string | null = null;
      if (startTrim && endTrim) {
        start = parseTimeInput(startTrim);
        end = parseTimeInput(endTrim);
        if (!start || !end) {
          setError(ENTRY_ERRORS.badTime);
          setSaving(false);
          return;
        }
      }
      let hours = draft.hours;
      const fromTimes = durationHoursFromTimes(start, end);
      if (fromTimes != null) {
        if (fromTimes <= 0) {
          setError(ENTRY_ERRORS.endBeforeStart);
          setSaving(false);
          return;
        }
        hours = fromTimes;
      } else {
        const parsedHours = parseHoursInput(hoursHm);
        if (parsedHours == null || parsedHours <= 0) {
          setError(ENTRY_ERRORS.badDuration);
          setSaving(false);
          return;
        }
        hours = parsedHours;
      }
      if (!clientNames.includes(draft.client)) {
        setError(ENTRY_ERRORS.client);
        setSaving(false);
        return;
      }
      const payload: EntryWritePayload = {
        ...draft,
        office,
        start_time: start,
        end_time: end,
        hours: Math.round(hours * 100) / 100,
        billable: draft.job_code === "Admin" ? false : draft.billable,
      };
      await onSave(payload);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  function requestSave() {
    if (viewerIsAdmin && !isWithinEditWindow(draft.entry_date)) {
      setConfirmOpen(true);
      return;
    }
    void doSave();
  }

  return (
    <>
      <div className={styles.backdrop} role="presentation" onClick={onClose}>
        <div
          className={styles.dialog}
          role="dialog"
          aria-modal="true"
          aria-labelledby="entry-editor-title"
          onClick={(e) => e.stopPropagation()}
        >
          <h3 id="entry-editor-title" className={styles.title}>
            {mode === "create" ? "Add time entry" : "Edit time entry"}
          </h3>
          <p className={styles.staff}>Staff: {staffName}</p>

          <label className={styles.field}>
            <span>Office</span>
            <select
              className={styles.input}
              value={office}
              onChange={(e) => onOfficeChange(e.target.value === "MH" ? "MH" : "GCD")}
              aria-label="Office for this entry"
            >
              <option value="GCD">GCD</option>
              <option value="MH">MH</option>
            </select>
          </label>

          <label className={styles.field}>
            <span>Date</span>
            <input
              type="date"
              className={styles.input}
              value={draft.entry_date}
              onChange={(e) => setDraft((d) => ({ ...d, entry_date: e.target.value }))}
            />
          </label>

          <div className={styles.row}>
            <label className={styles.field}>
              <span>Start</span>
              <input
                className={styles.input}
                placeholder="HH:MM"
                value={startHm}
                onChange={(e) =>
                  applyTimeFields(
                    { startHm: e.target.value, endHm, hoursHm },
                    "start",
                  )
                }
              />
            </label>
            <label className={styles.field}>
              <span>End</span>
              <input
                className={styles.input}
                placeholder="HH:MM"
                value={endHm}
                onChange={(e) =>
                  applyTimeFields(
                    { startHm, endHm: e.target.value, hoursHm },
                    "end",
                  )
                }
              />
            </label>
            <label className={styles.field}>
              <span>Duration</span>
              <input
                className={styles.input}
                placeholder="H:MM"
                value={hoursHm}
                onChange={(e) =>
                  applyTimeFields(
                    { startHm, endHm, hoursHm: e.target.value },
                    "duration",
                  )
                }
              />
            </label>
          </div>
          <p className={styles.hint}>
            Leave Start and End blank to save duration only.{" "}
            <button
              type="button"
              className={styles.linkish}
              onClick={() => {
                setStartHm("");
                setEndHm("");
                setDraft((d) => ({ ...d, start_time: null, end_time: null }));
              }}
            >
              Clear times
            </button>
          </p>

          <label className={styles.field}>
            <span>Client</span>
            <Combobox
              value={draft.client}
              options={clientNames}
              onChange={(client) => setDraft((d) => ({ ...d, client }))}
              placeholder="Select client"
            />
          </label>

          <label className={styles.field}>
            <span>Job code</span>
            <Combobox
              value={draft.job_code}
              options={jobCodes.map((j) => j.job_code)}
              onChange={(job_code) =>
                setDraft((d) => ({
                  ...d,
                  job_code,
                  billable: job_code === "Admin" ? false : d.billable,
                }))
              }
              placeholder="Select job code"
            />
          </label>

          <label className={styles.field}>
            <span>Notes</span>
            <input
              className={styles.input}
              value={draft.notes}
              onChange={(e) => setDraft((d) => ({ ...d, notes: e.target.value }))}
            />
          </label>

          {draft.job_code !== "Admin" ? (
            <label className={styles.check}>
              <input
                type="checkbox"
                checked={draft.billable}
                onChange={(e) => setDraft((d) => ({ ...d, billable: e.target.checked }))}
              />
              Billable
            </label>
          ) : null}

          {error ? <p className={styles.error}>{error}</p> : null}

          <div className={styles.actions}>
            <button type="button" className={styles.cancel} onClick={onClose} disabled={saving}>
              Cancel
            </button>
            <button type="button" className={styles.save} onClick={requestSave} disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>

      <OutOfWindowConfirm
        open={confirmOpen}
        mode={mode}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => {
          setConfirmOpen(false);
          void doSave();
        }}
      />
    </>
  );
}
