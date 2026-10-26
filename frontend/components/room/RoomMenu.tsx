"use client";

import { useState } from "react";

type Action = "human" | "leave";

const COPY: Record<Action, { title: string; body: string; confirm: string }> = {
  human: {
    title: "Talk to a person instead?",
    body: "This pauses the room for both of you, and flags it for the Mediator team. The other person will only see that the session is paused, not why.",
    confirm: "Pause and ask for a person",
  },
  leave: {
    title: "Leave this session?",
    body: "This ends the room for both of you. Nothing more will be shared. The other person will only see that the session is paused.",
    confirm: "Leave session",
  },
};

/** Options to stop at any time: voluntary participation is a hard rule. */
export function RoomMenu({ onAction }: { onAction: (action: Action) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState<Action | null>(null);
  const [busy, setBusy] = useState(false);

  function close() {
    setOpen(false);
    setConfirming(null);
  }

  async function run(action: Action) {
    setBusy(true);
    try {
      await onAction(action);
      close();
    } finally {
      setBusy(false);
    }
  }

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
          <div className="w-full max-w-lg rounded-t-[28px] bg-paper px-5 pt-6 pb-[max(1.25rem,env(safe-area-inset-bottom))] shadow-2xl sm:rounded-[28px]">
            {confirming ? (
              <>
                <h2 className="font-[family-name:var(--font-display)] text-2xl text-ink">{COPY[confirming].title}</h2>
                <p className="mt-2 text-[15px] leading-relaxed text-muted">{COPY[confirming].body}</p>
                <div className="mt-6 space-y-2.5">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void run(confirming)}
                    className={`w-full rounded-full px-5 py-3.5 text-base text-card disabled:opacity-50 ${
                      confirming === "leave" ? "bg-terracotta" : "bg-teal"
                    }`}
                  >
                    {busy ? "One moment…" : COPY[confirming].confirm}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => setConfirming(null)}
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
                  <button
                    type="button"
                    onClick={() => setConfirming("human")}
                    className="w-full rounded-3xl bg-card px-4 py-3.5 text-left shadow-[0_1px_0_rgba(36,28,22,0.08)]"
                  >
                    <span className="block text-[15px] text-ink">Talk to a person</span>
                    <span className="block text-sm text-muted">Pause the room and ask the Mediator team for help</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirming("leave")}
                    className="w-full rounded-3xl bg-card px-4 py-3.5 text-left shadow-[0_1px_0_rgba(36,28,22,0.08)]"
                  >
                    <span className="block text-[15px] text-terracotta">Leave this session</span>
                    <span className="block text-sm text-muted">Stop now. You don&apos;t have to give a reason.</span>
                  </button>
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
