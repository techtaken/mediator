"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { CalmScene } from "@/components/CalmScene";
import { NameForm } from "@/components/NameForm";
import { NewRoomForm } from "@/components/NewRoomForm";
import { isOpenRoom, useMyRooms } from "@/components/YourRooms";
import { useAuth } from "@/lib/useAuth";
import { useProfile } from "@/lib/useProfile";

function SafetyNote() {
  return (
    <p className="mt-10 text-center text-xs leading-relaxed text-muted">
      Not for crisis, violence, or legal advice. If you are in danger, call 112.
    </p>
  );
}

function Loading() {
  return (
    <div className="mx-auto mt-16 w-full max-w-md space-y-3 px-5" aria-label="Loading">
      <div className="h-40 animate-pulse rounded-[32px] bg-ink/[0.06]" />
      <div className="h-10 w-2/3 animate-pulse rounded-2xl bg-ink/[0.06]" />
    </div>
  );
}

/** Signed out: what this is, and a way in. */
function Welcome() {
  return (
    <main className="mx-auto flex min-h-[100dvh] w-full max-w-md flex-col px-5 py-8">
      <header className="flex items-center justify-between">
        <p className="text-sm tracking-[0.2em] text-terracotta uppercase">Mediator</p>
        <Link href="/login" className="text-sm text-muted underline-offset-4 hover:underline">
          Sign in
        </Link>
      </header>
      <CalmScene className="mt-8 w-full" />
      <h1 className="mt-8 text-center font-[family-name:var(--font-display)] text-4xl leading-tight text-ink">
        Two private rooms.
        <br />
        One calmer conversation.
      </h1>
      <p className="mt-4 text-center text-[17px] leading-relaxed text-muted">
        For family and household disagreements. You each talk to the mediator privately, in Hinglish, Hindi or English.
        The other person only sees words you choose to share.
      </p>
      <Link
        href="/login"
        className="mt-8 inline-flex w-full items-center justify-center rounded-full bg-teal px-5 py-3.5 text-base text-card"
      >
        Sign in to start a conversation
      </Link>
      <p className="mt-3 text-center text-sm text-muted">Invited by someone? Just open the link they sent you.</p>
      <SafetyNote />
    </main>
  );
}

function HomeInner() {
  const { accessToken, loading } = useAuth();
  const profile = useProfile(accessToken);
  const rooms = useMyRooms(accessToken);
  const asked = useSearchParams().get("change") === "name";
  const [changingName, setChangingName] = useState(asked);

  if (loading || (accessToken && profile.loading)) return <Loading />;
  if (!accessToken) return <Welcome />;

  const askName = !profile.failed && (!profile.name || changingName);
  // A second room about the same thing sends the other person a second invite.
  const ongoing = Array.isArray(rooms) ? rooms.filter((room) => room.role === "opened" && isOpenRoom(room)) : [];

  return (
    <AppShell accessToken={accessToken} name={profile.name} onChangeName={() => setChangingName(true)}>
      <main className="mx-auto w-full max-w-md px-5 pt-6 pb-10 md:pt-14">
        {askName ? (
          <div className="pt-4">
            <NameForm
              initial={profile.name ?? ""}
              onSave={async (name) => {
                await profile.save(name);
                setChangingName(false);
              }}
              onCancel={profile.name ? () => setChangingName(false) : undefined}
            />
          </div>
        ) : (
          <>
            <CalmScene className="w-full" />
            <h1 className="mt-8 text-center font-[family-name:var(--font-display)] text-3xl leading-tight text-ink">
              {profile.name ? `Take a breath, ${profile.name}.` : "Take a breath."}
            </h1>
            <p className="mt-3 text-center text-[16px] leading-relaxed text-muted">
              Is something sitting heavy between you and someone close? Start a conversation. You&apos;ll each talk to
              the mediator privately first, and nothing you write is shared unless you approve it.
            </p>

            {ongoing.length ? (
              <p className="mt-6 rounded-2xl bg-card px-4 py-3 text-sm leading-relaxed text-muted shadow-[0_1px_0_rgba(36,28,22,0.08)]">
                {ongoing.length === 1
                  ? `You already have a conversation going${ongoing[0].other_name ? ` with ${ongoing[0].other_name}` : ""}.`
                  : "You already have conversations going."}{" "}
                If this is about the same thing, continue it from the list instead, so they don&apos;t get a second invite.
              </p>
            ) : null}

            <div className="mt-8">
              <NewRoomForm accessToken={accessToken} />
            </div>
          </>
        )}
        <SafetyNote />
      </main>
    </AppShell>
  );
}

export default function HomePage() {
  return (
    <Suspense fallback={<Loading />}>
      <HomeInner />
    </Suspense>
  );
}
