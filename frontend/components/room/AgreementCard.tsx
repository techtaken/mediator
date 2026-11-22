"use client";

import { useState } from "react";
import type { Agreement } from "@/lib/types";

function when(value: string | null) {
  return value ? new Date(value).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "";
}

const CHECKINS: { days: number; label: string }[] = [
  { days: 7, label: "1 week" },
  { days: 14, label: "2 weeks" },
  { days: 30, label: "1 month" },
  { days: 0, label: "No check-in" },
];

type Props = {
  agreement: Agreement;
  agreedCount: number;
  otherName?: string | null;
  /** checkinDays: when to privately ask this person how it's going (0 = never). */
  onSign: (checkinDays: number) => Promise<void>;
  onRedraft: () => Promise<void>;
};

export function AgreementCard({ agreement, agreedCount, otherName, onSign, onRedraft }: Props) {
  const [confirmed, setConfirmed] = useState(false);
  const [checkin, setCheckin] = useState(14);
  const [busy, setBusy] = useState<"sign" | "redraft" | null>(null);
  const outOfDate = !agreement.fully_signed && agreedCount !== agreement.terms.length;

  async function run(kind: "sign" | "redraft", action: () => Promise<void>) {
    setBusy(kind);
    try {
      await action();
    } finally {
      setBusy(null);
    }
  }

  return (
    <article className="overflow-hidden rounded-3xl bg-card shadow-[0_1px_0_rgba(36,28,22,0.08),0_12px_40px_-24px_rgba(36,28,22,0.35)]">
      {agreement.fully_signed ? (
        <div className="bg-teal px-5 py-3 text-sm text-card">
          ✓ Signed by both of you on {when(agreement.signed_by_me_at && agreement.signed_by_them_at
            ? [agreement.signed_by_me_at, agreement.signed_by_them_at].sort()[1]
            : null)}
        </div>
      ) : null}

      <div className="p-5">
        <p className="text-xs font-medium tracking-[0.18em] text-terracotta uppercase">Our agreement</p>
        {agreement.summary ? <p className="mt-3 text-[15px] leading-relaxed text-muted">{agreement.summary}</p> : null}

        <p className="mt-4 text-sm font-medium text-ink">We agree:</p>
        <ol className="mt-2 space-y-2">
          {agreement.terms.map((term, index) => (
            <li key={`${index}-${term}`} className="flex gap-3 text-[15px] leading-relaxed text-ink">
              <span className="font-[family-name:var(--font-display)] text-lg leading-none text-terracotta">{index + 1}</span>
              <span>{term}</span>
            </li>
          ))}
        </ol>

        <p className="mt-4 text-[13px] leading-relaxed text-muted">
          If something isn&apos;t working, we&apos;ll come back and talk it through. This records a voluntary understanding
          between us. It isn&apos;t legal advice or a legal contract.
        </p>

        {agreement.flags.length && !agreement.fully_signed ? (
          <div className="mt-4 rounded-2xl bg-paper px-3 py-2.5 text-[13px]">
            <p className="font-medium text-ink">Worth making more specific</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-4 text-muted">
              {agreement.flags.map((flag) => (
                <li key={flag}>{flag}</li>
              ))}
            </ul>
            <p className="mt-1.5 text-muted">Suggest a clearer version as a new idea, then redraft.</p>
          </div>
        ) : null}

        <dl className="mt-5 grid grid-cols-2 gap-2 text-[13px]">
          {[
            { label: "You", at: agreement.signed_by_me_at },
            { label: otherName ?? "Them", at: agreement.signed_by_them_at },
          ].map((row) => (
            <div key={row.label} className="rounded-2xl border border-ink/10 px-3 py-2">
              <dt className="text-muted">{row.label}</dt>
              <dd className={row.at ? "text-teal" : "text-ink"}>{row.at ? `Signed ${when(row.at)}` : "Not signed yet"}</dd>
            </div>
          ))}
        </dl>

        {outOfDate ? (
          <p className="mt-4 rounded-2xl bg-terracotta/10 px-3 py-2.5 text-[13px] text-terracotta">
            You&apos;ve agreed on more since this draft. Redraft to include everything.
          </p>
        ) : null}

        {!agreement.fully_signed ? (
          <div className="mt-5 space-y-2.5">
            {!agreement.signed_by_me_at ? (
              <>
                <label className="flex items-start gap-2.5 text-[14px] leading-snug text-ink">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(e) => setConfirmed(e.target.checked)}
                    className="mt-0.5 h-4 w-4 accent-[var(--teal)]"
                  />
                  I&apos;ve read this and I agree to it.
                </label>
                <fieldset className="rounded-2xl border border-ink/10 px-3 py-2.5">
                  <legend className="px-1 text-[13px] text-muted">Check in with me privately in</legend>
                  <div className="mt-1 grid grid-cols-4 gap-1.5">
                    {CHECKINS.map((option) => (
                      <button
                        key={option.days}
                        type="button"
                        aria-pressed={checkin === option.days}
                        onClick={() => setCheckin(option.days)}
                        className={`rounded-full px-1.5 py-1.5 text-[12px] leading-tight transition ${
                          checkin === option.days ? "bg-ink text-card" : "border border-ink/15 bg-paper text-ink"
                        }`}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                  <p className="mt-1.5 px-1 text-[12px] text-muted">
                    We&apos;ll ask how it&apos;s going. Your answers stay private.
                  </p>
                </fieldset>
                <button
                  type="button"
                  disabled={!confirmed || busy !== null}
                  onClick={() => void run("sign", () => onSign(checkin))}
                  className="w-full rounded-full bg-teal px-5 py-3.5 text-base font-medium text-card disabled:opacity-50"
                >
                  {busy === "sign" ? "Signing…" : "Sign this agreement"}
                </button>
              </>
            ) : (
              <p className="text-center text-sm text-muted">You&apos;ve signed. Waiting for {otherName ?? "them"} to sign.</p>
            )}
            {outOfDate ? (
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => void run("redraft", onRedraft)}
                className="w-full rounded-full px-5 py-2.5 text-sm text-muted underline-offset-4 hover:underline disabled:opacity-50"
              >
                {busy === "redraft" ? "Updating…" : "Update the draft to match your ideas (clears signatures)"}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </article>
  );
}
