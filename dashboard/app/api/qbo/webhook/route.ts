import { NextResponse } from "next/server";
import {
  deactivateClient,
  fetchCustomer,
  loadTokenByRealmId,
  parseCustomerWebhookNotifications,
  qboWebhookVerifierToken,
  refreshAndPersistToken,
  upsertClientFromCustomer,
  verifyIntuitWebhookSignature,
} from "@/lib/qbo-webhook";

/**
 * Intuit Customer webhooks → Supabase `clients`.
 * Register: https://dashboard-gcd1.vercel.app/api/qbo/webhook
 */
export async function POST(request: Request) {
  const rawBody = await request.text();
  const verifier = qboWebhookVerifierToken();
  if (!verifier) {
    console.error("[qbo-webhook] QBO_WEBHOOK_VERIFIER_TOKEN not set");
    return NextResponse.json({ error: "Server misconfigured" }, { status: 500 });
  }

  const signature = request.headers.get("intuit-signature");
  if (!verifyIntuitWebhookSignature(rawBody, signature, verifier)) {
    return NextResponse.json({ error: "Invalid signature" }, { status: 401 });
  }

  let payload: unknown;
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const notifications = parseCustomerWebhookNotifications(payload);
  const results: Array<Record<string, unknown>> = [];

  // Cache access tokens per realm within this request to avoid N refreshes.
  const accessByRealm = new Map<string, string>();

  for (const note of notifications) {
    const tokenRow = await loadTokenByRealmId(note.realmId);
    if (!tokenRow) {
      console.warn(`[qbo-webhook] unknown realmId=${note.realmId}`);
      results.push({ realmId: note.realmId, skipped: "unknown_realm" });
      continue;
    }

    for (const entity of note.entities) {
      const op = entity.operation;
      try {
        if (op === "Delete") {
          await deactivateClient(tokenRow.office, entity.id);
          results.push({
            office: tokenRow.office,
            id: entity.id,
            operation: op,
            action: "deactivate",
          });
          continue;
        }

        // Create / Update / Merge → fetch + upsert
        let access = accessByRealm.get(note.realmId);
        if (!access) {
          const tokens = await refreshAndPersistToken(tokenRow);
          access = tokens.access_token;
          accessByRealm.set(note.realmId, access);
        }

        const customer = await fetchCustomer(note.realmId, access, entity.id);
        const action = await upsertClientFromCustomer(tokenRow.office, customer);
        results.push({
          office: tokenRow.office,
          id: entity.id,
          operation: op,
          action,
        });
      } catch (e) {
        console.error(
          `[qbo-webhook] entity failed office=${tokenRow.office} id=${entity.id} op=${op}:`,
          e,
        );
        results.push({
          office: tokenRow.office,
          id: entity.id,
          operation: op,
          error: String(e),
        });
      }
    }
  }

  return NextResponse.json({ ok: true, results });
}
