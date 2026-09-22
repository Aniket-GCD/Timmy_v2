import { createHmac } from "crypto";
import { describe, expect, it } from "vitest";
import {
  customerDisplayName,
  parseCustomerWebhookNotifications,
  verifyIntuitWebhookSignature,
} from "@/lib/qbo-webhook";

describe("verifyIntuitWebhookSignature", () => {
  const verifier = "test-verifier-token";
  const body = '{"eventNotifications":[]}';

  it("accepts a valid HMAC signature", () => {
    const sig = createHmac("sha256", verifier).update(body, "utf8").digest("base64");
    expect(verifyIntuitWebhookSignature(body, sig, verifier)).toBe(true);
  });

  it("rejects a bad signature", () => {
    expect(verifyIntuitWebhookSignature(body, "not-valid", verifier)).toBe(false);
  });

  it("rejects missing signature or verifier", () => {
    expect(verifyIntuitWebhookSignature(body, null, verifier)).toBe(false);
    expect(verifyIntuitWebhookSignature(body, "x", "")).toBe(false);
  });
});

describe("parseCustomerWebhookNotifications", () => {
  it("extracts Customer entities and ignores others", () => {
    const payload = {
      eventNotifications: [
        {
          realmId: "111",
          dataChangeEvent: {
            entities: [
              { name: "Customer", id: "9", operation: "Create" },
              { name: "Invoice", id: "1", operation: "Update" },
              { name: "Customer", id: "10", operation: "Delete" },
            ],
          },
        },
      ],
    };
    const notes = parseCustomerWebhookNotifications(payload);
    expect(notes).toEqual([
      {
        realmId: "111",
        entities: [
          { name: "Customer", id: "9", operation: "Create" },
          { name: "Customer", id: "10", operation: "Delete" },
        ],
      },
    ]);
  });

  it("returns empty for malformed payload", () => {
    expect(parseCustomerWebhookNotifications(null)).toEqual([]);
    expect(parseCustomerWebhookNotifications({})).toEqual([]);
  });
});

describe("customerDisplayName", () => {
  it("prefers DisplayName", () => {
    expect(
      customerDisplayName({
        DisplayName: "Acme",
        CompanyName: "Other",
      }),
    ).toBe("Acme");
  });
});
