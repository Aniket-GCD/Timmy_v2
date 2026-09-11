"use client";

import { useEffect, useState } from "react";
import { Combobox } from "@/components/Combobox";
import { durationHoursFromTimes, parseTimeInput } from "@/lib/hours-format";
import { isWithinEditWindow } from "@/lib/pay-period";
import type { ClientOption, JobCodeOption } from "@/lib/types/reference-data";
import type { EntryWritePayload, TimeEntry } from "@/lib/types/time-entry";
import { OutOfWindowConfirm } from "./OutOfWindowConfirm";
import styles from "./EntryEditorModal.module.css";

export type EntryEditorDefaults = {
  entry_date: string;
  start_time?: string | null;
  end_time?: string | null;
  hours?: number;
};

type Props = {
  open: boolean;
  mode: "create" | "edit";
  entry?: TimeEntry | null;
  defaults?: EntryEditorDefaults | null;
  staffName: string;
  viewerIsAdmin: boolean;
  clients: ClientOption[];
  jobCodes: JobCodeOption[];
  onClose: () => void;
  onSave: (payload: EntryWritePayload) => Promise<void>;
};

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
  };
}

function displayHm(value: string | null): string {
  return value ? value.slice(0, 5) : "";
}

function toTimeOrNull(hm: string): string | null {
  const t = hm.trim();
  if (!t) return null;
  const parsed = parseTimeInput(t);
  return parsed ?? `${t}:00`.slice(0, 8);
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
  onClose,
  onSave,
}: Props) {
  const [draft, setDraft] = useState<EntryWritePayload>(emptyDraft(defaults));
  const [startHm, setStartHm] = useState("");
  const [endHm, setEndHm] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const next = mode === "edit" && entry ? fromEntry(entry) : emptyDraft(defaults);
    setDraft(next);
    setStartHm(displayHm(next.start_time));
    setEndHm(displayHm(next.end_time));
    setError("");
    setSaving(false);
    setConfirmOpen(false);
  }, [open, mode, entry, defaults]);

  if (!open) return null;

  function syncTimes(nextStart: string, nextEnd: string) {
    setStartHm(nextStart);
    setEndHm(nextEnd);
    const start = toTimeOrNull(nextStart);
    const end = toTimeOrNull(nextEnd);
    setDraft((d) => {
      const hours =
        start && end ? durationHoursFromTimes(start, end) ?? d.hours : d.hours;
      return { ...d, start_time: start, end_time: end, hours };
    });
  }

  async function doSave() {
    setSaving(true);
    setError("");
    try {
      const payload: EntryWritePayload = {
        ...draft,
        start_time: toTimeOrNull(startHm),
        end_time: toTimeOrNull(endHm),
        billable: draft.job_code === "Admin" ? false : draft.billable,
      };
      if (payload.start_time && payload.end_time) {
        const fromTimes = durationHoursFromTimes(payload.start_time, payload.end_time);
        if (fromTimes != null) payload.hours = fromTimes;
      }
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
                onChange={(e) => syncTimes(e.target.value, endHm)}
              />
            </label>
            <label className={styles.field}>
              <span>End</span>
              <input
                className={styles.input}
                placeholder="HH:MM"
                value={endHm}
                onChange={(e) => syncTimes(startHm, e.target.value)}
              />
            </label>
            <label className={styles.field}>
              <span>Hours</span>
              <input
                type="number"
                step="0.25"
                className={styles.input}
                value={draft.hours}
                onChange={(e) => setDraft((d) => ({ ...d, hours: Number(e.target.value) }))}
              />
            </label>
          </div>

          <label className={styles.field}>
            <span>Client</span>
            <Combobox
              value={draft.client}
              options={clients.map((c) => c.name)}
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
