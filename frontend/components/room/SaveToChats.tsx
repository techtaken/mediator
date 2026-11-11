"use client";

import Link from "next/link";
import { useState } from "react";
import type { Session } from "@/lib/types";

type Props = {
  session: Session;
  signedInEmail: string | null;
  onSave: () => Promise<void>;
};

/** The invited person can keep the room in their chats. Always asked, never automatic:
 * a shared browser may be signed in as someone else. */
export function SaveToChats({ session, signedInEmail, onSave }: Props) {
  const [dismissed, setDismissed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (session.party !== "user_b" || session.needs_pin) return null;
  if (session.saved_to === "you") {
    return <p className="mx-4 mt-3 px-1 text-xs text-teal">Saved to your chats</p>;
  }
  if (session.saved_to === "another account") {
    return (
      <p className="mx-4 mt-3 px-1 text-xs text-muted">
        Saved to another account. If that wasn&apos;t you, remove it from Options.
      </p>
    );
  }
  if (dismissed) return null;

  async function save() {
    setBusy(true);
    setError("");
    try {
      await onSave();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save this conversation");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-4 mt-3 rounded-2xl border border-ink/10 bg-card px-3 py-3 text-sm">
      {signedInEmail ? (
        <p className="text-ink">
          Keep this conversation in your chats? You&apos;re signed in as <span className="font-medium">{signedInEmail}</span>.
          <span className="block text-xs text-muted">
            Only save it if this is your account. You&apos;ll still need your PIN to open it.
          </span>
        </p>
      ) : (
        <p className="text-ink">
          Want to keep this conversation? Sign in to save it to your chats.
          <span className="block text-xs text-muted">You&apos;ll still need your PIN to open it.</span>
        </p>
      )}
      {error ? (
        <p role="alert" className="mt-2 text-xs text-terracotta">
          {error}
        </p>
      ) : null}
      <div className="mt-2.5 flex gap-2">
        {signedInEmail ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => void save()}
            className="rounded-full bg-teal px-3.5 py-1.5 text-sm text-card disabled:opacity-50"
          >
            {busy ? "Saving…" : "Save to my chats"}
          </button>
        ) : (
          <Link
            href={`/login?next=${encodeURIComponent(`/room/${session.id}`)}`}
            className="rounded-full bg-teal px-3.5 py-1.5 text-sm text-card"
          >
            Sign in to save
          </Link>
        )}
        <button type="button" onClick={() => setDismissed(true)} className="rounded-full px-3 py-1.5 text-sm text-muted">
          Not now
        </button>
      </div>
    </div>
  );
}
