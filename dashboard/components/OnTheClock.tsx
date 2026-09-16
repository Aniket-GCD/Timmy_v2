"use client";

import { formatHoursHM, parseLocalStartMs } from "@/lib/hours-format";
import type { CurrentlyWorking } from "@/lib/types/currently-working";
import type { Employee } from "@/lib/types/employee";
import styles from "./OnTheClock.module.css";

type Props = {
  sessions: CurrentlyWorking[];
  employees: Employee[];
};

function elapsedHours(startedAt: string): number {
  const start = parseLocalStartMs(startedAt);
  if (Number.isNaN(start)) return 0;
  return Math.max(0, (Date.now() - start) / 3_600_000);
}

export function OnTheClock({ sessions, employees }: Props) {
  if (sessions.length === 0) {
    return (
      <section className="section" aria-label="On the clock">
        <div className={styles.empty}>No one on the clock</div>
      </section>
    );
  }

  const roster = new Map(employees.map((e) => [e.staff_name, e]));

  return (
    <section className="section" aria-label="On the clock">
      <h2 className="section-title">On the clock</h2>
      <div className={styles.strip}>
        {sessions.map((s) => {
          const emp = roster.get(s.staff_name);
          const label = emp?.staff_name ?? s.staff_name;
          const overdue = s.planned_end_at ? Date.parse(s.planned_end_at) < Date.now() : false;
          return (
            <div key={s.id} className={overdue ? styles.cardOverdue : styles.card}>
              <div className={styles.name}>{label}</div>
              <div className={styles.client}>{s.client}</div>
              <div className={styles.elapsed}>
                {formatHoursHM(elapsedHours(s.started_at))}
                {overdue ? " · overdue" : ""}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
