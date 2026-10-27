"use client";

import { useState } from "react";
import type { Language } from "@/lib/types";

const OPTIONS: { value: Language; label: string; hint: string }[] = [
  { value: "en", label: "English", hint: "English" },
  { value: "hinglish", label: "Hinglish", hint: "Hindi + English" },
  { value: "hi", label: "हिन्दी", hint: "Devanagari" },
];

/** The mediator's reply language. Unset means it matches how the person writes. */
export function LanguagePicker({ value, onChange }: { value: Language | null; onChange: (language: Language) => Promise<void> }) {
  const [saving, setSaving] = useState<Language | null>(null);

  async function choose(language: Language) {
    setSaving(language);
    try {
      await onChange(language);
    } finally {
      setSaving(null);
    }
  }

  return (
    <div className="mt-2 grid grid-cols-3 gap-1.5" role="radiogroup" aria-label="Reply language">
      {OPTIONS.map((option) => {
        const selected = value === option.value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={saving !== null}
            onClick={() => void choose(option.value)}
            className={`rounded-2xl px-2 py-2 text-center transition disabled:opacity-60 ${
              selected ? "bg-ink text-card" : "border border-ink/15 bg-paper text-ink hover:border-ink/30"
            }`}
          >
            <span className="block text-[14px] leading-tight">{saving === option.value ? "…" : option.label}</span>
            <span className={`block text-[11px] leading-tight ${selected ? "text-card/70" : "text-muted"}`}>{option.hint}</span>
          </button>
        );
      })}
    </div>
  );
}
