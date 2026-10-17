import type { ChatMessage, JointSummary, Session } from "./types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TOKEN_KEY = (sessionId: string) => `mediator_invite_${sessionId}`;

export function saveInviteToken(sessionId: string, token: string) {
  sessionStorage.setItem(TOKEN_KEY(sessionId), token);
}

export function getInviteToken(sessionId: string) {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(TOKEN_KEY(sessionId));
}

async function request<T>(
  path: string,
  init: RequestInit & { accessToken?: string | null; inviteToken?: string | null } = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (init.accessToken) {
    headers.set("Authorization", `Bearer ${init.accessToken}`);
  }
  if (init.inviteToken) {
    headers.set("X-Invite-Token", init.inviteToken);
  }

  const res = await fetch(`${API}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

type AuthOpts = { accessToken?: string | null; inviteToken?: string | null };

export function createSession(context: string, accessToken: string) {
  return request<Session>("/api/sessions", {
    method: "POST",
    accessToken,
    body: JSON.stringify({ relationship_context: context }),
  });
}

export function fetchSession(id: string, auth: AuthOpts) {
  return request<Session>(`/api/sessions/${id}`, { ...auth });
}

export function fetchMessages(id: string, auth: AuthOpts) {
  return request<ChatMessage[]>(`/api/sessions/${id}/messages`, { ...auth });
}

export function sendMessage(id: string, content: string, auth: AuthOpts) {
  return request<ChatMessage[]>(`/api/sessions/${id}/messages`, {
    method: "POST",
    body: JSON.stringify({ content }),
    ...auth,
  });
}

export function markReady(id: string, ready: boolean, auth: AuthOpts) {
  return request<Session>(`/api/sessions/${id}/ready`, {
    method: "POST",
    body: JSON.stringify({ ready }),
    ...auth,
  });
}

export function fetchSummary(id: string, auth: AuthOpts) {
  return request<JointSummary>(`/api/sessions/${id}/summary`, { ...auth });
}

export function markResolved(id: string, auth: AuthOpts) {
  return request<Session>(`/api/sessions/${id}/resolve`, {
    method: "POST",
    ...auth,
  });
}
