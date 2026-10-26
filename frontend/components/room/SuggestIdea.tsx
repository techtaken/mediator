"use client";

import { useState } from "react";

const MIN = 10;
const MAX = 300;

/** Lets either person add their own idea; it counts as a "yes" from them. */
export function SuggestIdea({ onSuggest }: { onSuggest: (text: string) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit() {
    const value = text.trim();
    if (value.length < MIN) return;
    setSaving(true);
    try {
      await onSuggest(value);
      setText("");
      setOpen(false);
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-3 w-full rounded-3xl border border-dashed border-ink/20 px-4 py-3.5 text-left text-[15px] text-ink hover:border-ink/35"
      >
        <span className="text-terracotta">+</span> Suggest your own idea
      </button>
    );
  }

  return (
    <div className="mt-3 rounded-3xl border border-ink/15 bg-card p-4">
      <label className="block text-[13px] text-muted">
        Write it as something you could both do. They&apos;ll see it, and it counts as a yes from you.
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value.slice(0, MAX))}
          rows={3}
          maxLength={MAX}
          autoFocus
          placeholder="e.g. Call each other before booking any family trip"
          className="mt-2 w-full resize-none rounded-2xl border border-ink/10 bg-paper px-3 py-2 text-[15px] text-ink outline-none focus:border-terracotta"
        />
      </label>
      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          disabled={saving || text.trim().length < MIN}
          onClick={() => void submit()}
          className="rounded-full bg-teal px-4 py-2 text-sm text-card disabled:opacity-50"
        >
          {saving ? "Checking…" : "Add idea"}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="px-2 text-sm text-muted">
          Cancel
        </button>
        <span className="ml-auto text-xs text-muted">
          {text.trim().length}/{MAX}
        </span>
      </div>
    </div>
  );
}
