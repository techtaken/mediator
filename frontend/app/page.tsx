"use client";

import Link from "next/link";
import { NewRoomForm } from "@/components/NewRoomForm";
import { YourRooms, useMyRooms } from "@/components/YourRooms";
import { getSupabase } from "@/lib/supabase";
import { useAuth } from "@/lib/useAuth";

function Header({ signedIn }: { signedIn: boolean }) {
  async function signOut() {
    await getSupabase().auth.signOut();
  }

  return (
    <header className="flex items-center justify-between">
      <p className="text-sm tracking-[0.2em] text-terracotta uppercase">Mediator</p>
      {signedIn ? (
        <button type="button" onClick={signOut} className="text-sm text-muted underline-offset-4 hover:underline">
          Sign out
        </button>
      ) : (
        <Link href="/login" className="text-sm text-muted underline-offset-4 hover:underline">
          Sign in
        </Link>
      )}
    </header>
  );
}

function Footer() {
  return (
    <p className="mt-auto pt-10 text-xs leading-relaxed text-muted">
      Not for crisis, violence, or legal advice. If you are in danger, call 112.
    </p>
  );
}

function Intro() {
  return (
    <>
      <h1 className="mt-12 font-[family-name:var(--font-display)] text-4xl leading-tight text-ink">
        Two private rooms.
        <br />
        One calmer conversation.
      </h1>
      <p className="mt-4 text-lg leading-relaxed text-muted">
        For Indian family and household disputes. You vent privately in Hinglish or English. The other person never
        sees your raw words. Mediator translates both sides into needs, then offers a few workable compromises.
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
    </>
  );
}

export default function HomePage() {
  const { accessToken, loading, user } = useAuth();
  const rooms = useMyRooms(accessToken);

  // Someone coming back sees their rooms first; starting another one is a separate page.
  if (accessToken && Array.isArray(rooms) && rooms.length > 0) {
    return (
      <main className="mx-auto flex min-h-full w-full max-w-lg flex-col px-5 py-10">
        <Header signedIn />
        <h1 className="mt-10 font-[family-name:var(--font-display)] text-3xl text-ink">Your rooms</h1>
        <Link
          href="/new"
          className="mt-6 inline-flex w-full items-center justify-center rounded-full bg-teal px-5 py-3.5 text-base text-card"
        >
          Start a new conversation
        </Link>
        <div className="mt-10">
          <YourRooms rooms={rooms} />
        </div>
        <Footer />
      </main>
    );
  }

  const checkingRooms = Boolean(accessToken) && rooms === null;

  return (
    <main className="mx-auto flex min-h-full w-full max-w-lg flex-col px-5 py-10">
      <Header signedIn={Boolean(user)} />
      {loading || checkingRooms ? (
        <div className="mt-12 space-y-3" aria-label="Loading">
          <div className="h-10 w-2/3 animate-pulse rounded-2xl bg-ink/[0.06]" />
          <div className="h-24 animate-pulse rounded-3xl bg-ink/[0.06]" />
        </div>
      ) : (
        <>
          <Intro />
          {accessToken ? (
            <div className="mt-10">
              {rooms === "failed" ? (
                <p className="mb-4 text-sm text-muted">Couldn&apos;t load your rooms right now.</p>
              ) : null}
              <NewRoomForm accessToken={accessToken} />
            </div>
          ) : (
            <Link
              href="/login"
              className="mt-10 inline-flex w-full items-center justify-center rounded-full bg-teal px-5 py-3.5 text-base text-card"
            >
              Sign in to start a session
            </Link>
          )}
        </>
      )}
      <Footer />
    </main>
  );
}
