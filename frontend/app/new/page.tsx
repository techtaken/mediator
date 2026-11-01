"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { NameForm } from "@/components/NameForm";
import { NewRoomForm } from "@/components/NewRoomForm";
import { RoomList, isOpenRoom, useMyRooms } from "@/components/YourRooms";
import { useAuth } from "@/lib/useAuth";
import { useProfile } from "@/lib/useProfile";

export default function NewRoomPage() {
  const router = useRouter();
  const { accessToken, loading } = useAuth();
  const rooms = useMyRooms(accessToken);
  const profile = useProfile(accessToken);
  const [startAnyway, setStartAnyway] = useState(false);

  useEffect(() => {
    if (!loading && !accessToken) router.replace("/login");
  }, [loading, accessToken, router]);

  const openRooms = Array.isArray(rooms) ? rooms.filter(isOpenRoom) : [];
  // A second room about the same fight sends the other person a second invite; check first.
  const askFirst = openRooms.length > 0 && !startAnyway;

  return (
    <main className="mx-auto flex min-h-full w-full max-w-lg flex-col px-5 py-10">
      <header className="flex items-center justify-between">
        <Link href="/" className="text-sm tracking-[0.2em] text-terracotta uppercase">
          Mediator
        </Link>
        <Link href="/" className="text-sm text-muted underline-offset-4 hover:underline">
          ← Your rooms
        </Link>
      </header>

      {!profile.loading && accessToken && !profile.name && !profile.failed ? (
        <div className="mt-10">
          <NameForm onSave={profile.save} />
        </div>
      ) : (
        <h1 className="mt-10 font-[family-name:var(--font-display)] text-3xl text-ink">Start a new conversation</h1>
      )}

      {loading || !accessToken || rooms === null || profile.loading ? (
        <div className="mt-8 h-40 animate-pulse rounded-3xl bg-ink/[0.06]" aria-label="Loading" />
      ) : !profile.name && !profile.failed ? null : askFirst ? (
        <section className="mt-6">
          <p className="text-[15px] leading-relaxed text-muted">
            {openRooms.length === 1
              ? "You already have a conversation going. If this is about the same thing, it's better to continue that one, so the other person doesn't get a second invite."
              : "You already have conversations going. If this is about one of them, it's better to continue it, so the other person doesn't get a second invite."}
          </p>
          <div className="mt-5">
            <RoomList rooms={openRooms} />
          </div>
          <button
            type="button"
            onClick={() => setStartAnyway(true)}
            className="mt-6 w-full rounded-full border border-ink/15 px-5 py-3.5 text-base text-ink hover:border-ink/30"
          >
            This is about something else
          </button>
        </section>
      ) : (
        <div className="mt-8">
          <NewRoomForm accessToken={accessToken} />
        </div>
      )}
    </main>
  );
}
