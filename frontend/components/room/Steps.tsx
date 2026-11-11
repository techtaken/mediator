const STEPS = ["Talk privately", "Share", "Joint view"] as const;

/** Three-step progress indicator. `current` is 0-based; 3 means all done. */
export function Steps({ current }: { current: 0 | 1 | 2 | 3 }) {
  return (
    <ol className="mt-3 flex items-center gap-2 text-[11px] font-medium tracking-wide uppercase" aria-label="Progress">
      {STEPS.map((label, index) => {
        const state = index < current ? "done" : index === current ? "current" : "todo";
        return (
          <li key={label} className="flex flex-1 items-center gap-2" aria-current={state === "current" ? "step" : undefined}>
            <span
              className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] ${
                state === "done"
                  ? "bg-teal text-card"
                  : state === "current"
                    ? "bg-terracotta text-card"
                    : "border border-ink/20 text-muted"
              }`}
            >
              {state === "done" ? "✓" : index + 1}
            </span>
            <span className={state === "todo" ? "text-muted" : "text-ink"}>{label}</span>
            {index < STEPS.length - 1 ? <span className="hidden h-px flex-1 bg-ink/15 sm:block" /> : null}
          </li>
        );
      })}
    </ol>
  );
}
