import type { ClientOption } from "./types/reference-data";

/** Display label: "GCD - Acme LLC" */
export function formatClientLabel(client: ClientOption): string {
  const office = (client.office || "GCD").trim().toUpperCase() || "GCD";
  return `${office} - ${client.name}`;
}

export function formatClientLabelParts(office: string, name: string): string {
  const o = (office || "GCD").trim().toUpperCase() || "GCD";
  return `${o} - ${name}`;
}

/** Parse "GCD - Acme" → { office, name }. Falls back to whole string as name. */
export function parseClientLabel(label: string): { office: string; name: string } {
  const raw = label.trim();
  const m = raw.match(/^(GCD|MH)\s*[-–—]\s*(.+)$/i);
  if (m) {
    return { office: m[1].toUpperCase(), name: m[2].trim() };
  }
  return { office: "GCD", name: raw };
}

export function clientLabels(clients: ClientOption[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const c of clients) {
    if (!c.name?.trim()) continue;
    const label = formatClientLabel(c);
    if (seen.has(label)) continue;
    seen.add(label);
    out.push(label);
  }
  out.sort((a, b) => a.localeCompare(b));
  return out;
}
