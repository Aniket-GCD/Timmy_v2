"use client";

import styles from "./OutOfWindowConfirm.module.css";

type Props = {
  open: boolean;
  mode: "edit" | "create";
  onConfirm: () => void;
  onCancel: () => void;
};

export function OutOfWindowConfirm({ open, mode, onConfirm, onCancel }: Props) {
  if (!open) return null;
  const message =
    mode === "create"
      ? "You are about to add an entry outside the pay-period edit window. Continue?"
      : "You are about to edit outside the pay-period edit window. Continue?";

  return (
    <div className={styles.backdrop} role="presentation" onClick={onCancel}>
      <div
        className={styles.dialog}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="out-of-window-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="out-of-window-title" className={styles.title}>
          Outside edit window
        </h3>
        <p className={styles.body}>{message}</p>
        <div className={styles.actions}>
          <button type="button" className={styles.cancel} onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className={styles.confirm} onClick={onConfirm}>
            Continue
          </button>
        </div>
      </div>
    </div>
  );
}
