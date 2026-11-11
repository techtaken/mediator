"use client";

import { FormEvent, useState } from "react";

type Props = {
  initial?: string;
  onSave: (name: string) => Promise<void>;
  onCancel?: () => void;
};

/** Person A's profile: asked once after signing in, and changeable later. */
export function NameForm({ initial = "", onSave, onCancel }: Props) {
  const [name, setName] = useState(initial);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onSave(name);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save your name");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <h1 className="font-[family-name:var(--font-display)] text-3xl leading-tight text-ink">What should we call you?</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-muted">
        The person you invite will see this name, and the mediator will use it. Your first name is fine.
      </p>
      <label className="mt-6 block text-sm text-muted">
        Your name
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
          autoFocus
          maxLength={40}
          autoComplete="given-name"
          className="mt-2 w-full rounded-2xl border border-ink/10 bg-card px-4 py-3 text-base text-ink outline-none focus:border-terracotta"
        />
      </label>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-terracotta">
          {error}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={busy || !name.trim()}
        className="mt-5 w-full rounded-full bg-teal px-5 py-3.5 text-base text-card disabled:opacity-60"
      >
        {busy ? "One moment…" : "Continue"}
      </button>
      {onCancel ? (
        <button type="button" onClick={onCancel} className="mt-2 w-full rounded-full px-5 py-3 text-sm text-muted">
          Cancel
        </button>
      ) : null}
    </form>
  );
}
