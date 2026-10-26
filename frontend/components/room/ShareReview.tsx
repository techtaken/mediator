"use client";

import { useEffect, useState } from "react";
import { approveShare, draftShare, type AuthOpts } from "@/lib/api";
import type { Session } from "@/lib/types";

const MIN = 20;
const MAX = 1200;

type Props = {
  sessionId: string;
  auth: AuthOpts;
  onCancel: () => void;
  onShared: (session: Session) => void;
};

/**
 * The consent step. The mediator drafts a summary from this person's own chat;
 * they edit it and approve the exact words the other person will read.
 */
export function ShareReview({ sessionId, auth, onCancel, onShared }: Props) {
  const [text, setText] = useState("");
  const [leftOut, setLeftOut] = useState<string[]>([]);
  const [drafting, setDrafting] = useState(true);
  const [draftFailed, setDraftFailed] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    draftShare(sessionId, auth)
      .then((result) => {
        if (cancelled) return;
        setText(result.draft ?? "");
        setLeftOut(result.left_out ?? []);
        setDraftFailed(!result.draft);
        setDrafting(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Could not prepare a draft");
        setDraftFailed(true);
        setDrafting(false);
      });
    return () => {
      cancelled = true;
    };
    // `attempt` re-runs the draft when the person asks for a new one.
  }, [sessionId, auth, attempt]);

  function redraft() {
    setDrafting(true);
    setError("");
    setAttempt((n) => n + 1);
  }

  async function share() {
    const value = text.trim();
    if (value.length < MIN || sharing) return;
    setSharing(true);
    setError("");
    try {
      onShared(await approveShare(sessionId, value, auth));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not share right now");
      setSharing(false);
    }
  }

  const length = text.trim().length;
  const tooShort = length < MIN;

  return (
    <div
      className="fixed inset-0 z-30 flex items-end justify-center bg-ink/40 backdrop-blur-[2px] sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="share-title"
    >
      <div className="max-h-[94dvh] w-full max-w-lg overflow-y-auto rounded-t-[28px] bg-paper px-5 pt-6 pb-[max(1.25rem,env(safe-area-inset-bottom))] shadow-2xl sm:rounded-[28px]">
        <p className="text-xs font-medium tracking-[0.18em] text-terracotta uppercase">Step 2 · Review &amp; share</p>
        <h2 id="share-title" className="mt-2 font-[family-name:var(--font-display)] text-2xl leading-snug text-ink">
          This is what the other person will read
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          We drafted it from your chat. Change anything until it sounds like you.
        </p>

        <div className="mt-4 flex items-start gap-2 rounded-2xl bg-teal/10 px-3 py-2.5 text-[13px] leading-snug text-teal">
          <svg aria-hidden viewBox="0 0 20 20" fill="currentColor" className="mt-0.5 h-4 w-4 shrink-0">
            <path
              fillRule="evenodd"
              d="M10 1a4.5 4.5 0 0 0-4.5 4.5V9H5a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6a2 2 0 0 0-2-2h-.5V5.5A4.5 4.5 0 0 0 10 1Zm3 8V5.5a3 3 0 1 0-6 0V9h6Z"
              clipRule="evenodd"
            />
          </svg>
          <span>Only these words are shared. Your private chat is never shown to them.</span>
        </div>

        {drafting ? (
          <div className="mt-5 space-y-2.5" aria-live="polite" aria-busy="true">
            <p className="text-sm text-muted">Drafting a summary of your side…</p>
            {[100, 92, 96, 70].map((width) => (
              <div key={width} className="h-3.5 animate-pulse rounded-full bg-ink/10" style={{ width: `${width}%` }} />
            ))}
          </div>
        ) : (
          <>
            {draftFailed ? (
              <p className="mt-5 text-sm leading-relaxed text-ink">
                We couldn&apos;t draft this automatically. In a few lines, say what happened, how it felt, and what you
                need now.
              </p>
            ) : null}
            <label className="mt-5 block">
              <span className="sr-only">What they will read</span>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value.slice(0, MAX))}
                rows={8}
                maxLength={MAX}
                autoFocus={draftFailed}
                placeholder="I felt… What matters to me is… I'd like…"
                className="w-full resize-y rounded-2xl border border-ink/10 bg-card px-4 py-3 text-[15px] leading-relaxed text-ink outline-none focus:border-terracotta"
              />
            </label>
            <div className="mt-1.5 flex justify-between text-xs text-muted">
              <span>{tooShort ? `At least ${MIN} characters` : "Looks good"}</span>
              <span>
                {length}/{MAX}
              </span>
            </div>

            {leftOut.length ? (
              <div className="mt-4 rounded-2xl border border-ink/10 px-3 py-2.5 text-[13px] text-muted">
                <p className="font-medium text-ink">Left out to protect your privacy</p>
                <ul className="mt-1 list-disc space-y-0.5 pl-4">
                  {leftOut.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
                <p className="mt-1.5">Add any of it back if you want them to know.</p>
              </div>
            ) : null}
          </>
        )}

        {error ? (
          <p role="alert" className="mt-4 rounded-2xl bg-terracotta/10 px-3 py-2.5 text-sm text-terracotta">
            {error}
          </p>
        ) : null}

        <div className="mt-6 space-y-2.5">
          <button
            type="button"
            onClick={() => void share()}
            disabled={drafting || sharing || tooShort}
            className="w-full rounded-full bg-teal px-5 py-3.5 text-base font-medium text-card transition disabled:opacity-50"
          >
            {sharing ? "Checking and sharing…" : "Share this & I'm ready"}
          </button>
          <div className="flex gap-2.5">
            <button
              type="button"
              onClick={redraft}
              disabled={drafting || sharing}
              className="flex-1 rounded-full border border-ink/15 bg-card px-4 py-3 text-sm text-ink disabled:opacity-50"
            >
              Redraft
            </button>
            <button
              type="button"
              onClick={onCancel}
              disabled={sharing}
              className="flex-1 rounded-full px-4 py-3 text-sm text-muted underline-offset-4 hover:underline disabled:opacity-50"
            >
              Keep talking
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
