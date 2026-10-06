/** Firm clients that are not a client of one office. The row uses the employee's home office. */
export const HOME_OFFICE_CLIENTS = new Set([
  "admin",
  "early out",
  "holiday",
  "staff meeting",
  "vacation",
]);

export function isHomeOfficeClient(name: string): boolean {
  return HOME_OFFICE_CLIENTS.has(name.trim().toLowerCase());
}

/** Office stored on a time entry: the client's office, not the employee's.
 * `selectedOffice` is the office on the chosen "GCD - Name" label, or the
 * employee's home office for Admin, Early Out, Holiday, Staff Meeting, and Vacation.
 * A name that exists in only one office wins over that label.
 * Unassigned exists once per office, so the label (or staff office) is kept.
 */
export function resolveEntryOffice(
  clientName: string,
  clients: Array<{ name: string; office?: string }>,
  selectedOffice: string,
): string {
  const name = clientName.trim();
  const selected = (selectedOffice || "GCD").trim().toUpperCase();
  const hint = selected === "MH" ? "MH" : "GCD";
  if (!name || name.toLowerCase() === "unassigned" || isHomeOfficeClient(name)) return hint;
  const offices = new Set<string>();
  for (const client of clients) {
    if (client.name.trim().toLowerCase() !== name.toLowerCase()) continue;
    const office = (client.office || "").trim().toUpperCase();
    if (office === "GCD" || office === "MH") offices.add(office);
  }
  if (offices.size === 1) return [...offices][0];
  if (offices.has(hint)) return hint;
  return hint;
}
