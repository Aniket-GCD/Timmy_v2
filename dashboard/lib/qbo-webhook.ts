/** Server-only QuickBooks webhook helpers (signature + Customer → clients). */

import { createHmac, timingSafeEqual } from "crypto";
import type { QboOffice } from "@/lib/qbo-oauth";
import { parseQboOffice, qboClientId, qboClientSecret, upsertQboTokenRow } from "@/lib/qbo-oauth";

const CLIENTS_TABLE = "clients";
const QBO_BASE = "https://quickbooks.api.intuit.com/v3/company";
const TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer";

export type QboCustomerEntityOp = "Create" | "Update" | "Delete" | "Merge" | string;

export type QboWebhookEntity = {
  name: string;
  id: string;
  operation: QboCustomerEntityOp;
};

export type QboWebhookNotification = {
  realmId: string;
  entities: QboWebhookEntity[];
};

export function qboWebhookVerifierToken(): string {
  return (process.env.QBO_WEBHOOK_VERIFIER_TOKEN ?? "").trim();
}

/** HMAC-SHA256(rawBody, verifier) as Base64; compare to intuit-signature. */
export function verifyIntuitWebhookSignature(
  rawBody: string,
  signatureHeader: string | null | undefined,
  verifierToken: string,
): boolean {
  const signature = (signatureHeader ?? "").trim();
  const verifier = verifierToken.trim();
  if (!signature || !verifier || !rawBody) return false;
  const expected = createHmac("sha256", verifier).update(rawBody, "utf8").digest("base64");
  try {
    const a = Buffer.from(expected);
    const b = Buffer.from(signature);
    if (a.length !== b.length) return false;
    return timingSafeEqual(a, b);
  } catch {
    return false;
  }
}

/** Parse Intuit webhook JSON into Customer entities only. */
export function parseCustomerWebhookNotifications(payload: unknown): QboWebhookNotification[] {
  if (!payload || typeof payload !== "object") return [];
  const root = payload as { eventNotifications?: unknown };
  const notes = root.eventNotifications;
  if (!Array.isArray(notes)) return [];

  const out: QboWebhookNotification[] = [];
  for (const note of notes) {
    if (!note || typeof note !== "object") continue;
    const n = note as {
      realmId?: unknown;
      dataChangeEvent?: { entities?: unknown };
    };
    const realmId = String(n.realmId ?? "").trim();
    if (!realmId) continue;
    const entitiesRaw = n.dataChangeEvent?.entities;
    if (!Array.isArray(entitiesRaw)) continue;
    const entities: QboWebhookEntity[] = [];
    for (const ent of entitiesRaw) {
      if (!ent || typeof ent !== "object") continue;
      const e = ent as { name?: unknown; id?: unknown; operation?: unknown };
      const name = String(e.name ?? "").trim();
      if (name.toLowerCase() !== "customer") continue;
      const id = String(e.id ?? "").trim();
      const operation = String(e.operation ?? "").trim();
      if (!id || !operation) continue;
      entities.push({ name: "Customer", id, operation });
    }
    if (entities.length) out.push({ realmId, entities });
  }
  return out;
}

export async function refreshAccessToken(params: {
  clientId: string;
  clientSecret: string;
  refreshToken: string;
}): Promise<{ access_token: string; refresh_token: string }> {
  const basic = Buffer.from(`${params.clientId}:${params.clientSecret}`).toString("base64");
  const body = new URLSearchParams({
    grant_type: "refresh_token",
    refresh_token: params.refreshToken,
  });
  const res = await fetch(TOKEN_URL, {
    method: "POST",
    headers: {
      Authorization: `Basic ${basic}`,
      "Content-Type": "application/x-www-form-urlencoded",
      Accept: "application/json",
      "User-Agent": "curl/8.5.0",
    },
    body: body.toString(),
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`QBO token refresh failed HTTP ${res.status}: ${text.slice(0, 240)}`);
  }
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(text) as Record<string, unknown>;
  } catch {
    throw new Error("QBO token refresh returned non-JSON");
  }
  const access = String(payload.access_token ?? "").trim();
  if (!access) throw new Error("QBO token refresh returned no access_token");
  const refresh =
    String(payload.refresh_token ?? "").trim() || params.refreshToken;
  return { access_token: access, refresh_token: refresh };
}

export type QboTokenRow = {
  office: QboOffice;
  realm_id: string;
  refresh_token: string;
};

export async function loadTokenByRealmId(realmId: string): Promise<QboTokenRow | null> {
  const { supabaseFetch } = await import("@/lib/supabase-server");
  const rid = realmId.trim();
  if (!rid) return null;
  const rows = await supabaseFetch<Array<Record<string, unknown>>>(
    `qbo_tokens?select=office,realm_id,refresh_token&realm_id=eq.${encodeURIComponent(rid)}&limit=1`,
    { purpose: "service" },
  );
  if (!Array.isArray(rows) || !rows[0]) return null;
  const office = parseQboOffice(String(rows[0].office ?? ""));
  const refresh = String(rows[0].refresh_token ?? "").trim();
  const realm = String(rows[0].realm_id ?? "").trim();
  if (!office || !refresh || !realm) return null;
  return { office, realm_id: realm, refresh_token: refresh };
}

export type QboCustomer = {
  Id?: string;
  DisplayName?: string;
  CompanyName?: string;
  FullyQualifiedName?: string;
  Active?: boolean;
};

export function customerDisplayName(customer: QboCustomer): string {
  return String(
    customer.DisplayName || customer.CompanyName || customer.FullyQualifiedName || "",
  ).trim();
}

export async function fetchCustomer(
  realmId: string,
  accessToken: string,
  customerId: string,
): Promise<QboCustomer> {
  const url =
    `${QBO_BASE}/${encodeURIComponent(realmId)}/customer/${encodeURIComponent(customerId)}` +
    `?minorversion=65`;
  const res = await fetch(url, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/json",
      "User-Agent": "curl/8.5.0",
    },
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`QBO customer fetch failed HTTP ${res.status}: ${text.slice(0, 240)}`);
  }
  let payload: { Customer?: QboCustomer };
  try {
    payload = JSON.parse(text) as { Customer?: QboCustomer };
  } catch {
    throw new Error("QBO customer fetch returned non-JSON");
  }
  const customer = payload.Customer;
  if (!customer) throw new Error("QBO customer fetch missing Customer");
  return customer;
}

export async function deactivateClient(office: QboOffice, qboId: string): Promise<void> {
  const { supabaseFetch } = await import("@/lib/supabase-server");
  await supabaseFetch(
    `${CLIENTS_TABLE}?office=eq.${encodeURIComponent(office)}&qbo_customer_id=eq.${encodeURIComponent(qboId)}`,
    {
      method: "PATCH",
      prefer: "return=minimal",
      purpose: "service",
      body: JSON.stringify({ active: false }),
    },
  );
}

export async function upsertClientFromCustomer(
  office: QboOffice,
  customer: QboCustomer,
): Promise<"insert" | "update"> {
  const { supabaseFetch } = await import("@/lib/supabase-server");
  const qboId = String(customer.Id ?? "").trim();
  const name = customerDisplayName(customer);
  if (!qboId || !name) throw new Error("Customer missing Id or display name");
  const active = customer.Active !== false;
  const body = {
    name,
    office,
    qbo_customer_id: qboId,
    active,
  };

  const byQbo = await supabaseFetch<Array<{ id: number | string }>>(
    `${CLIENTS_TABLE}?select=id&qbo_customer_id=eq.${encodeURIComponent(qboId)}&office=eq.${encodeURIComponent(office)}&limit=1`,
    { purpose: "service" },
  );
  if (Array.isArray(byQbo) && byQbo[0]?.id != null) {
    await supabaseFetch(`${CLIENTS_TABLE}?id=eq.${encodeURIComponent(String(byQbo[0].id))}`, {
      method: "PATCH",
      prefer: "return=minimal",
      purpose: "service",
      body: JSON.stringify(body),
    });
    return "update";
  }

  const byName = await supabaseFetch<Array<{ id: number | string }>>(
    `${CLIENTS_TABLE}?select=id&name=eq.${encodeURIComponent(name)}&office=eq.${encodeURIComponent(office)}&limit=1`,
    { purpose: "service" },
  );
  if (Array.isArray(byName) && byName[0]?.id != null) {
    await supabaseFetch(`${CLIENTS_TABLE}?id=eq.${encodeURIComponent(String(byName[0].id))}`, {
      method: "PATCH",
      prefer: "return=minimal",
      purpose: "service",
      body: JSON.stringify(body),
    });
    return "update";
  }

  await supabaseFetch(CLIENTS_TABLE, {
    method: "POST",
    prefer: "return=minimal",
    purpose: "service",
    body: JSON.stringify(body),
  });
  return "insert";
}

/** Refresh access for a token row and persist rotated refresh immediately. */
export async function refreshAndPersistToken(
  row: QboTokenRow,
): Promise<{ access_token: string; refresh_token: string }> {
  const clientId = qboClientId();
  const clientSecret = qboClientSecret();
  if (!clientId || !clientSecret) {
    throw new Error("QBO_CLIENT_ID / QBO_CLIENT_SECRET not configured");
  }
  const tokens = await refreshAccessToken({
    clientId,
    clientSecret,
    refreshToken: row.refresh_token,
  });
  await upsertQboTokenRow({
    office: row.office,
    realmId: row.realm_id,
    refreshToken: tokens.refresh_token,
  });
  row.refresh_token = tokens.refresh_token;
  return tokens;
}
