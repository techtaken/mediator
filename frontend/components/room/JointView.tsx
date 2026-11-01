"use client";

import { useState } from "react";
import { AgreementCard } from "@/components/room/AgreementCard";
import { FollowUpCard } from "@/components/room/FollowUpCard";
import { IdeaCard } from "@/components/room/IdeaCard";
import { SuggestIdea } from "@/components/room/SuggestIdea";
import {
  answerFollowUp,
  draftAgreement,
  fetchTranslation,
  reopenJoint,
  respondToIdea,
  signAgreement,
  suggestIdea,
  thinkItThrough,
  type AuthOpts,
} from "@/lib/api";
import type { FollowUp, IdeaResponse, JointState, JointSummary, Language, Session, Translation } from "@/lib/types";

type Props = {
  session: Session;
  summary: JointSummary | null;
  joint: JointState | null;
  followUp: FollowUp | null;
  auth: AuthOpts;
  onJoint: (next: JointState) => void;
  onFollowUp: (next: FollowUp) => void;
};

const LANGUAGE_LABEL: Record<Language, string> = { en: "English", hinglish: "Hinglish", hi: "हिन्दी" };

/** Their approved words, with an optional, clearly labelled translation. The original always shows. */
function TheirWords({ session, text, auth }: { session: Session; text: string; auth: AuthOpts }) {
  const [translation, setTranslation] = useState<Translation | null>(null);
  const [loading, setLoading] = useState<Language | null>(null);
  const [failed, setFailed] = useState(false);
  const preferred = session.my_language ?? "en";
  const choices: Language[] = [preferred, ...(["en", "hinglish", "hi"] as Language[]).filter((code) => code !== preferred)];

  async function translate(language: Language) {
    setLoading(language);
    setFailed(false);
    try {
      const result = await fetchTranslation(session.id, language, auth);
      setTranslation(result);
      setFailed(!result.translation);
    } catch {
      setFailed(true);
    } finally {
      setLoading(null);
    }
  }

  return (
    <figure className="rounded-3xl border border-ink/10 bg-paper p-5">
      <figcaption className="text-xs font-medium tracking-[0.16em] text-terracotta uppercase">{session.other_name ?? "The other person"}</figcaption>
      <blockquote className="mt-3 text-[15px] leading-relaxed whitespace-pre-wrap text-ink">{text}</blockquote>
      {translation?.translation ? (
        <div className="mt-4 border-t border-dashed border-ink/15 pt-3">
          <p className="text-[11px] font-medium tracking-[0.14em] text-muted uppercase">
            Translation · {LANGUAGE_LABEL[translation.language]} · by Mediator, not their words
          </p>
          <p className="mt-1.5 text-[15px] leading-relaxed whitespace-pre-wrap text-ink/85">{translation.translation}</p>
        </div>
      ) : null}
      {failed ? (
        <p className="mt-3 text-[13px] text-muted">We couldn&apos;t translate this safely. Their own words are above.</p>
      ) : null}
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]">
        <span className="text-muted">{translation?.translation ? "Show in:" : "Read a translation:"}</span>
        {choices.map((code) => (
          <button
            key={code}
            type="button"
            disabled={loading !== null}
            onClick={() => void translate(code)}
            className={`underline-offset-4 hover:underline disabled:opacity-50 ${
              translation?.language === code && translation.translation ? "text-ink" : "text-teal"
            }`}
          >
            {loading === code ? "Translating…" : LANGUAGE_LABEL[code]}
          </button>
        ))}
        {translation?.translation ? (
          <button type="button" onClick={() => setTranslation(null)} className="text-muted underline-offset-4 hover:underline">
            Hide
          </button>
        ) : null}
      </div>
    </figure>
  );
}

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

export function JointView({ session, summary, joint, followUp, auth, onJoint, onFollowUp }: Props) {
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

      {followUp && session.status === "resolved" ? (
        <div className="mt-6">
          <FollowUpCard
            followUp={followUp}
            onAnswer={async (answers) => {
              setError("");
              try {
                onFollowUp(await answerFollowUp(session.id, answers, auth));
              } catch (err) {
                setError(err instanceof Error ? err.message : "Couldn't send your check-in");
              }
            }}
            onReopen={() => quiet(() => reopenJoint(session.id, auth))}
          />
        </div>
      ) : null}

      {joint?.reopened && open ? (
        <p className="mt-5 rounded-2xl bg-teal/10 px-3 py-2.5 text-sm leading-relaxed text-teal">
          You&apos;re talking this through again after a check-in. Your earlier agreement is kept on record. Change any
          answers you like, then sign a new version together.
        </p>
      ) : null}

      {signed && joint?.agreement ? (
        <div className="mt-6">
          <AgreementCard agreement={joint.agreement} otherName={session.other_name} agreedCount={joint.agreed_count} onSign={async () => {}} onRedraft={async () => {}} />
        </div>
      ) : null}

      <div className="mt-6 space-y-3">
        <TheirWords session={session} text={theirs} auth={auth} />
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
                        otherName={session.other_name}
                        onAnswer={(response: IdeaResponse, note: string | null) =>
                          quiet(() => respondToIdea(session.id, idea.id, response, note, auth))
                        }
                        onThink={() => quiet(() => thinkItThrough(session.id, idea.id, auth))}
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
                agreement={joint.agreement} otherName={session.other_name}
                agreedCount={joint.agreed_count}
                onSign={(days) => quiet(() => signAgreement(session.id, joint.agreement!.version, days, auth))}
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
