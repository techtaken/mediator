"use client";

import { useState } from "react";
import type { IdeaResponse, JointIdea } from "@/lib/types";

const CHOICES: { value: IdeaResponse; label: string }[] = [
  { value: "yes", label: "Works for me" },
  { value: "change", label: "Needs a change" },
  { value: "no", label: "Not for me" },
];

const THEIR_ANSWER: Record<IdeaResponse, string> = {
  yes: "Works for them",
  change: "Needs a change",
  no: "Not for them",
};

function sourceLabel(source: JointIdea["source"], otherName: string | null | undefined) {
  if (source === "mediator") return "Suggested by the mediator";
  if (source === "you") return "Your idea";
  return otherName ? `${otherName}'s idea` : "Their idea";
}

type Props = {
  idea: JointIdea;
  index: number;
  locked: boolean;
  otherName?: string | null;
  onAnswer: (response: IdeaResponse, note: string | null) => Promise<void>;
  onThink?: () => Promise<void>;
};

export function IdeaCard({ idea, index, locked, otherName, onAnswer, onThink }: Props) {
  const [noteOpen, setNoteOpen] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [note, setNote] = useState(idea.my_note ?? "");
  const [saving, setSaving] = useState(false);

  async function answer(response: IdeaResponse, withNote: string | null = null) {
    setSaving(true);
    try {
      await onAnswer(response, withNote);
      setNoteOpen(false);
    } finally {
      setSaving(false);
    }
  }

  function choose(response: IdeaResponse) {
    if (response === "change") {
      setNoteOpen(true);
      return;
    }
    void answer(response);
  }

  const theirLine = !idea.other_responded
    ? "No answer yet"
    : !idea.my_response
      ? "They've answered. Give yours to see it."
      : idea.other_response
        ? THEIR_ANSWER[idea.other_response]
        : "";

  return (
    <li
      className={`rounded-3xl p-4 transition ${
        idea.agreed ? "bg-teal/10 ring-1 ring-teal/30" : "bg-card shadow-[0_1px_0_rgba(36,28,22,0.08)]"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-[11px] font-medium tracking-[0.14em] text-muted uppercase">{sourceLabel(idea.source, otherName)}</p>
        {idea.agreed ? (
          <span className="shrink-0 rounded-full bg-teal px-2.5 py-0.5 text-[11px] font-medium text-card">✓ Agreed</span>
        ) : null}
      </div>
      <p className="mt-1.5 flex gap-2.5 text-[15px] leading-relaxed text-ink">
        <span className="font-[family-name:var(--font-display)] text-lg leading-none text-terracotta">{index + 1}</span>
        <span>{idea.text}</span>
      </p>

      {locked ? null : (
        <div className="mt-3 grid grid-cols-3 gap-1.5" role="group" aria-label={`Your answer to idea ${index + 1}`}>
          {CHOICES.map((choice) => {
            const selected = idea.my_response === choice.value;
            return (
              <button
                key={choice.value}
                type="button"
                disabled={saving}
                aria-pressed={selected}
                onClick={() => choose(choice.value)}
                className={`rounded-full px-2 py-2 text-[13px] leading-tight transition disabled:opacity-50 ${
                  selected
                    ? choice.value === "yes"
                      ? "bg-teal text-card"
                      : "bg-ink text-card"
                    : "border border-ink/15 bg-paper text-ink hover:border-ink/30"
                }`}
              >
                {choice.label}
              </button>
            );
          })}
        </div>
      )}

      {noteOpen && !locked ? (
        <div className="mt-3">
          <label className="block text-[13px] text-muted">
            What would need to change? <span className="text-muted/80">They&apos;ll see this.</span>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value.slice(0, 300))}
              rows={2}
              maxLength={300}
              autoFocus
              placeholder="e.g. Only for trips longer than a weekend"
              className="mt-1.5 w-full resize-none rounded-2xl border border-ink/10 bg-paper px-3 py-2 text-sm text-ink outline-none focus:border-terracotta"
            />
          </label>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              disabled={saving}
              onClick={() => void answer("change", note.trim() || null)}
              className="rounded-full bg-ink px-4 py-1.5 text-[13px] text-card disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save answer"}
            </button>
            <button type="button" onClick={() => setNoteOpen(false)} className="px-2 text-[13px] text-muted">
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {idea.my_questions.length ? (
        <div className="mt-3 rounded-2xl bg-paper px-3 py-2.5">
          <p className="text-[12px] font-medium tracking-[0.12em] text-muted uppercase">Think it through · only you see this</p>
          <ul className="mt-1.5 space-y-1.5 text-[14px] leading-snug text-ink">
            {idea.my_questions.map((item) => (
              <li key={item.type} className="flex gap-2">
                <span aria-hidden className="text-terracotta">?</span>
                <span>{item.question}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : onThink && !locked ? (
        <button
          type="button"
          disabled={thinking}
          onClick={() => {
            setThinking(true);
            void onThink().finally(() => setThinking(false));
          }}
          className="mt-2.5 text-[13px] text-teal underline-offset-4 hover:underline disabled:opacity-50"
        >
          {thinking ? "Thinking…" : "Think it through privately"}
        </button>
      ) : null}

      <div className="mt-3 space-y-1 text-[13px] leading-snug">
        {idea.my_response === "change" && idea.my_note && !noteOpen ? (
          <p className="text-muted">
            You: <span className="text-ink">“{idea.my_note}”</span>
          </p>
        ) : null}
        {theirLine ? (
          <p className={idea.other_response === "yes" && idea.my_response ? "text-teal" : "text-muted"}>
            {otherName ?? "Them"}: {theirLine}
            {idea.my_response && idea.other_note ? <span className="text-ink"> · “{idea.other_note}”</span> : null}
          </p>
        ) : null}
      </div>
    </li>
  );
}
