import { request } from "./api";
import type { ChatMessage, SessionStatus } from "./types";

export type AdminSessionRow = {
  id: string;
  status: SessionStatus;
  topic: string | null;
  relationship_context: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string | null;
  user_a_ready: boolean;
  user_b_ready: boolean;
  halted_for: "user_a" | "user_b" | null;
  halt_kind: string | null;
  messages_a: number;
  messages_b: number;
  last_activity: string | null;
};

export type AdminSessionList = {
  sessions: AdminSessionRow[];
  limit: number;
  offset: number;
  has_more: boolean;
};

export type AuditEvent = {
  id: number;
  stage: string | null;
  agent: string | null;
  gate: number | null;
  reason: string | null;
  payload: Record<string, unknown>;
  created_at: string;
};

export type PrivateMemory = {
  party_role: "user_a" | "user_b";
  notes: string;
  profile: Record<string, unknown>;
  updated_at: string;
};

export type AdminSessionDetail = {
  session: Omit<AdminSessionRow, "messages_a" | "messages_b" | "last_activity"> & Record<string, unknown>;
  rooms: { user_a: ChatMessage[]; user_b: ChatMessage[] };
  private_memories: Partial<Record<"user_a" | "user_b", PrivateMemory>>;
  state: Record<string, unknown>;
  audit_events: AuditEvent[];
  joint: {
    ideas: { id: string; text: string; source: string; position: number }[];
    responses: { idea_id: string; party_role: "user_a" | "user_b"; response: string; note: string | null }[];
    agreement: Record<string, unknown> | null;
  };
  joint_summary: {
    user_a_perspective: string;
    user_b_perspective: string;
    compromises: string[];
    created_at: string;
  } | null;
};

export function fetchAdminSessions(
  accessToken: string,
  opts: { status?: string; limit?: number; offset?: number } = {},
) {
  const params = new URLSearchParams();
  if (opts.status) params.set("status", opts.status);
  params.set("limit", String(opts.limit ?? 50));
  params.set("offset", String(opts.offset ?? 0));
  return request<AdminSessionList>(`/api/admin/sessions?${params}`, { accessToken });
}

export function fetchAdminSession(id: string, accessToken: string) {
  return request<AdminSessionDetail>(`/api/admin/sessions/${id}`, { accessToken });
}
