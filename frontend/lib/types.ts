export type SessionStatus = "intake" | "building_joint" | "joint_review" | "resolved" | "halted";
export type Party = "user_a" | "user_b" | "ai";

export type Session = {
  id: string;
  status: SessionStatus;
  topic: string | null;
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
  my_share: string | null;
  i_consented: boolean;
};

export type RoomSummary = {
  id: string;
  status: SessionStatus;
  topic: string | null;
  created_at: string;
  user_a_ready: boolean;
  user_b_ready: boolean;
};

export type ShareDraft = {
  draft: string | null;
  left_out: string[];
  approved: string | null;
  approved_at: string | null;
};

export type ChatMessage = {
  id: string;
  sender_role: Party;
  audience_role: Party;
  content: string;
  is_private: boolean;
  created_at: string;
};

export type IdeaResponse = "yes" | "change" | "no";

export type JointIdea = {
  id: string;
  text: string;
  source: "mediator" | "you" | "them";
  my_response: IdeaResponse | null;
  my_note: string | null;
  other_responded: boolean;
  other_response: IdeaResponse | null;
  other_note: string | null;
  agreed: boolean;
};

export type Agreement = {
  version: number;
  summary: string | null;
  terms: string[];
  flags: string[];
  signed_by_me_at: string | null;
  signed_by_them_at: string | null;
  fully_signed: boolean;
  created_at: string | null;
};

export type JointState = {
  ideas: JointIdea[];
  agreed_count: number;
  agreement: Agreement | null;
};

export type JointSummary = {
  user_a_perspective: string;
  user_b_perspective: string;
  common_ground: string | null;
  compromises: string[];
  created_at: string;
};
