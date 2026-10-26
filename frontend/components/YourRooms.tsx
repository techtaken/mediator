"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchMyRooms } from "@/lib/api";
import type { RoomSummary, SessionStatus } from "@/lib/types";

const STATUS: Record<SessionStatus, { label: string; tone: string }> = {
  intake: { label: "Talking privately", tone: "bg-terracotta/10 text-terracotta" },
  building_joint: { label: "Preparing joint view", tone: "bg-teal/10 text-teal" },
  joint_review: { label: "Joint session", tone: "bg-teal/10 text-teal" },
  resolved: { label: "Agreement signed", tone: "bg-teal text-card" },
  halted: { label: "Paused", tone: "bg-ink/10 text-muted" },
};

function when(value: string) {
  return new Date(value).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** The signed-in person's rooms, so nobody loses a room by losing its link. */
export function YourRooms({ accessToken }: { accessToken: string }) {
  const [rooms, setRooms] = useState<RoomSummary[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchMyRooms(accessToken)
      .then((next) => {
        if (!cancelled) setRooms(next);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  if (failed) return <p className="mt-10 text-sm text-muted">Couldn&apos;t load your rooms right now.</p>;
  if (rooms === null) {
    return <div className="mt-10 h-16 animate-pulse rounded-3xl bg-ink/[0.06]" aria-label="Loading your rooms" />;
  }
  if (rooms.length === 0) return null;

  return (
    <section className="mt-12">
      <h2 className="font-[family-name:var(--font-display)] text-xl text-ink">Your rooms</h2>
      <ul className="mt-3 space-y-2">
        {rooms.map((room) => {
          const status = STATUS[room.status] ?? STATUS.intake;
          return (
            <li key={room.id}>
              <Link
                href={`/room/${room.id}`}
                className="flex items-center gap-3 rounded-3xl bg-card px-4 py-3.5 shadow-[0_1px_0_rgba(36,28,22,0.08)] hover:shadow-[0_1px_0_rgba(36,28,22,0.08),0_8px_24px_-16px_rgba(36,28,22,0.4)]"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[15px] text-ink">{room.topic ?? "Untitled room"}</span>
                  <span className="mt-0.5 block text-xs text-muted">Opened {when(room.created_at)}</span>
                </span>
                <span className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-medium ${status.tone}`}>
                  {status.label}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
