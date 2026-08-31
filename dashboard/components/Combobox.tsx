"use client";

import { useMemo, useState } from "react";
import styles from "./Combobox.module.css";

type Props = {
  value: string;
  options: string[];
  onChange: (value: string) => void;
  disabled?: boolean;
  placeholder?: string;
};

export function Combobox({ value, options, onChange, disabled, placeholder }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState(value);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options.slice(0, 12);
    return options.filter((o) => o.toLowerCase().includes(q)).slice(0, 12);
  }, [options, query]);

  return (
    <div className={styles.wrap}>
      <input
        className={styles.input}
        value={query}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && !disabled && filtered.length > 0 && (
        <ul className={styles.list} role="listbox">
          {filtered.map((opt) => (
            <li key={opt}>
              <button
                type="button"
                className={styles.option}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  onChange(opt);
                  setQuery(opt);
                  setOpen(false);
                }}
              >
                {opt}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
