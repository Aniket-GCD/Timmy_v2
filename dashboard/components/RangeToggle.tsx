"use client";

import styles from "./RangeToggle.module.css";

export type RangeKey = "yesterday" | "today" | "week";

const OPTIONS: { key: RangeKey; label: string }[] = [
  { key: "yesterday", label: "Yesterday" },
  { key: "today", label: "Today" },
  { key: "week", label: "This week" },
];

type Props = {
  value: RangeKey;
  onChange: (next: RangeKey) => void;
};

export function RangeToggle({ value, onChange }: Props) {
  return (
    <div className={styles.wrap} role="tablist" aria-label="Date range">
      {OPTIONS.map((opt) => {
        const active = opt.key === value;
        return (
          <button
            key={opt.key}
            type="button"
            role="tab"
            aria-selected={active}
            className={active ? styles.active : styles.btn}
            onClick={() => onChange(opt.key)}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
