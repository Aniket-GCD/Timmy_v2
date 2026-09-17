"use client";

import { useEffect, useState } from "react";

type Me = {
  email: string;
  staff_name: string;
  is_admin: boolean;
};

export default function QboConnectPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/me");
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || res.statusText);
        if (!cancelled) setMe(data as Me);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div className="page" style={{ maxWidth: 520, marginTop: "3rem" }}>
        <h1>QuickBooks connect</h1>
        <p className="muted">{error}</p>
        <p>
          <a href="/login">Sign in</a>
        </p>
      </div>
    );
  }

  if (!me) {
    return (
      <div className="page" style={{ maxWidth: 520, marginTop: "3rem" }}>
        <p className="muted">Loading…</p>
      </div>
    );
  }

  if (!me.is_admin) {
    return (
      <div className="page" style={{ maxWidth: 520, marginTop: "3rem" }}>
        <h1>QuickBooks connect</h1>
        <p className="muted">Admin only. Signed in as {me.email}.</p>
        <p>
          <a href="/">Back to dashboard</a>
        </p>
      </div>
    );
  }

  return (
    <div className="page" style={{ maxWidth: 520, marginTop: "3rem" }}>
      <h1 style={{ fontSize: "1.5rem", marginBottom: "0.5rem" }}>Connect QuickBooks</h1>
      <p className="muted" style={{ marginBottom: "1.25rem" }}>
        Authorize each company once. On the Intuit screen, use the company switcher so the
        company matches the office button you click. Tokens are stored in Supabase{" "}
        <code>qbo_tokens</code>.
      </p>
      <p style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
        <a
          href="/api/qbo/start?office=GCD"
          style={{
            display: "inline-block",
            padding: "0.55rem 1rem",
            background: "var(--mysterious-mixture)",
            color: "var(--white)",
            borderRadius: 8,
          }}
        >
          Connect GCD
        </a>
        <a
          href="/api/qbo/start?office=MH"
          style={{
            display: "inline-block",
            padding: "0.55rem 1rem",
            background: "var(--mysterious-mixture)",
            color: "var(--white)",
            borderRadius: 8,
          }}
        >
          Connect MH
        </a>
      </p>
      <p className="muted" style={{ marginTop: "1.5rem", fontSize: "0.9rem" }}>
        Intuit Redirect URI must be exactly{" "}
        <code>https://dashboard-gcd1.vercel.app/api/qbo/callback</code> (or your
        dashboard host + <code>/api/qbo/callback</code>).
      </p>
      <p style={{ marginTop: "1rem" }}>
        <a href="/">← Dashboard</a>
      </p>
    </div>
  );
}
