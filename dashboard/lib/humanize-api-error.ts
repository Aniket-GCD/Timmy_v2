import { ENTRY_ERRORS } from "./validate-entry";

/** Map API / network failure text into a short message staff can act on. */
export function humanizeApiError(raw: string): string {
  const text = raw.trim();
  if (!text) return ENTRY_ERRORS.saveFailed;

  let message = text;
  try {
    const parsed = JSON.parse(text) as { error?: unknown };
    if (typeof parsed.error === "string" && parsed.error.trim()) {
      message = parsed.error.trim();
    }
  } catch {
    // Next's 404 HTML includes `"forbidden":"$undefined"`. That is not an edit denial.
    if (/<!doctype|<html/i.test(text)) return ENTRY_ERRORS.saveFailed;
  }

  const lower = message.toLowerCase();
  if (lower.includes("forbidden") || lower.includes("own time") || lower.includes("own entries")) {
    return ENTRY_ERRORS.ownOnly;
  }
  if (lower.includes("edit window") || lower.includes("locked for editing")) {
    return ENTRY_ERRORS.lockedDate;
  }
  if (lower.includes("not found")) {
    return ENTRY_ERRORS.notFound;
  }
  if (lower.includes("empty_write") || lower.includes("couldn’t save") || lower.includes("couldn't save")) {
    return ENTRY_ERRORS.saveFailed;
  }

  // Already human copy from validate-entry — pass through.
  const known = Object.values(ENTRY_ERRORS);
  if (known.includes(message as (typeof known)[number])) {
    return message;
  }
  if (
    message.startsWith("Pick a ") ||
    message.startsWith("Enter ") ||
    message.startsWith("This date ") ||
    message.startsWith("End time ") ||
    message.startsWith("You can only ") ||
    message.startsWith("We could")
  ) {
    return message;
  }

  return ENTRY_ERRORS.saveFailed;
}
