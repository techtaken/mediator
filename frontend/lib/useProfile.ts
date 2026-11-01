"use client";

import { useEffect, useState } from "react";
import { fetchMyProfile, saveMyName } from "./api";

/** The signed-in person's name. Stays put across token refreshes, so forms aren't reset. */
export function useProfile(accessToken: string | null) {
  const [profile, setProfile] = useState<{ name: string | null; failed: boolean } | null>(null);

  useEffect(() => {
    if (!accessToken) return;
    let cancelled = false;
    fetchMyProfile(accessToken)
      .then((next) => {
        if (!cancelled) setProfile({ name: next.name, failed: false });
      })
      .catch(() => {
        if (!cancelled) setProfile((current) => current ?? { name: null, failed: true });
      });
    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  async function save(name: string) {
    if (!accessToken) return;
    const saved = await saveMyName(name, accessToken);
    setProfile({ name: saved.name, failed: false });
  }

  return {
    loading: Boolean(accessToken) && !profile,
    name: profile?.name ?? null,
    failed: profile?.failed ?? false,
    save,
  };
}
