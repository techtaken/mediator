"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { getSupabase } from "@/lib/supabase";
import { useAuth } from "@/lib/useAuth";

/** Only a path on this site, so a crafted link can't send people elsewhere after signing in. */
function safeNext(value: string | null) {
  return value &&
    value.startsWith("/") &&
    !value.startsWith("//") &&
    !value.startsWith("/\\")
    ? value
    : null;
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
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const { session } = useAuth();

  // Opening the email link signs this browser in from another tab. This tab
  // notices and moves on, so nobody has to find their way back.
  useEffect(() => {
    if (sent && session) router.replace(next ?? "/");
  }, [sent, session, next, router]);

  // Where signing in brings people back to, e.g. the room they're saving.
  const back = next
    ? `${next}${next.includes("?") ? "&" : "?"}from=signin`
    : "/";

  async function signInWithGoogle() {
    setBusy(true);
    setError("");
    const { error: googleError } = await getSupabase().auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}${back}` },
    });
    // On success the browser has already left for Google.
    if (googleError) {
      setBusy(false);
      setError(googleError.message);
    }
  }

  async function sendCode(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const { error: sendError } = await getSupabase().auth.signInWithOtp({
      email,
      options: {
        shouldCreateUser: true,
        emailRedirectTo: `${window.location.origin}${back}`,
      },
    });
    setBusy(false);
    if (sendError) {
      setError(sendError.message);
      return;
    }
    setSent(true);
  }

  return (
    <main className="mx-auto flex min-h-full w-full max-w-lg flex-col px-5 py-10">
      <Link
        href="/"
        className="text-sm tracking-[0.2em] text-terracotta uppercase"
      >
        Mediator
      </Link>
      <h1 className="mt-12 font-[family-name:var(--font-display)] text-4xl text-ink">
        Sign in
      </h1>
      <p className="mt-3 text-muted">
        {next
          ? "Sign in to save this conversation to your account. You'll come straight back to it."
          : "You need an account to open a room. If someone invited you, you can join from their link without one."}
      </p>

      {!sent ? (
        <>
          <button
            type="button"
            onClick={() => void signInWithGoogle()}
            disabled={busy}
            className="mt-10 flex w-full items-center justify-center gap-3 rounded-full border border-ink/15 bg-card px-5 py-3.5 text-ink disabled:opacity-60"
          >
            <svg viewBox="0 0 48 48" width="20" height="20" aria-hidden="true">
              <path
                fill="#FFC107"
                d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"
              />
              <path
                fill="#FF3D00"
                d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"
              />
              <path
                fill="#4CAF50"
                d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"
              />
              <path
                fill="#1976D2"
                d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"
              />
            </svg>
            Continue with Google
          </button>
          <div className="mt-6 flex items-center gap-3 text-xs text-muted">
            <span className="h-px flex-1 bg-ink/10" />
            or use your email
            <span className="h-px flex-1 bg-ink/10" />
          </div>
          <form onSubmit={sendCode} className="mt-6 space-y-4">
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
        </>
      ) : (
        <div className="mt-10 space-y-4">
          <div className="rounded-2xl bg-card px-4 py-3.5 text-[15px] leading-relaxed text-ink shadow-[0_1px_0_rgba(36,28,22,0.08)]">
            <p className="font-medium">Check your email</p>
            <p className="mt-1 text-muted">
              We sent a sign-in link to {email}. Open it on this phone or computer. Once you&apos;re signed in, this
              page takes you {next ? "back to your conversation" : "to your rooms"} by itself.
            </p>
            <p className="mt-2 text-sm text-muted">Can&apos;t find it? Check spam, or wait a minute before trying again.</p>
          </div>
          <button
            type="button"
            onClick={() => {
              setSent(false);
              setError("");
            }}
            className="w-full rounded-full px-5 py-2.5 text-sm text-muted underline-offset-4 hover:underline"
          >
            Use a different email
          </button>
        </div>
      )}
      <p className="mt-10 text-center text-xs text-muted">
        <Link href="/privacy" className="underline underline-offset-4">
          Privacy and terms
        </Link>
      </p>
    </main>
  );
}
