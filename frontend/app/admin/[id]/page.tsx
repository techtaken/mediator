"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { fetchAdminSession, type AdminSessionDetail } from "@/lib/admin";
import type { ChatMessage } from "@/lib/types";
import { useAuth } from "@/lib/useAuth";

function when(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : "—";
}

function Json({ value }: { value: unknown }) {
  return <pre className="mt-2 max-h-96 overflow-auto bg-card p-3 text-xs">{JSON.stringify(value, null, 2)}</pre>;
}

function Room({ title, messages }: { title: string; messages: ChatMessage[] }) {
  return (
    <section className="min-w-0 flex-1">
      <h2 className="font-semibold">
        {title} ({messages.length})
      </h2>
      <ol className="mt-2 space-y-2">
        {messages.map((m) => (
          <li key={m.id} className="border-l-2 pl-2">
            <div className="text-xs text-muted">
              {m.sender_role === "ai" ? "Mediator" : m.sender_role === "user_a" ? "Person A" : "Person B"} ·{" "}
              {when(m.created_at)}
            </div>
            <div className="whitespace-pre-wrap">{m.content}</div>
          </li>
        ))}
      </ol>
    </section>
  );
}

export default function AdminSessionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { accessToken, loading } = useAuth();
  const [data, setData] = useState<AdminSessionDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!accessToken) return;
    let cancelled = false;
    fetchAdminSession(id, accessToken)
      .then((next) => {
        if (!cancelled) setData(next);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load session");
      });
    return () => {
      cancelled = true;
    };
  }, [accessToken, id]);

  if (loading) return <p className="p-6">Loading…</p>;
  if (!accessToken) {
    return (
      <main className="p-6">
        <Link href="/login" className="underline">
          Sign in
        </Link>
      </main>
    );
  }
  if (error) return <p className="p-6 text-terracotta">{error}</p>;
  if (!data) return <p className="p-6">Loading session…</p>;

  const { session, rooms, private_memories: memories, state, audit_events: audit, joint_summary: joint } = data;
  const safety = (state as { safety?: unknown }).safety;

  return (
    <main className="space-y-8 p-6 text-sm">
      <div>
        <Link href="/admin" className="underline">
          ← All sessions
        </Link>
        <h1 className="mt-2 text-xl font-semibold">{session.topic ?? "(no topic)"}</h1>
        <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
          <dt className="text-muted">ID</dt>
          <dd>{session.id}</dd>
          <dt className="text-muted">Status</dt>
          <dd>{session.status}</dd>
          <dt className="text-muted">Context</dt>
          <dd>{session.relationship_context ?? "—"}</dd>
          <dt className="text-muted">Created</dt>
          <dd>
            {when(session.created_at)} by {session.created_by ?? "—"}
          </dd>
          <dt className="text-muted">Ready A / B</dt>
          <dd>
            {session.user_a_ready ? "yes" : "no"} / {session.user_b_ready ? "yes" : "no"}
          </dd>
          <dt className="text-muted">Halt</dt>
          <dd>{session.halted_for ? `${session.halt_kind ?? "halted"} for ${session.halted_for}` : "—"}</dd>
          <dt className="text-muted">Stage</dt>
          <dd>{String((state as { stage?: unknown }).stage ?? "—")}</dd>
        </dl>
      </div>

      <div className="flex flex-col gap-6 lg:flex-row">
        <Room title="Person A's private room" messages={rooms.user_a ?? []} />
        <Room title="Person B's private room" messages={rooms.user_b ?? []} />
      </div>

      <section>
        <h2 className="font-semibold">Safety flags</h2>
        <Json value={safety ?? {}} />
      </section>

      <section className="flex flex-col gap-6 lg:flex-row">
        {(["user_a", "user_b"] as const).map((party) => (
          <div key={party} className="min-w-0 flex-1">
            <h2 className="font-semibold">Private memory · {party === "user_a" ? "A" : "B"}</h2>
            {memories[party] ? (
              <>
                <p className="mt-2 whitespace-pre-wrap">{memories[party]?.notes || "(no notes)"}</p>
                <Json value={memories[party]?.profile} />
              </>
            ) : (
              <p className="mt-2 text-muted">None yet.</p>
            )}
          </div>
        ))}
      </section>

      <section>
        <h2 className="font-semibold">Joint summary</h2>
        {joint ? (
          <div className="mt-2 space-y-2">
            <p>
              <b>A:</b> {joint.user_a_perspective}
            </p>
            <p>
              <b>B:</b> {joint.user_b_perspective}
            </p>
            <ol className="list-decimal pl-5">
              {joint.compromises.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ol>
          </div>
        ) : (
          <p className="mt-2 text-muted">Not built yet.</p>
        )}
      </section>

      <section>
        <h2 className="font-semibold">Joint session · ideas ({data.joint.ideas.length})</h2>
        <table className="mt-2 w-full border-collapse text-left text-xs">
          <thead>
            <tr className="border-b">
              <th className="p-1">Idea</th>
              <th className="p-1">From</th>
              <th className="p-1">A</th>
              <th className="p-1">B</th>
            </tr>
          </thead>
          <tbody>
            {data.joint.ideas.map((idea) => {
              const answer = (party: "user_a" | "user_b") => {
                const row = data.joint.responses.find((r) => r.idea_id === idea.id && r.party_role === party);
                return row ? `${row.response}${row.note ? ` — ${row.note}` : ""}` : "—";
              };
              return (
                <tr key={idea.id} className="border-b align-top">
                  <td className="p-1">{idea.text}</td>
                  <td className="p-1">{idea.source}</td>
                  <td className="p-1">{answer("user_a")}</td>
                  <td className="p-1">{answer("user_b")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <h3 className="mt-3 font-semibold">Agreement</h3>
        {data.joint.agreement ? <Json value={data.joint.agreement} /> : <p className="mt-1 text-muted">None yet.</p>}
      </section>

      <section>
        <h2 className="font-semibold">Audit trail ({audit.length})</h2>
        <table className="mt-2 w-full border-collapse text-left text-xs">
          <thead>
            <tr className="border-b">
              <th className="p-1">Time</th>
              <th className="p-1">Agent</th>
              <th className="p-1">Stage</th>
              <th className="p-1">Gate</th>
              <th className="p-1">Reason</th>
            </tr>
          </thead>
          <tbody>
            {audit.map((event) => (
              <tr key={event.id} className="border-b align-top">
                <td className="p-1 whitespace-nowrap">{when(event.created_at)}</td>
                <td className="p-1">{event.agent ?? "—"}</td>
                <td className="p-1">{event.stage ?? "—"}</td>
                <td className="p-1">{event.gate ?? "—"}</td>
                <td className="p-1">{event.reason ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2 className="font-semibold">Raw mediation state</h2>
        <Json value={state} />
      </section>
    </main>
  );
}
