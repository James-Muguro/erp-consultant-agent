export type AccountType =
  | "erp_user"
  | "functional_consultant"
  | "developer"
  | "marketer"
  | "organization";

export interface SignupPayload {
  email: string;
  password: string;
  account_type: AccountType;
  /** Only sent when account_type === "organization". */
  organization_name?: string;
}

export interface OrganizationSummary {
  id: string;
  name: string;
  /** "owner" | "admin" | "member" — organization role, separate from
   *  application roles. */
  role: string;
}

export interface User {
  id: string;
  email: string;
  name: string | null;
  profile_picture_url: string | null;
  created_at: string;
  /** Application roles. Populated from the /me response; empty when the
   *  user holds no roles (should not happen for a signed-up user). */
  roles: string[];
  /** Organizations the user is a member of. Empty when the user has not
   *  created or joined an organization. */
  organizations: OrganizationSummary[];
}

export interface ProjectSummary {
  session_id: string;
  project_name: string;
  module: string;
  erp_system: string;
  is_casual: boolean;
  is_archived: boolean;
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

export type TurnState =
  | { status: "streaming" }
  | { status: "complete" }
  | { status: "aborted" }
  | { status: "failed"; error: string; retryable: boolean };

export interface ChatMessage {
  id: string;
  role: ChatRole;
  text: string;
  createdAt: number;
  documents?: DocumentRef[];
  nextAction?: NextAction | null;
  turnState?: TurnState;
  sendParams?: {
    agentHint?: string;
    preferWeb?: boolean;
  };
}

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

export type ReviewStatus = "draft" | "approved" | "rejected";

export interface RequirementItem {
  id: string;
  category: string;
  description: string;
  priority: string | null;
  type: string | null;
  acceptance_criteria: string | null;
  status: ReviewStatus;
}

export interface ProcessStep {
  id: string;
  process_name: string;
  step_number: number;
  name: string;
  description: string | null;
  responsible_role: string | null;
  requirement_id: string | null;
}

export interface SolutionDecision {
  id: string;
  decision_type: string;
  component: string | null;
  description: string;
  rationale: string | null;
  requirement_id: string | null;
  status: ReviewStatus;
}

export interface TestCase {
  id: string;
  test_type: string;
  external_code: string | null;
  scenario: string;
  priority: string | null;
  expected_result: string | null;
}

export interface TrainingStep {
  id: string;
  title: string;
  instructions: string | null;
}

export type IssueSeverity = "low" | "medium" | "high";

export interface ProjectIssue {
  id: string;
  issue_type: string;
  severity: IssueSeverity;
  description: string;
  status: string;
  related_object_type: string | null;
  related_object_id: string | null;
}

export interface ProjectHealth {
  requirements_total: number;
  requirements_by_status: Record<string, number>;
  requirements_coverage_pct: number;
  open_issues_total: number;
  open_issues_by_severity: Record<string, number>;
  uncovered_requirements_count: number;
  untested_requirements_count: number;
  has_active_baseline: boolean;
}

export interface CoverageGapRequirement {
  id: string;
  external_code: string | null;
  category: string;
  description: string;
  priority: string | null;
}

export interface CoverageGaps {
  session_id: string;
  uncovered_requirements: CoverageGapRequirement[];
  untested_requirements: CoverageGapRequirement[];
}

export interface UploadedDocument {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  extracted_text_chars: number;
  uploaded_at: string;
}

export type ReviewAction = "approved" | "rejected" | "corrected";