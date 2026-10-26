"use client";

import Link from "next/link";
import { FormEvent, use, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { Chat } from "@/components/room/Chat";
import { ConsentCard } from "@/components/room/ConsentCard";
import { HaltPanel } from "@/components/room/HaltPanel";
import { JointView } from "@/components/room/JointView";
import { RoomMenu } from "@/components/room/RoomMenu";
import { ShareReview } from "@/components/room/ShareReview";
import { Steps } from "@/components/room/Steps";
import { WaitingPanel } from "@/components/room/WaitingPanel";
import {
  acceptConsent,
  askForPerson,
  fetchJoint,
  fetchMessages,
  fetchSession,
  fetchSummary,
  getInviteToken,
  leaveSession,
  retryJoint,
  sendMessage,
  withdrawShare,
  type AuthOpts,
} from "@/lib/api";
import type { ChatMessage, JointState, JointSummary, Session } from "@/lib/types";
import { useAuth } from "@/lib/useAuth";

const POLL_MS = 2500;
const noopSubscribe = () => () => {};

function whatsappHref(link: string) {
  const text = `I opened a private Mediator room so we can talk this through calmly. Your side stays private. Join here: ${link}`;
  return `https://wa.me/?text=${encodeURIComponent(text)}`;
}

async function loadRoom(id: string, auth: AuthOpts) {
  const session = await fetchSession(id, auth);
  const messages = await fetchMessages(id, auth);
  let summary: JointSummary | null = null;
  let joint: JointState | null = null;
  if (session.status === "joint_review" || session.status === "resolved") {
    [summary, joint] = await Promise.all([
      fetchSummary(id, auth).catch(() => null),
      fetchJoint(id, auth).catch(() => null),
    ]);
  }
  return { session, messages, summary, joint };
}

function currentStep(session: Session | null, reviewing: boolean): 0 | 1 | 2 | 3 {
  if (!session || session.status === "intake") {
    return reviewing || session?.my_share ? 1 : 0;
  }
  return session.status === "resolved" ? 3 : 2;
}

export default function RoomPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { accessToken, loading: authLoading } = useAuth();
  // Invite tokens live in sessionStorage, so read them only on the client.
  const onClient = useSyncExternalStore(noopSubscribe, () => true, () => false);
  const inviteToken = onClient ? getInviteToken(id) : null;
  const auth = useMemo<AuthOpts>(() => ({ accessToken, inviteToken }), [accessToken, inviteToken]);

  const [session, setSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [summary, setSummary] = useState<JointSummary | null>(null);
  const [joint, setJoint] = useState<JointState | null>(null);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  // How many identical messages from this person existed when `pending` was sent.
  const [sentCopies, setSentCopies] = useState(0);
  const [reviewing, setReviewing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const canLoad = onClient && !authLoading && Boolean(auth.accessToken || auth.inviteToken);

  useEffect(() => {
    if (!canLoad) return;
    let cancelled = false;
    const tick = () =>
      loadRoom(id, auth)
        .then((room) => {
          if (cancelled) return;
          setSession(room.session);
          setMessages(room.messages);
          if (room.summary) setSummary(room.summary);
          if (room.joint) setJoint(room.joint);
          setError("");
        })
        .catch((err: unknown) => {
          if (!cancelled) setError(err instanceof Error ? err.message : "Could not load room");
        });
    void tick();
    const timer = setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [canLoad, id, auth, refreshKey]);

  async function run(action: () => Promise<Session | void>) {
    setBusy(true);
    setError("");
    try {
      const next = await action();
      if (next) setSession(next);
      setRefreshKey((n) => n + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  async function onSend(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || pending) return;
    setDraft("");
    setSentCopies(messages.filter((m) => m.sender_role === session?.party && m.content === text).length);
    setPending(text);
    setError("");
    try {
      const added = await sendMessage(id, text, auth);
      setMessages((prev) => {
        const seen = new Set(prev.map((m) => m.id));
        return [...prev, ...added.filter((m) => !seen.has(m.id))];
      });
      setRefreshKey((n) => n + 1);
    } catch (err) {
      setDraft(text);
      setError(err instanceof Error ? err.message : "Could not send");
    } finally {
      setPending(null);
    }
  }

  async function copyInvite(link: string) {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Couldn't copy. Long-press the WhatsApp button to share instead.");
    }
  }

  if (!onClient || authLoading) {
    return <p className="px-5 py-16 text-muted">Loading…</p>;
  }

  if (!auth.accessToken && !auth.inviteToken) {
    return (
      <main className="mx-auto max-w-lg px-5 py-16">
        <p className="text-ink">This private room needs a sign-in or an invite link.</p>
        <Link href="/login" className="mt-4 inline-block text-terracotta">
          Sign in
        </Link>
      </main>
    );
  }

  const isA = session?.party === "user_a";
  const otherReady = isA ? session?.user_b_ready : session?.user_a_ready;
  const hasSpoken = messages.some((m) => m.sender_role === session?.party);
  const needsConsent = session?.status === "intake" && !session.i_consented;
  const showChat = session?.status === "intake" && !session.my_share && !needsConsent;
  const canStop = session ? ["intake", "building_joint", "joint_review"].includes(session.status) : false;
  // The server saves the person's message before the mediator replies, so a
  // poll during that wait can already return it. Only show the local
  // placeholder until the saved copy arrives, or it appears twice.
  const ownCopies = (text: string) =>
    messages.filter((m) => m.sender_role === session?.party && m.content === text).length;
  const pendingSaved = pending !== null && ownCopies(pending) > sentCopies;
  const shownMessages: ChatMessage[] = pending && !pendingSaved
    ? [
        ...messages,
        {
          id: "pending",
          sender_role: session?.party ?? "user_a",
          audience_role: session?.party ?? "user_a",
          content: pending,
          is_private: true,
          created_at: new Date().toISOString(),
        },
      ]
    : messages;

  let body: React.ReactNode;
  if (!session) {
    body = <p className="flex-1 px-4 py-8 text-muted">{error || "Opening your room…"}</p>;
  } else if (session.status === "halted") {
    body = <HaltPanel session={session} />;
  } else if (needsConsent) {
    body = <ConsentCard onAccept={() => run(() => acceptConsent(id, auth))} />;
  } else if (session.status !== "intake") {
    body = (
      <JointView
        session={session}
        summary={summary}
        joint={joint}
        auth={auth}
        onJoint={(next) => {
          setJoint(next);
          setRefreshKey((n) => n + 1);
        }}
      />
    );
  } else if (session.my_share) {
    body = (
      <WaitingPanel
        shared={session.my_share}
        otherReady={Boolean(otherReady)}
        busy={busy}
        onWithdraw={() => void run(() => withdrawShare(id, auth))}
        onRetry={() => void run(() => retryJoint(id, auth))}
      />
    );
  } else {
    body = <Chat messages={shownMessages} thinking={Boolean(pending)} />;
  }

  return (
    <main className="mx-auto flex h-[100dvh] w-full max-w-lg flex-col">
      <header className="border-b border-ink/10 px-4 pt-3 pb-3">
        <div className="flex items-center justify-between gap-3">
          <Link href="/" className="text-xs tracking-[0.2em] text-terracotta uppercase">
            Mediator
          </Link>
          <div className="flex items-center gap-2">
            <p className="text-xs text-muted">{isA ? "Your private room" : "Invited · private room"}</p>
            {canStop ? (
              <RoomMenu
                onAction={(action) => run(() => (action === "leave" ? leaveSession(id, auth) : askForPerson(id, auth)))}
              />
            ) : null}
          </div>
        </div>
        {session?.status !== "halted" ? <Steps current={currentStep(session, reviewing)} /> : null}
        {session?.topic ? (
          <p className="mt-3 text-sm leading-snug text-ink">
            <span className="text-muted">{isA ? "You opened this about: " : "They opened this about: "}</span>
            {session.topic}
          </p>
        ) : null}
        {isA && session?.invite_link && session.status === "intake" ? (
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              className="flex-1 rounded-full border border-ink/10 bg-card px-3 py-2 text-sm text-ink"
              onClick={() => void copyInvite(session.invite_link ?? "")}
            >
              {copied ? "Copied ✓" : "Copy invite link"}
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

      {error && session ? (
        <p role="alert" className="mx-4 mt-3 rounded-2xl bg-terracotta/10 px-3 py-2 text-sm text-terracotta">
          {error}
        </p>
      ) : null}

      {body}

      {showChat ? (
        <form onSubmit={onSend} className="border-t border-ink/10 bg-paper px-3 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <div className="mb-2.5 flex items-center justify-between gap-3 px-1 text-xs">
            <span className="text-muted">
              {otherReady ? "The other person has shared their side" : "The other person is still talking"}
            </span>
            <button
              type="button"
              onClick={() => setReviewing(true)}
              disabled={!hasSpoken || Boolean(pending)}
              title={hasSpoken ? undefined : "Say a little about your side first"}
              className="shrink-0 rounded-full bg-terracotta px-3.5 py-1.5 font-medium text-card disabled:opacity-40"
            >
              I&apos;m ready to share
            </button>
          </div>
          <div className="flex gap-2">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Type in Hinglish or English"
              aria-label="Your message"
              maxLength={4000}
              className="flex-1 rounded-full border border-ink/10 bg-card px-4 py-3 text-base outline-none focus:border-terracotta"
            />
            <button
              disabled={Boolean(pending) || !draft.trim()}
              className="rounded-full bg-ink px-4 py-3 text-sm text-card disabled:opacity-40"
            >
              Send
            </button>
          </div>
        </form>
      ) : null}

      {reviewing && session?.status === "intake" ? (
        <ShareReview
          sessionId={id}
          auth={auth}
          onCancel={() => setReviewing(false)}
          onShared={(next) => {
            setSession(next);
            setReviewing(false);
            setRefreshKey((n) => n + 1);
          }}
        />
      ) : null}
    </main>
  );
}
