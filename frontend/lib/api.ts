import type {
  ChatMessage,
  CheckInAnswers,
  FollowUp,
  IdeaResponse,
  JointState,
  JointSummary,
  Language,
  RoomSummary,
  Session,
  ShareDraft,
  Translation,
} from "./types";

export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TOKEN_KEY = (sessionId: string) => `mediator_invite_${sessionId}`;

// Kept in localStorage so the invited person can come back on the same device
// (closing the tab, or WhatsApp's in-app browser, used to lose access).
export function saveInviteToken(sessionId: string, token: string) {
  try {
    localStorage.setItem(TOKEN_KEY(sessionId), token);
  } catch {
    sessionStorage.setItem(TOKEN_KEY(sessionId), token);
  }
}

export function getInviteToken(sessionId: string) {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(TOKEN_KEY(sessionId)) ?? sessionStorage.getItem(TOKEN_KEY(sessionId));
  } catch {
    return sessionStorage.getItem(TOKEN_KEY(sessionId));
  }
}

/** An API error that keeps the HTTP status, so pages can react to 404 / 410. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export async function request<T>(
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
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export type AuthOpts = { accessToken?: string | null; inviteToken?: string | null };

export function createSession(topic: string, context: string, accessToken: string) {
  return request<Session>("/api/sessions", {
    method: "POST",
    accessToken,
    body: JSON.stringify({ topic, relationship_context: context }),
  });
}

export function fetchMyRooms(accessToken: string) {
  return request<RoomSummary[]>("/api/sessions", { accessToken });
}

export function acceptConsent(id: string, auth: AuthOpts) {
  return request<Session>(`/api/sessions/${id}/consent`, { method: "POST", ...auth });
}

/** Stop the room for both people. */
export function leaveSession(id: string, auth: AuthOpts) {
  return request<Session>(`/api/sessions/${id}/leave`, { method: "POST", ...auth });
}

/** Pause the room and flag it for the Mediator team. */
export function askForPerson(id: string, auth: AuthOpts) {
  return request<Session>(`/api/sessions/${id}/human`, { method: "POST", ...auth });
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

export function draftShare(id: string, auth: AuthOpts) {
  return request<ShareDraft>(`/api/sessions/${id}/share/draft`, { method: "POST", ...auth });
}

export function approveShare(id: string, text: string, auth: AuthOpts) {
  return request<Session>(`/api/sessions/${id}/share/approve`, {
    method: "POST",
    body: JSON.stringify({ text }),
    ...auth,
  });
}

/** Retry building the joint view once both people have shared. */
export function retryJoint(id: string, auth: AuthOpts) {
  return request<Session>(`/api/sessions/${id}/joint`, { method: "POST", ...auth });
}

/** Withdraw the approved share and readiness, reopening private chat. */
export function withdrawShare(id: string, auth: AuthOpts) {
  return request<Session>(`/api/sessions/${id}/ready`, {
    method: "POST",
    body: JSON.stringify({ ready: false }),
    ...auth,
  });
}

export function fetchSummary(id: string, auth: AuthOpts) {
  return request<JointSummary>(`/api/sessions/${id}/summary`, { ...auth });
}

export function fetchJoint(id: string, auth: AuthOpts) {
  return request<JointState>(`/api/sessions/${id}/joint`, { ...auth });
}

export function suggestIdea(id: string, text: string, auth: AuthOpts) {
  return request<JointState>(`/api/sessions/${id}/ideas`, {
    method: "POST",
    body: JSON.stringify({ text }),
    ...auth,
  });
}

export function respondToIdea(id: string, ideaId: string, response: IdeaResponse, note: string | null, auth: AuthOpts) {
  return request<JointState>(`/api/sessions/${id}/ideas/${ideaId}/response`, {
    method: "POST",
    body: JSON.stringify({ response, note }),
    ...auth,
  });
}

export function draftAgreement(id: string, auth: AuthOpts) {
  return request<JointState>(`/api/sessions/${id}/agreement/draft`, { method: "POST", ...auth });
}

/** checkinDays: days until this person's private check-in (0 = none, null = default). */
export function signAgreement(id: string, version: number, checkinDays: number | null, auth: AuthOpts) {
  return request<JointState>(`/api/sessions/${id}/agreement/sign`, {
    method: "POST",
    body: JSON.stringify(checkinDays === null ? { version } : { version, checkin_days: checkinDays }),
    ...auth,
  });
}

export function setLanguage(id: string, language: Language, auth: AuthOpts) {
  return request<Session>(`/api/sessions/${id}/language`, {
    method: "POST",
    body: JSON.stringify({ language }),
    ...auth,
  });
}

/** The other person's approved words, with a translation for this person when one could be made. */
export function fetchTranslation(id: string, language: Language, auth: AuthOpts) {
  return request<Translation>(`/api/sessions/${id}/translation?language=${language}`, { ...auth });
}

/** Private "think it through" questions about one idea. */
export function thinkItThrough(id: string, ideaId: string, auth: AuthOpts) {
  return request<JointState>(`/api/sessions/${id}/ideas/${ideaId}/think`, { method: "POST", ...auth });
}

export function fetchFollowUp(id: string, auth: AuthOpts) {
  return request<FollowUp>(`/api/sessions/${id}/followup`, { ...auth });
}

export function answerFollowUp(id: string, answers: CheckInAnswers, auth: AuthOpts) {
  return request<FollowUp>(`/api/sessions/${id}/followup`, {
    method: "POST",
    body: JSON.stringify(answers),
    ...auth,
  });
}

/** Open the joint session again after a check-in. */
export function reopenJoint(id: string, auth: AuthOpts) {
  return request<JointState>(`/api/sessions/${id}/reopen`, { method: "POST", ...auth });
}

/** Person A replaces the invite link before the other person joins. */
export function rotateInvite(id: string, auth: AuthOpts) {
  return request<Session>(`/api/sessions/${id}/invite/rotate`, { method: "POST", ...auth });
}

/** Delete this person's private chat, notes and drafts. */
export function deleteMyData(id: string, auth: AuthOpts) {
  return request<Session>(`/api/sessions/${id}/delete-my-data`, { method: "POST", ...auth });
}

/** Person A deletes the whole room for both people. */
export function deleteRoom(id: string, auth: AuthOpts) {
  return request<{ deleted: boolean }>(`/api/sessions/${id}`, { method: "DELETE", ...auth });
}
