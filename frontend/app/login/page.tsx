"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";
import { getSupabase } from "@/lib/supabase";

/** Only a path on this site, so a crafted link can't send people elsewhere after signing in. */
function safeNext(value: string | null) {
  return value && value.startsWith("/") && !value.startsWith("//") && !value.startsWith("/\\") ? value : null;
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  );
}

function LoginInner() {
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function sendCode(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const { error: sendError } = await getSupabase().auth.signInWithOtp({
      email,
      options: { shouldCreateUser: true },
    });
    setBusy(false);
    if (sendError) {
      setError(sendError.message);
      return;
    }
    setSent(true);
  }

  async function verify(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const { error: verifyError } = await getSupabase().auth.verifyOtp({
      email,
      token: otp,
      type: "email",
    });
    setBusy(false);
    if (verifyError) {
      setError(verifyError.message);
      return;
    }
    router.push(next ?? "/");
    router.refresh();
  }

  return (
    <main className="mx-auto flex min-h-full w-full max-w-lg flex-col px-5 py-10">
      <Link href="/" className="text-sm tracking-[0.2em] text-terracotta uppercase">
        Mediator
      </Link>
      <h1 className="mt-12 font-[family-name:var(--font-display)] text-4xl text-ink">
        Sign in with email
      </h1>
      <p className="mt-3 text-muted">
        {next
          ? "We send a one-time code. Then you'll go straight back to your conversation to save it."
          : "We send a one-time code. Person A needs this to open a room. Person B can join from the invite link without an account."}
      </p>

      {!sent ? (
        <form onSubmit={sendCode} className="mt-10 space-y-4">
          <label className="block text-sm text-muted">
            Email
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-2 w-full rounded-2xl border border-ink/10 bg-card px-4 py-3 text-base text-ink outline-none focus:border-terracotta"
            />
          </label>
          {error ? <p className="text-sm text-terracotta">{error}</p> : null}
          <button
            disabled={busy}
            className="w-full rounded-full bg-teal px-5 py-3.5 text-card disabled:opacity-60"
          >
            {busy ? "Sending…" : "Send code"}
          </button>
        </form>
      ) : (
        <form onSubmit={verify} className="mt-10 space-y-4">
          <p className="text-sm text-muted">Code sent to {email}</p>
          <label className="block text-sm text-muted">
            One-time code
            <input
              inputMode="numeric"
              required
              value={otp}
              onChange={(e) => setOtp(e.target.value)}
              className="mt-2 w-full rounded-2xl border border-ink/10 bg-card px-4 py-3 text-base tracking-[0.3em] text-ink outline-none focus:border-terracotta"
            />
          </label>
          {error ? <p className="text-sm text-terracotta">{error}</p> : null}
          <button
            disabled={busy}
            className="w-full rounded-full bg-teal px-5 py-3.5 text-card disabled:opacity-60"
          >
            {busy ? "Checking…" : "Enter room access"}
          </button>
        </form>
      )}
    </main>
  );
}
