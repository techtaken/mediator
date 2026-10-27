"use client";

import { useState } from "react";

function points(retentionDays: number): { title: string; body: string }[] {
  return [
  {
    title: "You're talking to an AI",
    body: "Mediator is an AI. It doesn't take sides, and it can't give legal, medical or financial advice.",
  },
  {
    title: "This room is private",
    body: "The other person never sees your chat. They only see words you review and approve.",
  },
  {
    title: "The Mediator team can see conversations",
    body: "A small team can read rooms to keep the service safe and to help if you ask for a person. Each time they open a room, it's recorded.",
  },
  {
    title: "You control your data",
    body: `Delete your private chat any time from Options. ${
      retentionDays > 0 ? `Rooms are removed automatically after ${retentionDays} days. ` : ""
    }The mediator's working notes on each step are cleared after 30 days.`,
  },
  {
    title: "You can stop at any time",
    body: "Leave whenever you want, or ask to talk to a person instead.",
  },
  {
    title: "Not for emergencies",
    body: "If anyone is in danger, call 112. Mediator pauses if someone may be unsafe.",
  },
  ];
}

/** Shown before a person's first message. Accepting is recorded on the server. */
export function ConsentCard({ retentionDays, onAccept }: { retentionDays: number; onAccept: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);

  async function accept() {
    setBusy(true);
    try {
      await onAccept();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="flex-1 overflow-y-auto px-4 py-6">
      <p className="text-xs font-medium tracking-[0.18em] text-terracotta uppercase">Before we start</p>
      <h1 className="mt-2 font-[family-name:var(--font-display)] text-3xl leading-tight text-ink">How Mediator works</h1>

      <ul className="mt-6 space-y-3">
        {points(retentionDays).map((point, index) => (
          <li key={point.title} className="flex gap-3 rounded-3xl bg-card p-4 shadow-[0_1px_0_rgba(36,28,22,0.08)]">
            <span className="font-[family-name:var(--font-display)] text-lg leading-none text-terracotta">{index + 1}</span>
            <span>
              <span className="block text-[15px] font-medium text-ink">{point.title}</span>
              <span className="mt-0.5 block text-sm leading-relaxed text-muted">{point.body}</span>
            </span>
          </li>
        ))}
      </ul>

      <button
        type="button"
        onClick={() => void accept()}
        disabled={busy}
        className="mt-6 w-full rounded-full bg-teal px-5 py-3.5 text-base font-medium text-card disabled:opacity-50"
      >
        {busy ? "One moment…" : "I understand, let's start"}
      </button>
      <p className="mt-3 text-center text-xs text-muted">You can leave at any time from the menu at the top.</p>
    </section>
  );
}
