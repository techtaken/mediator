"use client";

import Link from "next/link";
import { FormEvent, use, useCallback, useEffect, useRef, useState } from "react";
import {
  fetchMessages,
  fetchSession,
  fetchSummary,
  getInviteToken,
  markReady,
  markResolved,
  sendMessage,
} from "@/lib/api";
import type { ChatMessage, JointSummary, Session } from "@/lib/types";
import { useAuth } from "@/lib/useAuth";

function whatsappHref(link: string) {
  const text = `I opened a private Mediator room so we can talk this through without shouting. Your side stays private. Join here: ${link}`;
  return `https://wa.me/?text=${encodeURIComponent(text)}`;
}

export default function RoomPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { accessToken, loading: authLoading } = useAuth();
  const [session, setSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [summary, setSummary] = useState<JointSummary | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [mounted, setMounted] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  const auth = useCallback(() => {
    return {
      accessToken,
      inviteToken: getInviteToken(id),
    };
  }, [accessToken, id]);

  const refresh = useCallback(async () => {
    const creds = auth();
    if (!creds.accessToken && !creds.inviteToken) return;
    try {
      const nextSession = await fetchSession(id, creds);
      setSession(nextSession);
      const nextMessages = await fetchMessages(id, creds);
      setMessages(nextMessages);
      if (nextSession.status === "joint_review" || nextSession.status === "resolved") {
        try {
          setSummary(await fetchSummary(id, creds));
        } catch {
          /* summary may still be writing */
        }
      }
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load room");
    }
  }, [auth, id]);

  useEffect(() => {
    if (authLoading) return;
    void refresh();
    const timer = setInterval(() => void refresh(), 2500);
    return () => clearInterval(timer);
  }, [authLoading, refresh]);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [messages.length]);

  async function onSend(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setBusy(true);
    setDraft("");
    try {
      const added = await sendMessage(id, text, auth());
      setMessages((prev) => {
        const seen = new Set(prev.map((m) => m.id));
        return [...prev, ...added.filter((m) => !seen.has(m.id))];
      });
      await refresh();
    } catch (err) {
      setDraft(text);
      setError(err instanceof Error ? err.message : "Could not send");
    } finally {
      setBusy(false);
    }
  }

  async function onReady() {
    if (!session) return;
    const mine = session.party === "user_a" ? session.user_a_ready : session.user_b_ready;
    setBusy(true);
    try {
      setSession(await markReady(id, !mine, auth()));
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update");
    } finally {
      setBusy(false);
    }
  }

  async function onResolve() {
    setBusy(true);
    try {
      setSession(await markResolved(id, auth()));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not close room");
    } finally {
      setBusy(false);
    }
  }

  if (!mounted || authLoading) {
    return <p className="px-5 py-16 text-muted">Loading…</p>;
  }

  if (!accessToken && !getInviteToken(id)) {
    return (
      <main className="mx-auto max-w-lg px-5 py-16">
        <p className="text-ink">This private room needs a sign-in or an invite link.</p>
        <Link href="/login" className="mt-4 inline-block text-terracotta">
          Sign in
        </Link>
      </main>
    );
  }

  const mineReady =
    session?.party === "user_a" ? session.user_a_ready : session?.user_b_ready;
  const otherReady =
    session?.party === "user_a" ? session.user_b_ready : session?.user_a_ready;
  const showJoint =
    session?.status === "building_joint" ||
    session?.status === "joint_review" ||
    session?.status === "resolved";

  return (
    <main className="mx-auto flex h-[100dvh] w-full max-w-lg flex-col">
      <header className="border-b border-ink/10 px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <Link href="/" className="text-xs tracking-[0.2em] text-terracotta uppercase">
            Mediator
          </Link>
          <p className="text-xs text-muted">
            {session?.party === "user_a" ? "Your private room" : "Invited private room"}
          </p>
        </div>
        {session?.invite_link ? (
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              className="flex-1 rounded-full bg-card px-3 py-2 text-sm text-ink"
              onClick={() => navigator.clipboard.writeText(session.invite_link ?? "")}
            >
              Copy invite
            </button>
            <a
              className="flex-1 rounded-full bg-teal px-3 py-2 text-center text-sm text-card"
              href={whatsappHref(session.invite_link)}
              target="_blank"
              rel="noreferrer"
            >
              Share on WhatsApp
            </a>
          </div>
        ) : null}
      </header>

      {error ? <p className="px-4 py-2 text-sm text-terracotta">{error}</p> : null}

      {session?.status === "halted" ? (
        <section className="flex-1 overflow-y-auto px-4 py-6">
          {session.halt_view === "other" ? (
            <>
              <h1 className="font-[family-name:var(--font-display)] text-2xl">This session is paused</h1>
              <p className="mt-3 text-muted">{session.halt_message}</p>
            </>
          ) : (
            <>
              <h1 className="font-[family-name:var(--font-display)] text-2xl">This room has stopped</h1>
              <p className="mt-3 text-muted">
                Mediator cannot continue when someone may be unsafe. Please reach out to people who can help
                right now:
              </p>
              <ul className="mt-3 space-y-1 text-ink">
                {session.helplines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
              <p className="mt-3 text-sm text-muted">If someone is in immediate danger, call 112.</p>
            </>
          )}
        </section>
      ) : showJoint ? (
        <section className="flex-1 overflow-y-auto px-4 py-6">
          <p className="text-xs uppercase tracking-[0.18em] text-muted">Joint view</p>
          <h1 className="mt-2 font-[family-name:var(--font-display)] text-3xl">What both of you need</h1>
          <p className="mt-2 text-sm text-muted">
            Private chats stay private. This is the neutralized reading.
          </p>
          {summary ? (
            <div className="mt-6 space-y-4">
              <article className="rounded-2xl bg-card p-4">
                <h2 className="text-sm uppercase tracking-wide text-terracotta">Person A</h2>
                <p className="mt-2 leading-relaxed">{summary.user_a_perspective}</p>
              </article>
              <article className="rounded-2xl bg-card p-4">
                <h2 className="text-sm uppercase tracking-wide text-terracotta">Person B</h2>
                <p className="mt-2 leading-relaxed">{summary.user_b_perspective}</p>
              </article>
              <div>
                <h2 className="text-sm uppercase tracking-wide text-muted">Possible compromises</h2>
                <ol className="mt-3 space-y-3">
                  {summary.compromises.map((item, index) => (
                    <li key={`${index}-${item}`} className="rounded-2xl bg-teal px-4 py-3 text-card">
                      {item}
                    </li>
                  ))}
                </ol>
              </div>
              {session.status === "joint_review" ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void onResolve()}
                  className="w-full rounded-full bg-ink px-5 py-3 text-card"
                >
                  Mark as resolved
                </button>
              ) : (
                <p className="text-sm text-muted">This room is marked resolved.</p>
              )}
            </div>
          ) : (
            <p className="mt-6 text-muted">Writing the joint summary…</p>
          )}
        </section>
      ) : (
        <>
          <div ref={scroller} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
            {messages.map((message) => {
              const mine = message.sender_role !== "ai";
              return (
                <div key={message.id} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
                  <p
                    className={`max-w-[85%] rounded-3xl px-4 py-3 text-[15px] leading-relaxed ${
                      mine ? "bg-teal text-card" : "bg-card text-ink"
                    }`}
                  >
                    {message.content}
                  </p>
                </div>
              );
            })}
          </div>
          <form onSubmit={onSend} className="border-t border-ink/10 bg-paper px-3 py-3">
            <div className="mb-2 flex items-center justify-between text-xs text-muted">
              <span>
                You {mineReady ? "are ready" : "are still venting"} · Other person{" "}
                {otherReady ? "is ready" : "is still venting"}
              </span>
              <button type="button" onClick={() => void onReady()} className="text-terracotta">
                {mineReady ? "Undo ready" : "Ready for joint session"}
              </button>
            </div>
            <div className="flex gap-2">
              <input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Type in Hinglish or English"
                className="flex-1 rounded-full border border-ink/10 bg-card px-4 py-3 text-base outline-none focus:border-terracotta"
              />
              <button
                disabled={busy || !draft.trim()}
                className="rounded-full bg-terracotta px-4 py-3 text-sm text-card disabled:opacity-50"
              >
                Send
              </button>
            </div>
          </form>
        </>
      )}
    </main>
  );
}
