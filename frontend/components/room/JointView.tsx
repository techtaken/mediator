"use client";

import type { JointSummary, Session } from "@/lib/types";

type Props = {
  session: Session;
  summary: JointSummary | null;
  busy: boolean;
  onResolve: () => void;
};

function Voice({ label, text, tone }: { label: string; text: string; tone: "mine" | "theirs" }) {
  return (
    <figure
      className={`rounded-3xl p-5 ${
        tone === "mine" ? "bg-card shadow-[0_1px_0_rgba(36,28,22,0.08)]" : "border border-ink/10 bg-paper"
      }`}
    >
      <figcaption className="text-xs font-medium tracking-[0.16em] text-terracotta uppercase">{label}</figcaption>
      <blockquote className="mt-3 text-[15px] leading-relaxed whitespace-pre-wrap text-ink">{text}</blockquote>
    </figure>
  );
}

export function JointView({ session, summary, busy, onResolve }: Props) {
  if (!summary) {
    return (
      <section className="flex-1 px-4 py-8" aria-busy="true" aria-live="polite">
        <p className="text-xs font-medium tracking-[0.18em] text-muted uppercase">Step 3 · Joint view</p>
        <h1 className="mt-2 font-[family-name:var(--font-display)] text-3xl text-ink">Preparing your joint view…</h1>
        <div className="mt-6 space-y-3">
          {[0, 1].map((key) => (
            <div key={key} className="h-28 animate-pulse rounded-3xl bg-ink/[0.06]" />
          ))}
        </div>
      </section>
    );
  }

  const isA = session.party === "user_a";
  const mine = isA ? summary.user_a_perspective : summary.user_b_perspective;
  const theirs = isA ? summary.user_b_perspective : summary.user_a_perspective;

  return (
    <section className="flex-1 overflow-y-auto px-4 py-6">
      <p className="text-xs font-medium tracking-[0.18em] text-muted uppercase">Step 3 · Joint view</p>
      <h1 className="mt-2 font-[family-name:var(--font-display)] text-3xl leading-tight text-ink">
        Both sides, in your own words
      </h1>
      <p className="mt-2 text-[15px] leading-relaxed text-muted">
        Each of you approved exactly what&apos;s shown here. Nothing else from your private chats was shared.
      </p>

      <div className="mt-6 space-y-3">
        <Voice label="The other person" text={theirs} tone="theirs" />
        <Voice label="You" text={mine} tone="mine" />
      </div>

      {summary.common_ground ? (
        <div className="mt-5 rounded-3xl bg-teal p-5 text-card">
          <h2 className="text-xs font-medium tracking-[0.16em] uppercase opacity-80">Where you overlap</h2>
          <p className="mt-2 text-[15px] leading-relaxed">{summary.common_ground}</p>
        </div>
      ) : null}

      <div className="mt-7">
        <h2 className="font-[family-name:var(--font-display)] text-xl text-ink">Ideas to talk through</h2>
        {summary.compromises.length ? (
          <>
            <p className="mt-1 text-sm text-muted">Possibilities, not recommendations. Neither of you has agreed to anything.</p>
            <ol className="mt-4 space-y-2.5">
              {summary.compromises.map((item, index) => (
                <li key={`${index}-${item}`} className="flex gap-3 rounded-2xl bg-card px-4 py-3.5 shadow-[0_1px_0_rgba(36,28,22,0.08)]">
                  <span className="font-[family-name:var(--font-display)] text-lg leading-none text-terracotta">{index + 1}</span>
                  <span className="text-[15px] leading-relaxed text-ink">{item}</span>
                </li>
              ))}
            </ol>
          </>
        ) : (
          <p className="mt-2 rounded-2xl border border-dashed border-ink/15 px-4 py-3.5 text-sm leading-relaxed text-muted">
            No specific ideas came out of this round. Reading each other&apos;s words is often the best place to start the
            conversation.
          </p>
        )}
      </div>

      <div className="mt-8 border-t border-ink/10 pt-5">
        {session.status === "resolved" ? (
          <p className="text-center text-sm text-teal">✓ Marked as resolved</p>
        ) : (
          <button
            type="button"
            disabled={busy}
            onClick={onResolve}
            className="w-full rounded-full bg-ink px-5 py-3.5 text-base text-card disabled:opacity-50"
          >
            {busy ? "Saving…" : "We've worked this out"}
          </button>
        )}
      </div>
    </section>
  );
}
