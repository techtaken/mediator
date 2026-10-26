export type SessionStatus = "intake" | "building_joint" | "joint_review" | "resolved" | "halted";
export type Party = "user_a" | "user_b" | "ai";

export type Session = {
  id: string;
  status: SessionStatus;
  relationship_context: string | null;
  created_at: string;
  user_a_ready: boolean;
  user_b_ready: boolean;
  party: "user_a" | "user_b";
  invite_link: string | null;
  halted_reason: string | null;
  halt_view: "self" | "other" | null;
  halt_message: string | null;
  helplines: string[];
};

export type ChatMessage = {
  id: string;
  sender_role: Party;
  audience_role: Party;
  content: string;
  is_private: boolean;
  created_at: string;
};

export type JointSummary = {
  user_a_perspective: string;
  user_b_perspective: string;
  compromises: string[];
  created_at: string;
};
