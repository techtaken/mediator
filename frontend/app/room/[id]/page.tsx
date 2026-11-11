"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, use, useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { Chat } from "@/components/room/Chat";
import { ConsentCard } from "@/components/room/ConsentCard";
import { HaltPanel } from "@/components/room/HaltPanel";
import { JointView } from "@/components/room/JointView";
import { ChoosePin, EnterPin } from "@/components/room/PinScreens";
import { AppShell } from "@/components/AppShell";
import { RoomMenu, type RoomAction } from "@/components/room/RoomMenu";
import { SaveToChats } from "@/components/room/SaveToChats";
import { ShareReview } from "@/components/room/ShareReview";
import { Steps } from "@/components/room/Steps";
import { WaitingPanel } from "@/components/room/WaitingPanel";
import {
  ApiError,
  acceptConsent,
  askForPerson,
  claimRoom,
  clearRoomAccess,
  deleteMyData,
  deleteRoom,
  fetchFollowUp,
  fetchJoint,
  fetchMessages,
  fetchSession,
  fetchSummary,
  getInviteToken,
  getRoomAccess,
  leaveSession,
  removeFromMyChats,
  retryJoint,
  rotateInvite,
  saveRoomAccess,
  saveToMyChats,
  sendMessage,
  setLanguage,
  unlockRoom,
  withdrawShare,
  type AuthOpts,
} from "@/lib/api";
import { subscribeRoom } from "@/lib/live";
import type { ChatMessage, FollowUp, JointState, JointSummary, Language, Session } from "@/lib/types";
import { useAuth } from "@/lib/useAuth";
import { useProfile } from "@/lib/useProfile";

// Polling is the fallback; with a live stream connected it only runs as a slow safety net.
const POLL_MS = 2500;
const SAFETY_POLL_MS = 30000;

const PLACEHOLDER: Record<Language, string> = {
  en: "Type your message",
  hinglish: "Apni baat likhiye",
  hi: "अपनी बात लिखिए",
};
const noopSubscribe = () => () => {};

function whatsappHref(link: string, name: string | null) {
  const text = `${name ? `Hi ${name}, I` : "I"} opened a private Mediator room so we can talk this through calmly. Your side stays private. Join here: ${link}`;
  return `https://wa.me/?text=${encodeURIComponent(text)}`;
}

async function loadRoom(id: string, auth: AuthOpts) {
  const session = await fetchSession(id, auth);
  if (session.needs_pin) {
    return { session, messages: [], summary: null, joint: null, followUp: null };
  }
  const messages = await fetchMessages(id, auth);
  let summary: JointSummary | null = null;
  let joint: JointState | null = null;
  let followUp: FollowUp | null = null;
  if (session.status === "joint_review" || session.status === "resolved") {
    [summary, joint, followUp] = await Promise.all([
      fetchSummary(id, auth).catch(() => null),
      fetchJoint(id, auth).catch(() => null),
      session.status === "resolved" ? fetchFollowUp(id, auth).catch(() => null) : Promise.resolve(null),
    ]);
  }
  return { session, messages, summary, joint, followUp };
}

function shortDate(value: string | null) {
  return value ? new Date(value).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "";
}

function currentStep(session: Session | null, reviewing: boolean): 0 | 1 | 2 | 3 {
  if (!session || session.status === "intake") {
    return reviewing || session?.my_share ? 1 : 0;
  }
  return session.status === "resolved" ? 3 : 2;
}

export default function RoomPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const { accessToken, loading: authLoading, user } = useAuth();
  const profile = useProfile(accessToken);
  // Invite tokens live in sessionStorage, so read them only on the client.
  const onClient = useSyncExternalStore(noopSubscribe, () => true, () => false);
  const inviteToken = onClient ? getInviteToken(id) : null;
  // Back from the sign-in email link, on the way to saving this room.
  const fromSignIn = onClient && new URLSearchParams(window.location.search).get("from") === "signin";
  const roomAccess = onClient ? getRoomAccess(id) : null;
  const auth = useMemo<AuthOpts>(() => ({ accessToken, inviteToken, roomAccess }), [accessToken, inviteToken, roomAccess]);

  const [session, setSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [summary, setSummary] = useState<JointSummary | null>(null);
  const [joint, setJoint] = useState<JointState | null>(null);
  const [followUp, setFollowUp] = useState<FollowUp | null>(null);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  // How many identical messages from this person existed when `pending` was sent.
  const [sentCopies, setSentCopies] = useState(0);
  const [reviewing, setReviewing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  // The room was deleted (404), the invite expired (410) or it was replaced (403): stop polling.
  const [gone, setGone] = useState<"deleted" | "expired" | "replaced" | null>(null);
  const [confirmRotate, setConfirmRotate] = useState(false);
  // The server wants the invited person's PIN (423): show nothing of the room until then.
  const [pinGate, setPinGate] = useState(false);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [claiming, setClaiming] = useState(false);

  /** The access token ran out or was never there: clear the room off the screen and ask. */
  const askedForPin = useCallback(
    (err: unknown) => {
      if (!(err instanceof ApiError && err.status === 423)) return false;
      clearRoomAccess(id);
      setSession(null);
      setMessages([]);
      setSummary(null);
      setJoint(null);
      setFollowUp(null);
      setError("");
      setPinGate(true);
      return true;
    },
    [id],
  );

  const canLoad =
    onClient && !authLoading && Boolean(auth.accessToken || auth.inviteToken || auth.roomAccess) && !gone && !pinGate && !claiming;

  useEffect(() => {
    if (!canLoad) return;
    let cancelled = false;
    let live = false;
    let lastLoad = 0;
    const tick = () => {
      lastLoad = Date.now();
      return loadRoom(id, auth)
        .then((room) => {
          if (cancelled) return;
          setSession(room.session);
          setMessages(room.messages);
          if (room.summary) setSummary(room.summary);
          if (room.joint) setJoint(room.joint);
          setFollowUp(room.followUp);
          setError("");
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          if (askedForPin(err)) return;
          if (err instanceof ApiError && (err.status === 404 || err.status === 410)) {
            setGone(err.status === 404 ? "deleted" : "expired");
          }
          if (err instanceof ApiError && err.status === 403 && (auth.inviteToken || auth.roomAccess)) {
            clearRoomAccess(id);
            setGone("replaced");
          }
          setError(err instanceof Error ? err.message : "Could not load room");
        });
    };
    void tick();
    const timer = setInterval(() => {
      if (!live || Date.now() - lastLoad > SAFETY_POLL_MS) void tick();
    }, POLL_MS);
    const stop = subscribeRoom(id, auth, {
      onChange: () => {
        // The first event after connecting usually repeats what we just loaded.
        if (!cancelled && Date.now() - lastLoad > 400) void tick();
      },
      onGone: () => {
        if (!cancelled) setGone("deleted");
      },
      onStatus: (connected) => {
        live = connected;
      },
    });
    return () => {
      cancelled = true;
      clearInterval(timer);
      stop();
    };
  }, [canLoad, id, auth, refreshKey, askedForPin]);

  async function choosePin(pin: string, name: string) {
    // The link stops working the moment the PIN is saved. A refresh sent with
    // just the link would then ask for the PIN they only just chose, so hold
    // refreshes until the access token is here.
    setClaiming(true);
    try {
      saveRoomAccess(id, await claimRoom(id, pin, name, auth));
      setTermsAccepted(false);
    } catch (err) {
      if (!askedForPin(err)) throw err;
    } finally {
      setClaiming(false);
    }
  }

  async function enterPin(pin: string) {
    saveRoomAccess(id, await unlockRoom(id, pin, auth));
    setPinGate(false);
  }

  async function run(action: () => Promise<Session | void>) {
    setBusy(true);
    setError("");
    try {
      const next = await action();
      if (next) setSession(next);
      setRefreshKey((n) => n + 1);
    } catch (err) {
      if (askedForPin(err)) return;
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
      if (askedForPin(err)) return;
      setError(err instanceof Error ? err.message : "Could not send");
    } finally {
      setPending(null);
    }
  }

  async function onMenu(action: RoomAction) {
    if (action === "delete_room") {
      setBusy(true);
      try {
        await deleteRoom(id, auth);
        router.push("/");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not delete the room");
      } finally {
        setBusy(false);
      }
      return;
    }
    await run(() => {
      if (action === "leave") return leaveSession(id, auth);
      if (action === "human") return askForPerson(id, auth);
      if (action === "reset_invite") return rotateInvite(id, auth);
      if (action === "unsave") return removeFromMyChats(id, auth);
      return deleteMyData(id, auth);
    });
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

  if (gone) {
    return (
      <main className="mx-auto max-w-lg px-5 py-16">
        <h1 className="font-[family-name:var(--font-display)] text-3xl text-ink">
          {gone === "deleted"
            ? "This room is no longer available"
            : gone === "replaced"
              ? "This link no longer works"
              : "This invite link has expired"}
        </h1>
        <p className="mt-3 text-[15px] leading-relaxed text-muted">
          {gone === "deleted"
            ? "It was deleted, or removed after the retention period. Nothing from it is kept."
            : gone === "replaced"
              ? "The person who invited you replaced it. Anything written with the old link was deleted, and they never saw it. Ask them for the new link."
              : "Ask the person who invited you to send a new link."}
        </p>
        <Link href="/" className="mt-6 inline-block text-sm text-terracotta underline-offset-4 hover:underline">
          Back to Mediator
        </Link>
      </main>
    );
  }

  if (pinGate) {
    return (
      <main className="mx-auto max-w-lg">
        <EnterPin
          onEnter={enterPin}
          reason={fromSignIn ? "signin" : !auth.inviteToken && auth.accessToken ? "chats" : "invite"}
        />
      </main>
    );
  }

  if (!auth.accessToken && !auth.inviteToken && !auth.roomAccess) {
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
  const needsPin = Boolean(session?.needs_pin);
  const needsConsent = !needsPin && session?.status === "intake" && !session.i_consented;
  const showChat = session?.status === "intake" && !session.my_share && !needsConsent && !needsPin;
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
  } else if (needsPin && (session.i_consented || termsAccepted)) {
    body = <ChoosePin inviter={session.other_name} invitedAs={session.invited_as} onChoose={choosePin} />;
  } else if (needsPin) {
    // Accepting is recorded together with the PIN, so nobody joins without one.
    body = (
      <ConsentCard
        retentionDays={session.retention_days}
        invitedAs={session.invited_as}
        language={session.my_language}
        onLanguage={(language) => run(() => setLanguage(id, language, auth))}
        onAccept={async () => setTermsAccepted(true)}
      />
    );
  } else if (needsConsent) {
    body = (
      <ConsentCard
        retentionDays={session.retention_days}
        language={session.my_language}
        onLanguage={(language) => run(() => setLanguage(id, language, auth))}
        onAccept={() => run(() => acceptConsent(id, auth))}
      />
    );
  } else if (session.status !== "intake") {
    body = (
      <JointView
        session={session}
        summary={summary}
        joint={joint}
        followUp={followUp}
        auth={auth}
        onJoint={(next) => {
          setJoint(next);
          setRefreshKey((n) => n + 1);
        }}
        onFollowUp={(next) => {
          setFollowUp(next);
          setRefreshKey((n) => n + 1);
        }}
      />
    );
  } else if (session.my_share) {
    body = (
      <WaitingPanel
        shared={session.my_share}
        otherReady={Boolean(otherReady)}
        otherJoined={session.other_joined}
        otherName={session.other_name}
        busy={busy}
        onWithdraw={() => void run(() => withdrawShare(id, auth))}
        onRetry={() => void run(() => retryJoint(id, auth))}
      />
    );
  } else {
    body = <Chat messages={shownMessages} thinking={Boolean(pending)} />;
  }

  const room = (
    <main className="mx-auto flex h-[100dvh] w-full max-w-lg flex-col">
      <header className="border-b border-ink/10 px-4 pt-3 pb-3">
        <div className="flex items-center justify-between gap-3">
          <Link href="/" className="text-xs tracking-[0.2em] text-terracotta uppercase">
            Mediator
          </Link>
          <div className="flex items-center gap-2">
            <p className="text-xs text-muted">{isA ? "Your private room" : "Invited · private room"}</p>
            {session && !needsPin ? (
              <RoomMenu
                canStop={canStop}
                isA={isA}
                canResetInvite={isA && session.other_joined && session.status === "intake" && !session.user_b_ready}
                canUnsave={Boolean(session.saved_to)}
                language={session.my_language}
                onLanguage={(language) => run(() => setLanguage(id, language, auth))}
                onAction={onMenu}
              />
            ) : null}
          </div>
        </div>
        {session?.status !== "halted" ? <Steps current={currentStep(session, reviewing)} /> : null}
        {session?.topic ? (
          <p className="mt-3 text-sm leading-snug text-ink">
            <span className="text-muted">
              {isA ? "You opened this about: " : `${session.other_name ?? "They"} opened this about: `}
            </span>
            {session.topic}
          </p>
        ) : null}
        {needsPin && session?.invited_as ? (
          <p className="mt-1.5 text-xs text-muted">
            This invite is for {session.invited_as}. If that isn&apos;t you, please close this page.
          </p>
        ) : null}
        {isA && session?.invite_link && session.status === "intake" ? (
          <>
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
              href={whatsappHref(session.invite_link, session.other_name)}
              target="_blank"
              rel="noreferrer"
            >
              Share on WhatsApp
            </a>
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-1 text-xs text-muted">
            <span>
              {session.invite_expires_at ? `Link works until ${shortDate(session.invite_expires_at)} if unused` : "Not joined yet"}
            </span>
            {confirmRotate ? (
              <span className="flex items-center gap-2">
                <span>The old link will stop working.</span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void run(() => rotateInvite(id, auth)).finally(() => setConfirmRotate(false))}
                  className="font-medium text-terracotta disabled:opacity-50"
                >
                  Make new link
                </button>
                <button type="button" onClick={() => setConfirmRotate(false)} className="text-muted">
                  Cancel
                </button>
              </span>
            ) : (
              <button type="button" onClick={() => setConfirmRotate(true)} className="underline-offset-4 hover:underline">
                Sent it to the wrong person? Make a new link
              </button>
            )}
          </div>
          </>
        ) : null}
        {isA && session?.invite_expired && session.status === "intake" ? (
          <div className="mt-3 rounded-2xl bg-terracotta/10 px-3 py-3">
            <p className="text-sm font-medium text-terracotta">This link has expired</p>
            <p className="mt-0.5 text-xs leading-relaxed text-muted">
              Nobody joined with it, so it no longer works. Make a new one to invite {session.other_name ?? "them"}.
            </p>
            <button
              type="button"
              disabled={busy}
              onClick={() => void run(() => rotateInvite(id, auth))}
              className="mt-2.5 w-full rounded-full bg-teal px-3 py-2 text-sm text-card disabled:opacity-50"
            >
              {busy ? "One moment…" : "Make a new link"}
            </button>
          </div>
        ) : null}
        {isA && session?.other_joined && session.status === "intake" ? (
          <p className="mt-3 rounded-2xl bg-teal/10 px-3 py-2 text-sm text-teal">
            {session.other_name ? `${session.other_name} has joined` : "They've joined"}
            {session.invited_as && session.other_name && session.invited_as.toLowerCase() !== session.other_name.toLowerCase()
              ? ` (you invited ${session.invited_as})`
              : ""}
            . Their chat stays private.
          </p>
        ) : null}
      </header>

      {session?.my_data_deleted && session.status !== "halted" ? (
        <p className="mx-4 mt-3 rounded-2xl bg-teal/10 px-3 py-2 text-sm text-teal">
          Your private chat and notes have been deleted. What you both agreed to in the joint view is still here.
        </p>
      ) : null}

      {error && session ? (
        <p role="alert" className="mx-4 mt-3 rounded-2xl bg-terracotta/10 px-3 py-2 text-sm text-terracotta">
          {error}
        </p>
      ) : null}

      {session ? (
        <SaveToChats
          session={session}
          signedInEmail={user?.email ?? null}
          onSave={async () => {
            setSession(await saveToMyChats(id, auth));
          }}
        />
      ) : null}

      {body}

      {showChat ? (
        <form onSubmit={onSend} className="border-t border-ink/10 bg-paper px-3 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <div className="mb-2.5 flex items-center justify-between gap-3 px-1 text-xs">
            <span className="text-muted">
              {!session?.other_joined
                ? session?.other_name
                  ? `${session.other_name} hasn't joined yet`
                  : "They haven't joined yet"
                : otherReady
                  ? `${session?.other_name ?? "The other person"} has shared their side`
                  : `${session?.other_name ?? "The other person"} is still talking`}
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
              placeholder={session?.my_language ? PLACEHOLDER[session.my_language] : "Type in English, Hinglish or Hindi"}
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

  // Signed in (Person A, or Person B with an account): their conversations sit beside the room.
  return accessToken ? (
    <AppShell accessToken={accessToken} name={profile.name} activeRoomId={id} ownMobileHeader>
      {room}
    </AppShell>
  ) : (
    room
  );
}
