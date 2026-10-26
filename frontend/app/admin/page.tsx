"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchAdminSessions, type AdminSessionList } from "@/lib/admin";
import { useAuth } from "@/lib/useAuth";

const STATUSES = ["", "intake", "building_joint", "joint_review", "resolved", "halted"];
const PAGE_SIZE = 50;

function when(value: string | null) {
  return value ? new Date(value).toLocaleString() : "—";
}

export default function AdminSessionsPage() {
  const { accessToken, loading } = useAuth();
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [reload, setReload] = useState(0);
  const [data, setData] = useState<AdminSessionList | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!accessToken) return;
    let cancelled = false;
    fetchAdminSessions(accessToken, { status: status || undefined, limit: PAGE_SIZE, offset })
      .then((next) => {
        if (cancelled) return;
        setData(next);
        setError("");
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load sessions");
      });
    return () => {
      cancelled = true;
    };
  }, [accessToken, status, offset, reload]);

  if (loading) return <p className="p-6">Loading…</p>;
  if (!accessToken) {
    return (
      <main className="p-6">
        <p>Admins must sign in first.</p>
        <Link href="/login" className="underline">
          Sign in
        </Link>
      </main>
    );
  }

  return (
    <main className="p-6 text-sm">
      <h1 className="text-xl font-semibold">Admin · Sessions</h1>
      <p className="mt-1 text-muted">Read-only. Opening a session is recorded in its audit log.</p>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <label>
          Status{" "}
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
            }}
            className="border px-2 py-1"
          >
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {value || "all"}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="border px-2 py-1" onClick={() => setReload((n) => n + 1)}>
          Refresh
        </button>
      </div>

      {error ? <p className="mt-4 text-terracotta">{error}</p> : null}

      {data ? (
        <>
          <table className="mt-4 w-full border-collapse text-left">
            <thead>
              <tr className="border-b">
                <th className="p-2">Created</th>
                <th className="p-2">Status</th>
                <th className="p-2">Topic</th>
                <th className="p-2">Context</th>
                <th className="p-2">Msgs A / B</th>
                <th className="p-2">Ready A / B</th>
                <th className="p-2">Halt</th>
                <th className="p-2">Last activity</th>
              </tr>
            </thead>
            <tbody>
              {data.sessions.map((row) => (
                <tr key={row.id} className="border-b align-top hover:bg-card">
                  <td className="p-2 whitespace-nowrap">
                    <Link href={`/admin/${row.id}`} className="underline">
                      {when(row.created_at)}
                    </Link>
                  </td>
                  <td className="p-2">{row.status}</td>
                  <td className="p-2">{row.topic ?? "—"}</td>
                  <td className="p-2">{row.relationship_context ?? "—"}</td>
                  <td className="p-2">
                    {row.messages_a} / {row.messages_b}
                  </td>
                  <td className="p-2">
                    {row.user_a_ready ? "✓" : "·"} / {row.user_b_ready ? "✓" : "·"}
                  </td>
                  <td className="p-2">
                    {row.halted_for ? `${row.halt_kind ?? "halted"} (${row.halted_for})` : "—"}
                  </td>
                  <td className="p-2 whitespace-nowrap">{when(row.last_activity)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.sessions.length === 0 ? <p className="mt-4 text-muted">No sessions.</p> : null}
          <div className="mt-4 flex gap-3">
            <button
              type="button"
              className="border px-2 py-1 disabled:opacity-40"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Previous
            </button>
            <button
              type="button"
              className="border px-2 py-1 disabled:opacity-40"
              disabled={!data.has_more}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Next
            </button>
          </div>
        </>
      ) : !error ? (
        <p className="mt-4">Loading sessions…</p>
      ) : null}
    </main>
  );
}
