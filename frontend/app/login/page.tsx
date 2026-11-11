"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { getSupabase } from "@/lib/supabase";
import { useAuth } from "@/lib/useAuth";

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
  const { session } = useAuth();

  // Opening the email link signs this browser in from another tab. This tab
  // notices and moves on, so nobody has to find their way back.
  useEffect(() => {
    if (sent && session) router.replace(next ?? "/");
  }, [sent, session, next, router]);

  async function sendCode(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    // The email holds a link (and, once the template allows it, a code). The
    // link brings people back to where they were, e.g. the room they're saving.
    const back = next ? `${next}${next.includes("?") ? "&" : "?"}from=signin` : "/";
    const { error: sendError } = await getSupabase().auth.signInWithOtp({
      email,
      options: { shouldCreateUser: true, emailRedirectTo: `${window.location.origin}${back}` },
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
          ? "We'll email you a sign-in link. It brings you back to your conversation to save it."
          : "We'll email you a sign-in link. Person A needs this to open a room. Person B can join from the invite link without an account."}
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
            {busy ? "Sending…" : "Email me a sign-in link"}
          </button>
        </form>
      ) : (
        <form onSubmit={verify} className="mt-10 space-y-4">
          <div className="rounded-2xl bg-card px-4 py-3.5 text-[15px] leading-relaxed text-ink shadow-[0_1px_0_rgba(36,28,22,0.08)]">
            <p className="font-medium">Check your email</p>
            <p className="mt-1 text-muted">
              We sent a sign-in link to {email}. Open it on this phone or computer. Once you&apos;re signed in, this
              page takes you {next ? "back to your conversation" : "to your rooms"} by itself.
            </p>
          </div>
          <label className="block text-sm text-muted">
            If your email shows a 6-digit code instead, enter it here
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
            {busy ? "Checking…" : "Sign in"}
          </button>
        </form>
      )}
    </main>
  );
}
