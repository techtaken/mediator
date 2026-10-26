"use client";

type Props = {
  shared: string;
  otherReady: boolean;
  busy: boolean;
  onWithdraw: () => void;
  onRetry: () => void;
};

/** Shown after this person has shared, until the joint view opens. */
export function WaitingPanel({ shared, otherReady, busy, onWithdraw, onRetry }: Props) {
  return (
    <section className="flex-1 overflow-y-auto px-4 py-6">
      <div className="flex items-center gap-2 text-sm text-teal" aria-live="polite">
        <span className="relative flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-teal/50" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-teal" />
        </span>
        {otherReady ? "You've both shared" : "Waiting for the other person to finish"}
      </div>

      <h1 className="mt-4 font-[family-name:var(--font-display)] text-3xl leading-tight text-ink">
        You&apos;ve shared your side
      </h1>
      <p className="mt-2 text-[15px] leading-relaxed text-muted">
        {otherReady
          ? "Your joint view is being prepared. If it doesn't open in a moment, try again below."
          : "When they share theirs, you'll both see each other's words side by side. This page updates on its own."}
      </p>

      <figure className="mt-6 rounded-3xl bg-card p-5 shadow-[0_1px_0_rgba(36,28,22,0.08)]">
        <figcaption className="text-xs font-medium tracking-[0.16em] text-muted uppercase">What they will read</figcaption>
        <blockquote className="mt-3 text-[15px] leading-relaxed whitespace-pre-wrap text-ink">{shared}</blockquote>
      </figure>

      {otherReady ? (
        <button
          type="button"
          onClick={onRetry}
          disabled={busy}
          className="mt-5 w-full rounded-full bg-teal px-5 py-3 text-sm text-card disabled:opacity-50"
        >
          {busy ? "Preparing…" : "Open the joint view"}
        </button>
      ) : (
        <button
          type="button"
          onClick={onWithdraw}
          disabled={busy}
          className="mt-5 w-full rounded-full border border-ink/15 bg-card px-5 py-3 text-sm text-ink disabled:opacity-50"
        >
          {busy ? "Withdrawing…" : "Withdraw and keep talking"}
        </button>
      )}
    </section>
  );
}
