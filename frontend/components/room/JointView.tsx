"use client";

import { useState } from "react";
import { AgreementCard } from "@/components/room/AgreementCard";
import { IdeaCard } from "@/components/room/IdeaCard";
import { SuggestIdea } from "@/components/room/SuggestIdea";
import { draftAgreement, respondToIdea, signAgreement, suggestIdea, type AuthOpts } from "@/lib/api";
import type { IdeaResponse, JointState, JointSummary, Session } from "@/lib/types";

type Props = {
  session: Session;
  summary: JointSummary | null;
  joint: JointState | null;
  auth: AuthOpts;
  onJoint: (next: JointState) => void;
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

export function JointView({ session, summary, joint, auth, onJoint }: Props) {
  const [error, setError] = useState("");
  const [drafting, setDrafting] = useState(false);

  async function act(action: () => Promise<JointState>) {
    setError("");
    try {
      onJoint(await action());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      throw err;
    }
  }
  // Card-level handlers report errors here; swallow so the card's own state resets.
  const quiet = (action: () => Promise<JointState>) => act(action).catch(() => undefined);

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
  const signed = Boolean(joint?.agreement?.fully_signed);
  const open = session.status === "joint_review" && !signed;
  const answered = joint?.ideas.filter((idea) => idea.my_response).length ?? 0;

  return (
    <section className="flex-1 overflow-y-auto px-4 py-6">
      <p className="text-xs font-medium tracking-[0.18em] text-muted uppercase">Step 3 · Joint view</p>
      <h1 className="mt-2 font-[family-name:var(--font-display)] text-3xl leading-tight text-ink">
        {signed ? "You reached an agreement" : "Both sides, in your own words"}
      </h1>
      <p className="mt-2 text-[15px] leading-relaxed text-muted">
        Each of you approved exactly what&apos;s shown here. Nothing else from your private chats was shared.
      </p>

      {signed && joint?.agreement ? (
        <div className="mt-6">
          <AgreementCard agreement={joint.agreement} agreedCount={joint.agreed_count} onSign={async () => {}} onRedraft={async () => {}} />
        </div>
      ) : null}

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

      {error ? (
        <p role="alert" className="mt-5 rounded-2xl bg-terracotta/10 px-3 py-2.5 text-sm text-terracotta">
          {error}
        </p>
      ) : null}

      {open ? (
        <>
          <div className="mt-8">
            <div className="flex items-baseline justify-between gap-3">
              <h2 className="font-[family-name:var(--font-display)] text-xl text-ink">Ideas to talk through</h2>
              {joint?.ideas.length ? (
                <span className="text-xs text-muted">
                  {answered}/{joint.ideas.length} answered
                </span>
              ) : null}
            </div>
            <p className="mt-1 text-sm leading-relaxed text-muted">
              Answer each one privately. You&apos;ll see their answer once you&apos;ve given yours. Nothing is agreed until
              you both say it works.
            </p>

            {joint ? (
              <>
                {joint.ideas.length ? (
                  <ol className="mt-4 space-y-3">
                    {joint.ideas.map((idea, index) => (
                      <IdeaCard
                        key={idea.id}
                        idea={idea}
                        index={index}
                        locked={false}
                        onAnswer={(response: IdeaResponse, note: string | null) =>
                          quiet(() => respondToIdea(session.id, idea.id, response, note, auth))
                        }
                      />
                    ))}
                  </ol>
                ) : (
                  <p className="mt-4 rounded-2xl border border-dashed border-ink/15 px-4 py-3.5 text-sm leading-relaxed text-muted">
                    No ideas came out of this round yet. Reading each other&apos;s words is a good place to start. Then
                    suggest something you could both do.
                  </p>
                )}
                <SuggestIdea onSuggest={(text) => quiet(() => suggestIdea(session.id, text, auth))} />
              </>
            ) : (
              <div className="mt-4 h-24 animate-pulse rounded-3xl bg-ink/[0.06]" />
            )}
          </div>

          <div className="mt-8 border-t border-ink/10 pt-6">
            {joint?.agreement ? (
              <AgreementCard
                agreement={joint.agreement}
                agreedCount={joint.agreed_count}
                onSign={() => quiet(() => signAgreement(session.id, joint.agreement!.version, auth))}
                onRedraft={() => quiet(() => draftAgreement(session.id, auth))}
              />
            ) : joint && joint.agreed_count > 0 ? (
              <div className="rounded-3xl bg-card p-5 shadow-[0_1px_0_rgba(36,28,22,0.08)]">
                <p className="text-[15px] text-ink">
                  You both agree on {joint.agreed_count} {joint.agreed_count === 1 ? "idea" : "ideas"}.
                </p>
                <p className="mt-1 text-sm text-muted">Turn them into a short written agreement you can both sign.</p>
                <button
                  type="button"
                  disabled={drafting}
                  onClick={() => {
                    setDrafting(true);
                    void quiet(() => draftAgreement(session.id, auth)).finally(() => setDrafting(false));
                  }}
                  className="mt-4 w-full rounded-full bg-ink px-5 py-3.5 text-base text-card disabled:opacity-50"
                >
                  {drafting ? "Drafting…" : "Draft our agreement"}
                </button>
              </div>
            ) : (
              <p className="text-center text-sm leading-relaxed text-muted">
                When you both say “works for me” to an idea, you can turn it into an agreement.
              </p>
            )}
          </div>
        </>
      ) : null}
    </section>
  );
}
