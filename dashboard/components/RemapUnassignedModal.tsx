"use client";

import { useEffect, useMemo, useState } from "react";
import { Combobox } from "@/components/Combobox";
import type { ClientOption } from "@/lib/types/reference-data";
import type { TimeEntry } from "@/lib/types/time-entry";
import styles from "./EntryEditorModal.module.css";

type Props = {
  open: boolean;
  clients: ClientOption[];
  defaultOffice: string;
  onClose: () => void;
  onDone: () => void;
};

export function RemapUnassignedModal({
  open,
  clients,
  defaultOffice,
  onClose,
  onDone,
}: Props) {
  const [office, setOffice] = useState(defaultOffice || "GCD");
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [toClient, setToClient] = useState("");
  const [notesContains, setNotesContains] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const targetOptions = useMemo(() => {
    const names = clients
      .filter((c) => c.office.toUpperCase() === office.toUpperCase())
      .map((c) => c.name)
      .filter((n) => n.toLowerCase() !== "unassigned");
    return Array.from(new Set(names)).sort((a, b) => a.localeCompare(b));
  }, [clients, office]);

  useEffect(() => {
    if (!open) return;
    setOffice(defaultOffice === "MH" ? "MH" : "GCD");
    setSelected(new Set());
    setToClient("");
    setNotesContains("");
    setError("");
    setMessage("");
  }, [open, defaultOffice]);

  useEffect(() => {
    if (!open) return;
    void (async () => {
      setLoading(true);
      setError("");
      try {
        const q = new URLSearchParams({
          office,
          client: "Unassigned",
        });
        const res = await fetch(`/api/entries/unassigned?${q}`);
        if (!res.ok) throw new Error(await res.text());
        const rows = (await res.json()) as TimeEntry[];
        setEntries(rows);
        setSelected(new Set(rows.map((r) => r.id)));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setEntries([]);
      } finally {
        setLoading(false);
      }
    })();
  }, [open, office]);

  const visibleEntries = useMemo(() => {
    const needle = notesContains.trim().toLowerCase();
    if (!needle) return entries;
    return entries.filter((e) => (e.notes || "").toLowerCase().includes(needle));
  }, [entries, notesContains]);

  if (!open) return null;

  async function applyRemap() {
    if (!toClient.trim()) {
      setError("Pick the real client name.");
      return;
    }
    const ids = [...selected];
    if (!ids.length) {
      setError("Select at least one entry.");
      return;
    }
    setLoading(true);
    setError("");
    setMessage("");
    try {
      const res = await fetch("/api/entries/remap-client", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          office,
          to_client: toClient.trim(),
          entry_ids: ids,
        }),
      });
      const data = (await res.json()) as { updated?: number; error?: string };
      if (!res.ok) throw new Error(data.error || "Remap failed");
      setMessage(`Updated ${data.updated ?? 0} entries.`);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={styles.backdrop} role="presentation" onClick={onClose}>
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="remap-title"
        onClick={(e) => e.stopPropagation()}
        style={{ width: "min(36rem, 100%)" }}
      >
        <h3 id="remap-title" className={styles.title}>
          Remap Unassigned entries
        </h3>
        <p className={styles.staff}>
          After QBO/CSV adds the real client, move placeholder Unassigned rows to that name.
        </p>

        <label className={styles.field}>
          <span>Office</span>
          <select
            className={styles.input}
            value={office}
            onChange={(e) => setOffice(e.target.value)}
          >
            <option value="GCD">GCD</option>
            <option value="MH">MH</option>
          </select>
        </label>

        <label className={styles.field}>
          <span>Notes contain (optional filter)</span>
          <input
            className={styles.input}
            value={notesContains}
            onChange={(e) => setNotesContains(e.target.value)}
            placeholder="Spoken client name fragment"
          />
        </label>

        <label className={styles.field}>
          <span>Map to client</span>
          <Combobox
            value={toClient}
            options={targetOptions}
            onChange={setToClient}
            placeholder="Select real client"
          />
        </label>

        {loading ? <p className={styles.staff}>Loading…</p> : null}
        {error ? <p className={styles.error}>{error}</p> : null}
        {message ? <p className={styles.staff}>{message}</p> : null}

        <div style={{ maxHeight: "12rem", overflow: "auto", marginBottom: "0.75rem" }}>
          {visibleEntries.length === 0 && !loading ? (
            <p className={styles.staff}>No Unassigned entries for this office/filter.</p>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {visibleEntries.map((e) => (
                <li key={e.id} style={{ marginBottom: "0.35rem" }}>
                  <label className={styles.check}>
                    <input
                      type="checkbox"
                      checked={selected.has(e.id)}
                      onChange={(ev) => {
                        setSelected((prev) => {
                          const next = new Set(prev);
                          if (ev.target.checked) next.add(e.id);
                          else next.delete(e.id);
                          return next;
                        });
                      }}
                    />
                    <span>
                      #{e.id} {e.staff_name} · {e.entry_date} · {e.hours}h —{" "}
                      {(e.notes || "").slice(0, 80)}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className={styles.actions}>
          <button type="button" className={styles.cancel} onClick={onClose} disabled={loading}>
            Close
          </button>
          <button type="button" className={styles.save} onClick={() => void applyRemap()} disabled={loading}>
            {loading ? "Working…" : "Remap selected"}
          </button>
        </div>
      </div>
    </div>
  );
}
