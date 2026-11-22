"use client";

import { useEffect } from "react";

/**
 * Flags the browser tab ("(1) Ravi is ready · Mediator") when `alert` appears
 * while this tab is in the background, and puts the title back once the
 * person looks at it again.
 */
export function useTabAlert(alert: string | null) {
  useEffect(() => {
    if (!alert || typeof document === "undefined") return;
    const original = document.title;
    let flagged = false;

    const flag = () => {
      if (document.hidden && !flagged) {
        document.title = `(1) ${alert} · Mediator`;
        flagged = true;
      } else if (!document.hidden && flagged) {
        document.title = original;
        flagged = false;
      }
    };

    // Seen already if it showed up while they were looking at this tab.
    if (document.hidden) flag();
    const onVisibility = () => {
      if (!document.hidden) flag();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      if (flagged) document.title = original;
    };
  }, [alert]);
}
