"use client";

import { useState } from "react";
import type { CheckInAnswers, FollowUp, TermStatus } from "@/lib/types";

const STATUS: { value: TermStatus; label: string }[] = [
  { value: "kept", label: "Working" },
  { value: "partly", label: "Partly" },
  { value: "not_kept", label: "Not working" },
];

const FEELING = ["Not well", "Not great", "Okay", "Good", "Very well"];

function when(value: string | null) {
  return value ? new Date(value).toLocaleDateString(undefined, { day: "numeric", month: "long" }) : "";
}

type Props = {
  followUp: FollowUp;
  onAnswer: (answers: CheckInAnswers) => Promise<void>;
  onReopen: () => Promise<void>;
};

/** A private check-in after the agreement. Nobody sees the other person's answers. */
export function FollowUpCard({ followUp, onAnswer, onReopen }: Props) {
  const [terms, setTerms] = useState<Record<number, TermStatus>>({});
  const [feeling, setFeeling] = useState<number | null>(null);
  const [newIssues, setNewIssues] = useState("");
  const [talk, setTalk] = useState(false);
  const [busy, setBusy] = useState(false);

  if (followUp.status === "none") return null;

  if (followUp.status === "scheduled") {
    return (
      <div className="rounded-3xl border border-ink/10 bg-paper px-5 py-4 text-sm leading-relaxed text-muted">
        We&apos;ll check in with you privately around <span className="text-ink">{when(followUp.due_at)}</span> to ask how
        it&apos;s going. Just open this room then.
      </div>
    );
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  }

  if (followUp.status === "answered") {
    const differ = followUp.accounts_differ;
    return (
      <article className="rounded-3xl bg-card p-5 shadow-[0_1px_0_rgba(36,28,22,0.08)]">
        <p className="text-xs font-medium tracking-[0.18em] text-terracotta uppercase">Your check-in</p>
        {followUp.reply ? <p className="mt-3 text-[15px] leading-relaxed whitespace-pre-wrap text-ink">{followUp.reply}</p> : null}
        <p className="mt-3 text-[13px] text-muted">Your answers are private. The other person never sees them.</p>

        {followUp.other_answered ? (
          differ.length ? (
            <div className="mt-4 rounded-2xl bg-paper px-3 py-2.5 text-[14px] leading-relaxed text-ink">
              <p className="font-medium">Your accounts differ</p>
              <p className="mt-1 text-muted">
                You and the other person see {differ.length === 1 ? "term" : "terms"}{" "}
                {differ.join(", ")} differently. That&apos;s common. Mediator doesn&apos;t decide who&apos;s right; talking it
                through together can help.
              </p>
            </div>
          ) : (
            <p className="mt-4 text-[14px] text-teal">You both described the terms the same way.</p>
          )
        ) : followUp.other_checking_in ? (
          <p className="mt-4 text-[13px] text-muted">The other person hasn&apos;t checked in yet.</p>
        ) : null}

        {followUp.can_reopen ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => void run(onReopen)}
            className="mt-5 w-full rounded-full border border-ink/15 bg-paper px-5 py-3 text-sm text-ink disabled:opacity-50"
          >
            {busy ? "Opening…" : "Talk it through together again"}
          </button>
        ) : null}
      </article>
    );
  }

  const complete = followUp.terms.every((_, index) => terms[index]) && feeling !== null;

  return (
    <article className="rounded-3xl bg-card p-5 shadow-[0_1px_0_rgba(36,28,22,0.08),0_12px_40px_-24px_rgba(36,28,22,0.35)]">
      <p className="text-xs font-medium tracking-[0.18em] text-terracotta uppercase">Check-in</p>
      <h2 className="mt-2 font-[family-name:var(--font-display)] text-2xl leading-snug text-ink">How is it going?</h2>
      <p className="mt-1 text-sm leading-relaxed text-muted">Only you and the mediator see your answers.</p>

      <ol className="mt-4 space-y-4">
        {followUp.terms.map((term, index) => (
          <li key={`${index}-${term}`}>
            <p className="flex gap-2.5 text-[15px] leading-relaxed text-ink">
              <span className="font-[family-name:var(--font-display)] text-lg leading-none text-terracotta">{index + 1}</span>
              <span>{term}</span>
            </p>
            <div className="mt-2 grid grid-cols-3 gap-1.5" role="group" aria-label={`How term ${index + 1} is going`}>
              {STATUS.map((choice) => {
                const selected = terms[index] === choice.value;
                return (
                  <button
                    key={choice.value}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => setTerms((prev) => ({ ...prev, [index]: choice.value }))}
                    className={`rounded-full px-2 py-2 text-[13px] transition ${
                      selected ? "bg-ink text-card" : "border border-ink/15 bg-paper text-ink hover:border-ink/30"
                    }`}
                  >
                    {choice.label}
                  </button>
                );
              })}
            </div>
          </li>
        ))}
      </ol>

      <fieldset className="mt-5">
        <legend className="text-sm text-ink">Overall, how do you feel about things between you?</legend>
        <div className="mt-2 grid grid-cols-5 gap-1.5">
          {FEELING.map((label, index) => (
            <button
              key={label}
              type="button"
              aria-pressed={feeling === index + 1}
              onClick={() => setFeeling(index + 1)}
              className={`rounded-2xl px-1 py-2 text-[12px] leading-tight transition ${
                feeling === index + 1 ? "bg-teal text-card" : "border border-ink/15 bg-paper text-ink"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </fieldset>

      <label className="mt-5 block text-sm text-ink">
        Anything new on your mind? <span className="text-muted">(optional, private)</span>
        <textarea
          value={newIssues}
          onChange={(e) => setNewIssues(e.target.value.slice(0, 500))}
          rows={3}
          maxLength={500}
          className="mt-1.5 w-full resize-none rounded-2xl border border-ink/10 bg-paper px-3 py-2 text-[15px] text-ink outline-none focus:border-terracotta"
        />
      </label>

      <label className="mt-3 flex items-start gap-2.5 text-[14px] leading-snug text-ink">
        <input
          type="checkbox"
          checked={talk}
          onChange={(e) => setTalk(e.target.checked)}
          className="mt-0.5 h-4 w-4 accent-[var(--teal)]"
        />
        I&apos;d like to talk some of this through together again
      </label>

      <button
        type="button"
        disabled={!complete || busy}
        onClick={() =>
          void run(() =>
            onAnswer({
              term_status: followUp.terms.map((_, index) => ({ term: index, status: terms[index] })),
              satisfaction: feeling ?? 3,
              new_issues: newIssues.trim() || null,
              wants_to_talk: talk,
            }),
          )
        }
        className="mt-5 w-full rounded-full bg-teal px-5 py-3.5 text-base font-medium text-card disabled:opacity-50"
      >
        {busy ? "Sending…" : "Send my check-in"}
      </button>
    </article>
  );
}
