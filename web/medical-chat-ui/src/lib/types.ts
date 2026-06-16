export interface MessageMetadata {
  intent: string;
  route_mode: string;
  route_mode_label: string;
  route_reason: string;
  plan_summary: string;
  audit_log: string[];
  awaiting_user: boolean;
  done: boolean;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  metadata: MessageMetadata;
}

export interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface SessionDetail extends ChatSession {
  messages: ChatMessage[];
}

export interface UserProfile {
  id: string;
  email: string | null;
}

export interface SendMessageResponse {
  message: ChatMessage;
  session: ChatSession;
}
