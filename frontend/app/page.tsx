"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { createSession } from "@/lib/api";
import { getSupabase } from "@/lib/supabase";
import { useAuth } from "@/lib/useAuth";

export default function HomePage() {
  const router = useRouter();
  const { accessToken, loading, user } = useAuth();
  const [context, setContext] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    if (!accessToken) {
      router.push("/login");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const session = await createSession(context, accessToken);
      router.push(`/room/${session.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start a room");
      setBusy(false);
    }
  }

  async function signOut() {
    await getSupabase().auth.signOut();
  }

  return (
    <main className="mx-auto flex min-h-full w-full max-w-lg flex-col px-5 py-10">
      <header className="flex items-center justify-between">
        <p className="text-sm tracking-[0.2em] text-terracotta uppercase">Mediator</p>
        {user ? (
          <button
            type="button"
            onClick={signOut}
            className="text-sm text-muted underline-offset-4 hover:underline"
          >
            Sign out
          </button>
        ) : (
          <Link href="/login" className="text-sm text-muted underline-offset-4 hover:underline">
            Sign in
          </Link>
        )}
      </header>

      <h1 className="mt-12 font-[family-name:var(--font-display)] text-4xl leading-tight text-ink">
        Two private rooms.
        <br />
        One calmer conversation.
      </h1>
      <p className="mt-4 text-lg leading-relaxed text-muted">
        For Indian family and household disputes. You vent privately in Hinglish or English. The
        other person never sees your raw words. Mediator translates both sides into needs, then
        offers a few workable compromises.
      </p>

      <ol className="mt-8 space-y-3 text-sm text-ink">
        <li className="rounded-2xl bg-card px-4 py-3 shadow-[0_1px_0_rgba(36,28,22,0.08)]">
          1. You start a dispute room and share a WhatsApp link.
        </li>
        <li className="rounded-2xl bg-card px-4 py-3 shadow-[0_1px_0_rgba(36,28,22,0.08)]">
          2. Each of you talks privately with the mediator.
        </li>
        <li className="rounded-2xl bg-card px-4 py-3 shadow-[0_1px_0_rgba(36,28,22,0.08)]">
          3. When both are ready, a joint view shows the neutralized picture.
        </li>
      </ol>

      {loading ? (
        <p className="mt-10 text-muted">Loading…</p>
      ) : user ? (
        <form onSubmit={onCreate} className="mt-10 space-y-4">
          <label className="block text-sm text-muted">
            Relationship context (optional)
            <input
              value={context}
              onChange={(e) => setContext(e.target.value)}
              placeholder="e.g. siblings sharing a flat in Pune"
              className="mt-2 w-full rounded-2xl border border-ink/10 bg-card px-4 py-3 text-base text-ink outline-none focus:border-terracotta"
            />
          </label>
          {error ? <p className="text-sm text-terracotta">{error}</p> : null}
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-full bg-teal px-5 py-3.5 text-base text-card disabled:opacity-60"
          >
            {busy ? "Opening room…" : "Start a session"}
          </button>
        </form>
      ) : (
        <Link
          href="/login"
          className="mt-10 inline-flex w-full items-center justify-center rounded-full bg-teal px-5 py-3.5 text-base text-card"
        >
          Sign in to start a session
        </Link>
      )}

      <p className="mt-8 text-xs leading-relaxed text-muted">
        Not for crisis, violence, or legal advice. If you are in danger, call 112.
      </p>
    </main>
  );
}
