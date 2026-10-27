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

export type CallStats = {
  calls: number;
  failed: number;
  attempts: number;
  prompt_tokens: number;
  output_tokens: number;
  latency_ms: number;
  avg_latency_ms: number;
  estimated_cost_usd: number;
  price_per_m: { input: number; output: number };
  by_role: Record<string, { calls: number; failed: number; prompt_tokens: number; output_tokens: number; latency_ms: number }>;
};

export type AdminSessionDetail = {
  session: Omit<AdminSessionRow, "messages_a" | "messages_b" | "last_activity"> & Record<string, unknown>;
  rooms: { user_a: ChatMessage[]; user_b: ChatMessage[] };
  private_memories: Partial<Record<"user_a" | "user_b", PrivateMemory>>;
  state: Record<string, unknown>;
  audit_events: AuditEvent[];
  agent_calls: CallStats;
  followups: {
    id: string;
    party_role: "user_a" | "user_b";
    round: number;
    status: string;
    due_at: string;
    answers: Record<string, unknown> | null;
    reply: string | null;
  }[];
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

export type ReferralRow = {
  id: string;
  status: SessionStatus;
  topic: string | null;
  relationship_context: string | null;
  created_at: string;
  updated_at: string | null;
  halted_for: "user_a" | "user_b" | null;
  referral_brief_at: string | null;
  referral_handled_at: string | null;
  referral_handled_by: string | null;
};

export type HandoffBrief = Record<string, unknown> & {
  urgency?: string;
  handoff_reason?: string;
  dispute_summary?: string;
  issues?: unknown[];
  progress_so_far?: unknown[];
  what_didnt_work?: unknown[];
  suggested_starting_point?: string;
};

export function fetchReferrals(accessToken: string, handled?: boolean) {
  const query = handled === undefined ? "" : `?handled=${handled}`;
  return request<{ referrals: ReferralRow[] }>(`/api/admin/referrals${query}`, { accessToken });
}

export function generateBrief(id: string, accessToken: string) {
  return request<{ brief: HandoffBrief }>(`/api/admin/referrals/${id}/brief`, { method: "POST", accessToken });
}

export function markReferralHandled(id: string, accessToken: string) {
  return request<{ handled: boolean }>(`/api/admin/referrals/${id}/handled`, { method: "POST", accessToken });
}

export function fetchAdminSession(id: string, accessToken: string) {
  return request<AdminSessionDetail>(`/api/admin/sessions/${id}`, { accessToken });
}
