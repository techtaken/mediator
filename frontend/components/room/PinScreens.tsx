"use client";

import { FormEvent, useState } from "react";

function PinField({
  label,
  value,
  onChange,
  autoFocus,
  autoComplete,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoFocus?: boolean;
  autoComplete: string;
}) {
  return (
    <label className="block text-sm text-muted">
      {label}
      <input
        type="password"
        inputMode="numeric"
        pattern="[0-9]*"
        maxLength={6}
        value={value}
        onChange={(event) => onChange(event.target.value.replace(/\D/g, ""))}
        autoFocus={autoFocus}
        autoComplete={autoComplete}
        className="mt-2 w-full rounded-2xl border border-ink/10 bg-card px-4 py-3 text-center text-xl tracking-[0.5em] text-ink outline-none focus:border-terracotta"
      />
    </label>
  );
}

/** First visit: the person who invited you has this link too, so it can't be the key. */
export function ChoosePin({ onChoose }: { onChoose: (pin: string) => Promise<void> }) {
  const [pin, setPin] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pin !== again) {
      setError("Those two PINs don't match.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await onChoose(pin);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save your PIN");
      setBusy(false);
    }
  }

  return (
    <section className="flex-1 overflow-y-auto px-4 py-6">
      <p className="text-xs font-medium tracking-[0.18em] text-terracotta uppercase">One last step</p>
      <h1 className="mt-2 font-[family-name:var(--font-display)] text-3xl leading-tight text-ink">Choose a 6-digit PIN</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-muted">
        The person who invited you has this link too. Your PIN is what keeps your room yours: without it, the link opens
        nothing. Keep it to yourself.
      </p>
      <form onSubmit={submit} className="mt-6 space-y-4">
        <PinField label="Your PIN" value={pin} onChange={setPin} autoFocus autoComplete="new-password" />
        <PinField label="Type it again" value={again} onChange={setAgain} autoComplete="new-password" />
        <ul className="list-disc space-y-1 pl-5 text-[13px] leading-relaxed text-muted">
          <li>Don&apos;t use a birthday or an easy pattern. Family can guess those.</li>
          <li>We can&apos;t show it to you again, so remember it. You&apos;ll need it each time you come back.</li>
        </ul>
        {error ? (
          <p role="alert" className="text-sm text-terracotta">
            {error}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={busy || pin.length !== 6 || again.length !== 6}
          className="w-full rounded-full bg-teal px-5 py-3.5 text-base font-medium text-card disabled:opacity-50"
        >
          {busy ? "One moment…" : "Open my private room"}
        </button>
      </form>
    </section>
  );
}

/** Coming back, or anyone else holding the link. Shows nothing about the room. */
export function EnterPin({ onEnter }: { onEnter: (pin: string) => Promise<void> }) {
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [forgot, setForgot] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onEnter(pin);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not check your PIN");
      setPin("");
      setBusy(false);
    }
  }

  return (
    <section className="px-5 py-16">
      <h1 className="font-[family-name:var(--font-display)] text-3xl leading-tight text-ink">Enter your PIN</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-muted">
        This invite has already been used. If this is your room, enter the PIN you chose when you joined.
      </p>
      <form onSubmit={submit} className="mt-6 space-y-4">
        <PinField label="Your PIN" value={pin} onChange={setPin} autoFocus autoComplete="off" />
        {error ? (
          <p role="alert" className="text-sm text-terracotta">
            {error}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={busy || pin.length !== 6}
          className="w-full rounded-full bg-teal px-5 py-3.5 text-base font-medium text-card disabled:opacity-50"
        >
          {busy ? "One moment…" : "Open my room"}
        </button>
      </form>
      <button
        type="button"
        onClick={() => setForgot((value) => !value)}
        className="mt-5 text-sm text-muted underline-offset-4 hover:underline"
      >
        Forgot your PIN, or never chose one?
      </button>
      {forgot ? (
        <p className="mt-2 text-sm leading-relaxed text-muted">
          Nobody can open this room without the PIN, including us. Ask the person who invited you to reset the invite. You&apos;ll
          get a new link and start fresh: what was written with the old one is deleted, and they never see it. If you&apos;ve
          already shared your side, they can delete this room and start a new one instead.
        </p>
      ) : null}
    </section>
  );
}
