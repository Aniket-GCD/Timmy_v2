"use client";

import { useMemo, useState } from "react";
import styles from "./Combobox.module.css";
import { filterComboboxOptions } from "./Combobox";

type Props = {
  values: string[];
  options: string[];
  onChange: (values: string[]) => void;
  disabled?: boolean;
  placeholder?: string;
  ariaLabel?: string;
  className?: string;
};

export function MultiCombobox({
  values,
  options,
  onChange,
  disabled,
  placeholder,
  ariaLabel,
  className,
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => filterComboboxOptions(options, query), [options, query]);

  function toggle(opt: string) {
    onChange(values.includes(opt) ? values.filter((value) => value !== opt) : [...values, opt]);
  }

  return (
    <div className={[styles.wrap, className].filter(Boolean).join(" ")}>
      {values.length > 0 ? (
        <ul className={styles.chips}>
          {values.map((value) => (
            <li key={value} className={styles.chip}>
              <span>{value}</span>
              <button
                type="button"
                aria-label={`Remove ${value}`}
                disabled={disabled}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => toggle(value)}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <input
        className={styles.input}
        value={query}
        disabled={disabled}
        placeholder={placeholder}
        aria-label={ariaLabel}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && !disabled && filtered.length > 0 ? (
        <ul className={styles.list} role="listbox" aria-multiselectable="true">
          {filtered.map((opt) => {
            const selected = values.includes(opt);
            return (
              <li key={opt}>
                <button
                  type="button"
                  className={selected ? `${styles.option} ${styles.optionOn}` : styles.option}
                  aria-pressed={selected}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => toggle(opt)}
                >
                  {opt}
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
