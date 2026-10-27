"use client";

import { useState } from "react";

export type RoomAction = "human" | "leave" | "delete_mine" | "delete_room";

const COPY: Record<RoomAction, { title: string; body: string; confirm: string; danger: boolean }> = {
  human: {
    title: "Talk to a person instead?",
    body: "This pauses the room for both of you, and flags it for the Mediator team. The other person will only see that the session is paused, not why.",
    confirm: "Pause and ask for a person",
    danger: false,
  },
  leave: {
    title: "Leave this session?",
    body: "This ends the room for both of you. Nothing more will be shared. The other person will only see that the session is paused.",
    confirm: "Leave session",
    danger: true,
  },
  delete_mine: {
    title: "Delete your data?",
    body: "This permanently deletes your private chat with the mediator, its notes about you and your drafts. If the room is still open, it also ends the session for both of you; they only see that it's paused. Words you already shared in the joint view stay there, because the other person has read them.",
    confirm: "Delete my data",
    danger: true,
  },
  delete_room: {
    title: "Delete this whole room?",
    body: "This permanently deletes the room for both of you: both private chats, what you each shared, ideas and any agreement. It can't be undone.",
    confirm: "Delete the room",
    danger: true,
  },
};

type Props = {
  canStop: boolean;
  isA: boolean;
  onAction: (action: RoomAction) => Promise<void>;
};

function Option({ label, hint, danger, onClick }: { label: string; hint: string; danger?: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full rounded-3xl bg-card px-4 py-3.5 text-left shadow-[0_1px_0_rgba(36,28,22,0.08)]"
    >
      <span className={`block text-[15px] ${danger ? "text-terracotta" : "text-ink"}`}>{label}</span>
      <span className="block text-sm text-muted">{hint}</span>
    </button>
  );
}

/** Options to stop or delete at any time: voluntary participation is a hard rule. */
export function RoomMenu({ canStop, isA, onAction }: Props) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState<RoomAction | null>(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);

  function close() {
    setOpen(false);
    setConfirming(null);
    setTyped("");
  }

  async function run(action: RoomAction) {
    setBusy(true);
    try {
      await onAction(action);
      close();
    } finally {
      setBusy(false);
    }
  }

  // Deleting can't be undone, so it takes a typed confirmation.
  const needsTyping = confirming === "delete_mine" || confirming === "delete_room";
  const confirmed = !needsTyping || typed.trim().toLowerCase() === "delete";

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        className="rounded-full border border-ink/10 px-2.5 py-1 text-xs text-muted hover:text-ink"
      >
        Options
      </button>

      {open ? (
        <div
          className="fixed inset-0 z-30 flex items-end justify-center bg-ink/40 backdrop-blur-[2px] sm:items-center"
          role="dialog"
          aria-modal="true"
          aria-label="Session options"
          onClick={(event) => {
            if (event.target === event.currentTarget && !busy) close();
          }}
        >
          <div className="max-h-[94dvh] w-full max-w-lg overflow-y-auto rounded-t-[28px] bg-paper px-5 pt-6 pb-[max(1.25rem,env(safe-area-inset-bottom))] shadow-2xl sm:rounded-[28px]">
            {confirming ? (
              <>
                <h2 className="font-[family-name:var(--font-display)] text-2xl text-ink">{COPY[confirming].title}</h2>
                <p className="mt-2 text-[15px] leading-relaxed text-muted">{COPY[confirming].body}</p>
                {needsTyping ? (
                  <label className="mt-4 block text-sm text-ink">
                    Type <span className="font-medium">delete</span> to confirm
                    <input
                      value={typed}
                      onChange={(e) => setTyped(e.target.value)}
                      autoFocus
                      autoComplete="off"
                      className="mt-1.5 w-full rounded-full border border-ink/10 bg-card px-4 py-2.5 text-base outline-none focus:border-terracotta"
                    />
                  </label>
                ) : null}
                <div className="mt-6 space-y-2.5">
                  <button
                    type="button"
                    disabled={busy || !confirmed}
                    onClick={() => void run(confirming)}
                    className={`w-full rounded-full px-5 py-3.5 text-base text-card disabled:opacity-50 ${
                      COPY[confirming].danger ? "bg-terracotta" : "bg-teal"
                    }`}
                  >
                    {busy ? "One moment…" : COPY[confirming].confirm}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      setConfirming(null);
                      setTyped("");
                    }}
                    className="w-full rounded-full px-5 py-3 text-sm text-muted"
                  >
                    Go back
                  </button>
                </div>
              </>
            ) : (
              <>
                <h2 className="font-[family-name:var(--font-display)] text-2xl text-ink">Options</h2>
                <div className="mt-4 space-y-2.5">
                  {canStop ? (
                    <>
                      <Option
                        label="Talk to a person"
                        hint="Pause the room and ask the Mediator team for help"
                        onClick={() => setConfirming("human")}
                      />
                      <Option
                        label="Leave this session"
                        hint="Stop now. You don't have to give a reason."
                        danger
                        onClick={() => setConfirming("leave")}
                      />
                    </>
                  ) : null}
                  <Option
                    label="Delete my data"
                    hint="Remove your private chat and notes for good"
                    danger
                    onClick={() => setConfirming("delete_mine")}
                  />
                  {isA ? (
                    <Option
                      label="Delete this room"
                      hint="Remove everything, for both of you"
                      danger
                      onClick={() => setConfirming("delete_room")}
                    />
                  ) : null}
                  <button type="button" onClick={close} className="w-full rounded-full px-5 py-3 text-sm text-muted">
                    Close
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      ) : null}
    </>
  );
}
