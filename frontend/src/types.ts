export interface User {
  id: string;
  email: string;
  created_at: string;
}

export interface ProjectSummary {
  session_id: string;
  project_name: string;
  module: string;
  erp_system: string;
  is_casual: boolean;
  current_phase: string;
  completed_phases: string[];
  phases_completed: number;
  total_conversations: number;
  total_decisions: number;
  created_at: string;
  last_updated: string;
}

export interface ProjectStatus {
  session_id: string;
  project_name: string;
  module: string;
  current_phase: string;
  completed_phases: string[];
  progress_percentage: number;
  next_phase: string | null;
  created_at: string;
  last_updated: string;
}

export interface DocumentRef {
  phase: string;
  label: string;
  filename: string;
}

export interface NextAction {
  label: string;
  agent_hint: string;
}

export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  text: string;
  createdAt: number;
  documents?: DocumentRef[];
  isStreaming?: boolean;
  error?: boolean;
  nextAction?: NextAction | null;
}
/** One parsed Server-Sent Event from /api/chat/stream. */
export interface ChatStreamEvent {
  type:
    | "message_start"
    | "agent_started"
    | "agent_progress"
    | "tool_started"
    | "tool_completed"
    | "text_delta"
    | "document_created"
    | "workflow_completed"
    | "message_complete"
    | "error";
  data: Record<string, unknown>;
}

export interface ApiErrorBody {
  error: {
    code: number;
    message: string;
    request_id: string | null;
  };
}
