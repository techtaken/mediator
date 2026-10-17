"use client";

import { Suspense, use, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { saveInviteToken } from "@/lib/api";

function JoinInner({ id }: { id: string }) {
  const router = useRouter();
  const search = useSearchParams();

  useEffect(() => {
    const token = search.get("token");
    if (token) saveInviteToken(id, token);
    router.replace(`/room/${id}`);
  }, [id, router, search]);

  return (
    <main className="px-5 py-16 text-muted">
      Opening your private room…
    </main>
  );
}

export default function JoinPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <Suspense fallback={<main className="px-5 py-16 text-muted">Opening your private room…</main>}>
      <JoinInner id={id} />
    </Suspense>
  );
}
