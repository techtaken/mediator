"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { createSession } from "@/lib/api";

/** Start a new room: the topic line the other person will see, plus optional context. */
export function NewRoomForm({ accessToken }: { accessToken: string }) {
  const router = useRouter();
  const [topic, setTopic] = useState("");
  const [context, setContext] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const session = await createSession(topic.trim(), context, accessToken);
      router.push(`/room/${session.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start a room");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onCreate} className="space-y-4">
      <label className="block text-sm text-muted">
        What is this about?
        <span className="mt-1 block text-xs">
          The other person will see this line exactly as you write it, so they know why you invited them.
        </span>
        <textarea
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          required
          minLength={3}
          maxLength={300}
          rows={2}
          placeholder="e.g. You went on the Goa trip without me"
          className="mt-2 w-full resize-none rounded-2xl border border-ink/10 bg-card px-4 py-3 text-base text-ink outline-none focus:border-terracotta"
        />
      </label>
      <label className="block text-sm text-muted">
        Relationship context (optional)
        <span className="mt-1 block text-xs">
          The mediator uses this in both rooms. Say who you are to each other, not what happened.
        </span>
        <input
          value={context}
          onChange={(e) => setContext(e.target.value)}
          maxLength={500}
          placeholder="e.g. siblings sharing a flat in Pune"
          className="mt-2 w-full rounded-2xl border border-ink/10 bg-card px-4 py-3 text-base text-ink outline-none focus:border-terracotta"
        />
      </label>
      {error ? <p className="text-sm text-terracotta">{error}</p> : null}
      <button
        type="submit"
        disabled={busy || topic.trim().length < 3}
        className="w-full rounded-full bg-teal px-5 py-3.5 text-base text-card disabled:opacity-60"
      >
        {busy ? "Opening room…" : "Start a session"}
      </button>
    </form>
  );
}
