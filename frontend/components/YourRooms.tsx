"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchMyRooms } from "@/lib/api";
import type { RoomSummary } from "@/lib/types";

const OPEN_STATUSES = new Set(["intake", "building_joint", "joint_review"]);

export function isOpenRoom(room: RoomSummary) {
  return OPEN_STATUSES.has(room.status);
}

/** The signed-in person's rooms: null while loading, "failed" if they couldn't be loaded. */
export function useMyRooms(accessToken: string | null) {
  const [rooms, setRooms] = useState<RoomSummary[] | null | "failed">(null);

  useEffect(() => {
    if (!accessToken) return;
    let cancelled = false;
    fetchMyRooms(accessToken)
      .then((next) => {
        if (!cancelled) setRooms(next);
      })
      .catch(() => {
        if (!cancelled) setRooms("failed");
      });
    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  return rooms;
}

/** Where the room stands, in the words of the person who opened it. */
function statusOf(room: RoomSummary): { label: string; tone: string } {
  switch (room.status) {
    case "halted":
      return { label: "Paused", tone: "bg-ink/10 text-muted" };
    case "resolved":
      return { label: "Agreement signed", tone: "bg-teal text-card" };
    case "joint_review":
      return { label: "Joint session", tone: "bg-teal/10 text-teal" };
    case "building_joint":
      return { label: "Preparing joint view", tone: "bg-teal/10 text-teal" };
    default:
      if (!room.other_joined) return { label: "Waiting for them to join", tone: "bg-ink/[0.06] text-muted" };
      if (room.user_a_ready && !room.user_b_ready) return { label: "Waiting for them", tone: "bg-ink/[0.06] text-muted" };
      return { label: "Talking privately", tone: "bg-terracotta/10 text-terracotta" };
  }
}

function when(value: string) {
  return new Date(value).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export function RoomList({ rooms }: { rooms: RoomSummary[] }) {
  return (
    <ul className="space-y-2">
      {rooms.map((room) => {
        const status = statusOf(room);
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
  );
}

/** Open rooms first, then the finished and paused ones. */
export function YourRooms({ rooms }: { rooms: RoomSummary[] }) {
  const open = rooms.filter(isOpenRoom);
  const past = rooms.filter((room) => !isOpenRoom(room));

  return (
    <div className="space-y-8">
      {open.length > 0 ? (
        <section>
          <h2 className="text-xs tracking-[0.15em] text-muted uppercase">Ongoing</h2>
          <div className="mt-3">
            <RoomList rooms={open} />
          </div>
        </section>
      ) : null}
      {past.length > 0 ? (
        <section>
          <h2 className="text-xs tracking-[0.15em] text-muted uppercase">Finished or paused</h2>
          <div className="mt-3">
            <RoomList rooms={past} />
          </div>
        </section>
      ) : null}
    </div>
  );
}
