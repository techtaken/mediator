import Link from "next/link";
import type { Session } from "@/lib/types";

function Helplines({ session }: { session: Session }) {
  return (
    <ul className="mt-4 space-y-2">
      {session.helplines.map((line) => (
        <li key={line} className="rounded-2xl bg-card px-4 py-3 text-[15px] text-ink shadow-[0_1px_0_rgba(36,28,22,0.08)]">
          {line}
        </li>
      ))}
    </ul>
  );
}

/** What each person sees once a room has stopped. Only the person who stopped it learns why. */
export function HaltPanel({ session }: { session: Session }) {
  if (session.halt_view === "other") {
    return (
      <section className="flex-1 overflow-y-auto px-4 py-8">
        <h1 className="font-[family-name:var(--font-display)] text-3xl text-ink">This session is paused</h1>
        <p className="mt-3 text-[15px] leading-relaxed text-muted">{session.halt_message}</p>
      </section>
    );
  }

  if (session.halted_reason === "withdrawn") {
    return (
      <section className="flex-1 overflow-y-auto px-4 py-8">
        <h1 className="font-[family-name:var(--font-display)] text-3xl text-ink">You&apos;ve left this session</h1>
        <p className="mt-3 text-[15px] leading-relaxed text-muted">
          Nothing more will be shared. The other person only sees that the session is paused. Leaving is always okay.
        </p>
        <Link href="/" className="mt-6 inline-block text-sm text-terracotta underline-offset-4 hover:underline">
          Back to Mediator
        </Link>
      </section>
    );
  }

  if (session.halted_reason === "referral") {
    return (
      <section className="flex-1 overflow-y-auto px-4 py-8">
        <h1 className="font-[family-name:var(--font-display)] text-3xl text-ink">Talking to a person</h1>
        <p className="mt-3 text-[15px] leading-relaxed text-muted">
          We&apos;ve paused this room and flagged it for the Mediator team. The other person only sees that the session
          is paused.
        </p>
        <h2 className="mt-6 text-sm font-medium text-ink">In the meantime, these can help</h2>
        <ul className="mt-2 list-disc space-y-1.5 pl-5 text-[15px] leading-relaxed text-muted">
          <li>Someone you both trust, like a family elder or a friend, can often hear both sides.</li>
          <li>For anything legal, your District Legal Services Authority offers free mediation.</li>
          <li>If this is weighing on you, or anyone is unsafe, these lines can help:</li>
        </ul>
        <Helplines session={session} />
      </section>
    );
  }

  return (
    <section className="flex-1 overflow-y-auto px-4 py-8">
      <h1 className="font-[family-name:var(--font-display)] text-3xl text-ink">Let&apos;s pause here</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-muted">
        Mediator can&apos;t continue when someone may be unsafe. Please reach out to people who can help right now:
      </p>
      <Helplines session={session} />
      <p className="mt-4 text-sm text-muted">If someone is in immediate danger, call 112.</p>
    </section>
  );
}
