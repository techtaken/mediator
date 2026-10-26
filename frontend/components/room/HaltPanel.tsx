import type { Session } from "@/lib/types";

export function HaltPanel({ session }: { session: Session }) {
  if (session.halt_view === "other") {
    return (
      <section className="flex-1 overflow-y-auto px-4 py-8">
        <h1 className="font-[family-name:var(--font-display)] text-3xl text-ink">This session is paused</h1>
        <p className="mt-3 text-[15px] leading-relaxed text-muted">{session.halt_message}</p>
      </section>
    );
  }
  return (
    <section className="flex-1 overflow-y-auto px-4 py-8">
      <h1 className="font-[family-name:var(--font-display)] text-3xl text-ink">Let&apos;s pause here</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-muted">
        Mediator can&apos;t continue when someone may be unsafe. Please reach out to people who can help right now:
      </p>
      <ul className="mt-4 space-y-2">
        {session.helplines.map((line) => (
          <li key={line} className="rounded-2xl bg-card px-4 py-3 text-[15px] text-ink shadow-[0_1px_0_rgba(36,28,22,0.08)]">
            {line}
          </li>
        ))}
      </ul>
      <p className="mt-4 text-sm text-muted">If someone is in immediate danger, call 112.</p>
    </section>
  );
}
