"use client";

import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { getSupabase } from "./supabase";

export function useAuth() {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const supabase = getSupabase();
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, next) => {
      setSession(next);
    });
    // Signing in from the email link usually happens in another tab. Pick it
    // up when that tab saves the session, or when this one is looked at again.
    const recheck = () => {
      if (document.visibilityState === "visible") {
        void supabase.auth.getSession().then(({ data }) => setSession(data.session));
      }
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key?.startsWith("sb-")) recheck();
    };
    document.addEventListener("visibilitychange", recheck);
    window.addEventListener("storage", onStorage);
    return () => {
      sub.subscription.unsubscribe();
      document.removeEventListener("visibilitychange", recheck);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  return {
    session,
    user: session?.user ?? null,
    accessToken: session?.access_token ?? null,
    loading,
  };
}
