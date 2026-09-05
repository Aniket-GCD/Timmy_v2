"use client";

import { FormEvent, useState } from "react";
import { createClient } from "@/lib/auth/supabase-browser";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [message, setMessage] = useState("");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setStatus("sending");
    setMessage("");
    try {
      const supabase = createClient();
      const origin = window.location.origin;
      const { error } = await supabase.auth.signInWithOtp({
        email: email.trim(),
        options: { emailRedirectTo: `${origin}/auth/callback` },
      });
      if (error) throw error;
      setStatus("sent");
      setMessage("Check Outlook for the Timmy sign-in link, then return here.");
    } catch (err) {
      setStatus("error");
      setMessage(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="page" style={{ maxWidth: 420, marginTop: "4rem" }}>
      <img src="/timmy-lockup-green.svg" alt="Timmy" height={48} style={{ marginBottom: "1.5rem" }} />
      <h1 style={{ fontSize: "1.5rem", marginBottom: "0.5rem" }}>Sign in</h1>
      <p className="muted" style={{ marginBottom: "1.25rem" }}>
        Use your work email. We&apos;ll send a one-time link to Outlook.
      </p>
      <form onSubmit={onSubmit}>
        <label className="muted" style={{ display: "block", marginBottom: "0.35rem" }}>
          Email
        </label>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={{
            width: "100%",
            padding: "0.65rem 0.85rem",
            border: "1px solid var(--border)",
            borderRadius: 8,
            fontFamily: "inherit",
            fontSize: "1rem",
            marginBottom: "0.85rem",
          }}
        />
        <button
          type="submit"
          disabled={status === "sending"}
          style={{
            background: "var(--mysterious-mixture)",
            color: "#fff",
            border: "none",
            borderRadius: 8,
            padding: "0.65rem 1.1rem",
            fontFamily: "inherit",
            cursor: "pointer",
          }}
        >
          {status === "sending" ? "Sending…" : "Send magic link"}
        </button>
      </form>
      {message ? (
        <p
          className="muted"
          style={{ marginTop: "1rem", color: status === "error" ? "#a33" : undefined }}
        >
          {message}
        </p>
      ) : null}
    </div>
  );
}
