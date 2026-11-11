"use client";

import Link from "next/link";
import { useState } from "react";
import { isOpenRoom, statusOf, useMyRooms } from "@/components/YourRooms";
import { getSupabase } from "@/lib/supabase";
import type { RoomSummary } from "@/lib/types";

type Props = {
  accessToken: string;
  name: string | null;
  children: React.ReactNode;
  /** Highlights this room in the list. */
  activeRoomId?: string;
  /** Shown instead of the link to change one's name, where the page can do it in place. */
  onChangeName?: () => void;
  /** Pages with their own top bar on phones (a room) skip the shell's. */
  ownMobileHeader?: boolean;
};

function RoomRow({ room, active, onPick }: { room: RoomSummary; active: boolean; onPick: () => void }) {
  const status = statusOf(room);
  return (
    <li>
      <Link
        href={`/room/${room.id}`}
        onClick={onPick}
        aria-current={active ? "page" : undefined}
        className={`block rounded-2xl px-3 py-2.5 ${active ? "bg-paper shadow-[0_1px_0_rgba(36,28,22,0.06)]" : "hover:bg-paper/60"}`}
      >
        <span className="block truncate text-sm text-ink">{room.topic ?? "Untitled conversation"}</span>
        <span className="mt-0.5 block truncate text-xs text-muted">
          {room.role === "invited" ? `Invited by ${room.other_name ?? "someone"} · ` : ""}
          {status.label}
        </span>
      </Link>
    </li>
  );
}

function Sidebar({ accessToken, name, activeRoomId, onChangeName, onPick }: Omit<Props, "children" | "ownMobileHeader"> & { onPick: () => void }) {
  const rooms = useMyRooms(accessToken);
  const list = Array.isArray(rooms) ? rooms : [];
  const ongoing = list.filter(isOpenRoom);
  const past = list.filter((room) => !isOpenRoom(room));

  return (
    <div className="flex h-full flex-col">
      <div className="px-5 pt-6">
        <Link href="/" onClick={onPick} className="text-sm tracking-[0.2em] text-terracotta uppercase">
          Mediator
        </Link>
        <Link
          href="/"
          onClick={onPick}
          className="mt-5 flex w-full items-center justify-center gap-2 rounded-full bg-teal px-4 py-2.5 text-sm text-card"
        >
          <span aria-hidden="true" className="text-base leading-none">+</span> New conversation
        </Link>
      </div>

      <nav aria-label="Your conversations" className="mt-6 flex-1 overflow-y-auto px-2 pb-4">
        {rooms === null ? (
          <div className="space-y-2 px-3" aria-label="Loading your conversations">
            <div className="h-10 animate-pulse rounded-2xl bg-ink/[0.05]" />
            <div className="h-10 animate-pulse rounded-2xl bg-ink/[0.05]" />
          </div>
        ) : rooms === "failed" ? (
          <p className="px-3 text-xs text-muted">Couldn&apos;t load your conversations.</p>
        ) : list.length === 0 ? (
          <p className="px-3 text-xs leading-relaxed text-muted">Your conversations will show up here.</p>
        ) : (
          <>
            {ongoing.length ? (
              <>
                <h2 className="px-3 text-[11px] tracking-[0.15em] text-muted uppercase">Ongoing</h2>
                <ul className="mt-1.5 space-y-0.5">
                  {ongoing.map((room) => (
                    <RoomRow key={room.id} room={room} active={room.id === activeRoomId} onPick={onPick} />
                  ))}
                </ul>
              </>
            ) : null}
            {past.length ? (
              <>
                <h2 className="mt-5 px-3 text-[11px] tracking-[0.15em] text-muted uppercase">Finished or paused</h2>
                <ul className="mt-1.5 space-y-0.5">
                  {past.map((room) => (
                    <RoomRow key={room.id} room={room} active={room.id === activeRoomId} onPick={onPick} />
                  ))}
                </ul>
              </>
            ) : null}
          </>
        )}
      </nav>

      <div className="flex items-center justify-between gap-3 border-t border-ink/10 px-5 py-4 text-sm">
        {onChangeName ? (
          <button type="button" onClick={onChangeName} className="min-w-0 truncate text-ink underline-offset-4 hover:underline" title="Change your name">
            {name ?? "Your name"}
          </button>
        ) : (
          <Link href="/?change=name" onClick={onPick} className="min-w-0 truncate text-ink underline-offset-4 hover:underline" title="Change your name">
            {name ?? "Your name"}
          </Link>
        )}
        <button type="button" onClick={() => void getSupabase().auth.signOut()} className="shrink-0 text-muted underline-offset-4 hover:underline">
          Sign out
        </button>
      </div>
    </div>
  );
}

/** Signed-in layout: conversations in a sidebar (a drawer on phones), the page beside it. */
export function AppShell({ children, ownMobileHeader = false, ...sidebar }: Props) {
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);

  return (
    <div className="flex h-[100dvh]">
      <aside className="hidden w-72 shrink-0 border-r border-ink/10 bg-card/70 md:block">
        <Sidebar {...sidebar} onPick={close} />
      </aside>

      {open ? (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Your conversations">
          <button type="button" aria-label="Close menu" onClick={close} className="absolute inset-0 bg-ink/30 backdrop-blur-[2px]" />
          <div className="relative h-full w-[85%] max-w-xs bg-card shadow-2xl">
            <Sidebar {...sidebar} onPick={close} />
          </div>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        {ownMobileHeader ? null : (
          <div className="flex items-center gap-3 px-4 pt-4 md:hidden">
            <button
              type="button"
              onClick={() => setOpen(true)}
              aria-label="Your conversations"
              className="rounded-full border border-ink/10 p-2 text-ink"
            >
              <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
                <path d="M3 6h14M3 10h14M3 14h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </button>
            <span className="text-sm tracking-[0.2em] text-terracotta uppercase">Mediator</span>
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}
