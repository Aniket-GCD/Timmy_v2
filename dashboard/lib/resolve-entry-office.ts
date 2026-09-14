/** Resolve entry office from the selected client (dashboard writes). */
export function resolveEntryOffice(
  clientName: string,
  clients: Array<{ name: string; office?: string }>,
  fallbackOffice: string,
): string {
  const name = clientName.trim();
  const fallback = (fallbackOffice || "GCD").trim().toUpperCase() || "GCD";
  if (!name) return fallback;
  if (name.toLowerCase() === "unassigned") return fallback;
  const matches = clients.filter((c) => c.name.trim().toLowerCase() === name.toLowerCase());
  if (matches.length === 0) return fallback;
  const prefer = matches.find((c) => (c.office || "").toUpperCase() === fallback);
  const hit = prefer ?? matches[0];
  const office = (hit.office || "").trim().toUpperCase();
  return office === "GCD" || office === "MH" ? office : fallback;
}
