"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchReferrals, generateBrief, markReferralHandled, type HandoffBrief, type ReferralRow } from "@/lib/admin";
import { useAuth } from "@/lib/useAuth";

function when(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : "—";
}

function list(value: unknown) {
  if (!Array.isArray(value) || value.length === 0) return null;
  return (
    <ul className="list-disc pl-5">
      {value.map((item, index) => (
        <li key={index}>{typeof item === "string" ? item : JSON.stringify(item)}</li>
      ))}
    </ul>
  );
}

function Brief({ brief }: { brief: HandoffBrief }) {
  const rows: [string, React.ReactNode][] = [
    ["Urgency", brief.urgency],
    ["Reason", brief.handoff_reason],
    ["Summary", brief.dispute_summary],
    ["Issues", list(brief.issues)],
    ["Progress so far", list(brief.progress_so_far)],
    ["What didn't work", list(brief.what_didnt_work)],
    ["Suggested starting point", brief.suggested_starting_point],
  ];
  return (
    <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 bg-card p-3">
      {rows
        .filter(([, value]) => value)
        .map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted">{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
    </dl>
  );
}

/** Rooms where someone asked to talk to a person. */
export default function ReferralInboxPage() {
  const { accessToken, loading } = useAuth();
  const [showHandled, setShowHandled] = useState(false);
  const [rows, setRows] = useState<ReferralRow[] | null>(null);
  const [briefs, setBriefs] = useState<Record<string, HandoffBrief>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (!accessToken) return;
    let cancelled = false;
    fetchReferrals(accessToken, showHandled ? undefined : false)
      .then((data) => {
        if (cancelled) return;
        setRows(data.referrals);
        setError("");
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load referrals");
      });
    return () => {
      cancelled = true;
    };
  }, [accessToken, showHandled, reload]);

  async function act(id: string, action: () => Promise<void>) {
    setBusy(id);
    setError("");
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(null);
    }
  }

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

  return (
    <main className="p-6 text-sm">
      <Link href="/admin" className="underline">
        ← All sessions
      </Link>
      <h1 className="mt-2 text-xl font-semibold">Referral inbox</h1>
      <p className="mt-1 max-w-2xl text-muted">
        Rooms paused because someone asked to talk to a person. A brief is written by the Handoff agent from shared,
        approved content only (never either private room); reach out through your own channels and mark it handled.
        Generating a brief and marking it handled are both recorded in the room&apos;s audit log.
      </p>
      <label className="mt-4 flex items-center gap-2">
        <input type="checkbox" checked={showHandled} onChange={(e) => setShowHandled(e.target.checked)} />
        Show handled referrals too
      </label>
      {error ? <p className="mt-4 text-terracotta">{error}</p> : null}
      {rows === null ? (
        <p className="mt-4">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="mt-4 text-muted">No referrals waiting.</p>
      ) : (
        <ul className="mt-4 space-y-4">
          {rows.map((row) => (
            <li key={row.id} className="border p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <Link href={`/admin/${row.id}`} className="font-semibold underline">
                  {row.topic ?? "(no topic)"}
                </Link>
                <span className="text-muted">
                  asked by {row.halted_for === "user_a" ? "Person A" : "Person B"} · opened {when(row.created_at)}
                </span>
              </div>
              <p className="mt-1 text-muted">
                {row.referral_handled_at
                  ? `Handled ${when(row.referral_handled_at)} by ${row.referral_handled_by ?? "—"}`
                  : "Not handled yet"}
                {row.referral_brief_at ? ` · brief from ${when(row.referral_brief_at)}` : ""}
              </p>
              {briefs[row.id] ? <Brief brief={briefs[row.id]} /> : null}
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  disabled={busy === row.id}
                  className="border px-2 py-1 disabled:opacity-40"
                  onClick={() =>
                    void act(row.id, async () => {
                      const { brief } = await generateBrief(row.id, accessToken);
                      setBriefs((prev) => ({ ...prev, [row.id]: brief }));
                    })
                  }
                >
                  {busy === row.id ? "Working…" : row.referral_brief_at ? "Regenerate brief" : "Write handoff brief"}
                </button>
                {!row.referral_handled_at ? (
                  <button
                    type="button"
                    disabled={busy === row.id}
                    className="border px-2 py-1 disabled:opacity-40"
                    onClick={() =>
                      void act(row.id, async () => {
                        await markReferralHandled(row.id, accessToken);
                        setReload((n) => n + 1);
                      })
                    }
                  >
                    Mark handled
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
