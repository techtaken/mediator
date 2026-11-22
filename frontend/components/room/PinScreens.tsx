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

const ASCENDING = "01234567890";
const DESCENDING = "09876543210";

/** The PIN rules, checked as the person types. Dates are checked by the server. */
function pinRules(pin: string) {
  const full = pin.length === 6;
  const pattern = new Set(pin).size <= 2 || pin.slice(0, 3) === pin.slice(3) || ASCENDING.includes(pin) || DESCENDING.includes(pin);
  return [
    { label: `Exactly 6 digits (${pin.length}/6)`, ok: full },
    { label: "Numbers only", ok: pin.length > 0 && /^\d+$/.test(pin) },
    { label: "Not a pattern like 111111, 121212 or 123456", ok: full && !pattern },
    { label: "Not a date or birthday, like 150890", ok: false },
  ];
}

function PinRules({ pin }: { pin: string }) {
  return (
    <div className="rounded-2xl bg-card px-4 py-3 shadow-[0_1px_0_rgba(36,28,22,0.08)]">
      <p className="text-sm font-medium text-ink">PIN rules</p>
      <ul className="mt-2 space-y-1.5 text-[13px] leading-snug">
        {pinRules(pin).map((rule) => (
          <li key={rule.label} className={`flex items-start gap-2 ${rule.ok ? "text-teal" : "text-muted"}`}>
            <span aria-hidden="true" className="w-4 shrink-0 text-center">
              {rule.ok ? "✓" : "•"}
            </span>
            <span>
              {rule.label}
              {rule.ok ? <span className="sr-only"> (done)</span> : null}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

type ChoosePinProps = {
  inviter: string | null;
  invitedAs: string | null;
  onChoose: (pin: string, name: string) => Promise<void>;
};

/** First visit: the person who invited you has this link too, so it can't be the key. */
export function ChoosePin({ inviter, invitedAs, onChoose }: ChoosePinProps) {
  const [name, setName] = useState(invitedAs ?? "");
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
      await onChoose(pin, name);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save your PIN");
      setBusy(false);
    }
  }

  return (
    <section className="flex-1 overflow-y-auto px-4 py-6">
      <p className="text-xs font-medium tracking-[0.18em] text-terracotta uppercase">One last step</p>
      <h1 className="mt-2 font-[family-name:var(--font-display)] text-3xl leading-tight text-ink">Your name and a PIN</h1>
      <form onSubmit={submit} className="mt-6 space-y-4">
        <label className="block text-sm text-muted">
          Your name
          <span className="mt-1 block text-xs">
            {inviter ?? "The person who invited you"} will see this, and the mediator will use it.
            {invitedAs ? " Change it if you'd rather be called something else." : ""}
          </span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            autoFocus
            maxLength={40}
            autoComplete="given-name"
            className="mt-2 w-full rounded-2xl border border-ink/10 bg-card px-4 py-3 text-base text-ink outline-none focus:border-terracotta"
          />
        </label>
        <p className="text-[15px] leading-relaxed text-muted">
          {inviter ?? "The person who invited you"} has this link too. A 6-digit PIN is what keeps your room yours: without
          it, the link opens nothing. Keep it to yourself.
        </p>
        <PinField label="Choose a PIN" value={pin} onChange={setPin} autoComplete="new-password" />
        <PinRules pin={pin} />
        <PinField label="Type it again" value={again} onChange={setAgain} autoComplete="new-password" />
        <p className="text-[13px] leading-relaxed text-muted">
          We can&apos;t show your PIN again, so remember it. You&apos;ll need it each time you come back.
        </p>
        {error ? (
          <p role="alert" className="text-sm text-terracotta">
            {error}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={busy || !name.trim() || pin.length !== 6 || again.length !== 6}
          className="w-full rounded-full bg-teal px-5 py-3.5 text-base font-medium text-card disabled:opacity-50"
        >
          {busy ? "One moment…" : "Open my private room"}
        </button>
      </form>
    </section>
  );
}

/** Coming back, or anyone else holding the link. Shows nothing about the room. */
type EnterPinProps = {
  onEnter: (pin: string) => Promise<void>;
  /** invite: opened from the link. chats: from their saved chats. signin: just signed in to save it. */
  reason?: "invite" | "chats" | "signin";
};

const ENTER_PIN_COPY = {
  invite: "This invite has already been used. If this is your room, enter the PIN you chose when you joined.",
  chats: "Enter the PIN you chose when you joined this conversation.",
  signin: "You're signed in. Enter the PIN you chose when you joined, and then you can save this conversation.",
};

export function EnterPin({ onEnter, reason = "invite" }: EnterPinProps) {
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
        {ENTER_PIN_COPY[reason]}
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
