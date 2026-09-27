export type AccountType =
  | "erp_user"
  | "functional_consultant"
  | "developer"
  | "business_development"
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
   *  user holds no roles (e.g. an organization-only account). */
  roles: string[];
  /** Organizations the user is a member of. Empty when the user has not
   *  created or joined an organization. */
  organizations: OrganizationSummary[];
  /** Effective application permissions, computed server-side from the
   *  union of the permission sets of every role the user holds. The
   *  frontend treats this list as opaque — no role→permission mapping
   *  is duplicated here. */
  permissions: string[];
  /** Per-organization privileges, keyed by organization id. Values are
   *  the privileges granted by the user's membership role in that org
   *  (e.g. "org:member:manage", "org:settings:edit"). */
  organization_privileges: Record<string, string[]>;
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

export interface MessageResponse {
  message: string;
}

export interface PendingLoginResponse {
  pending_auth_ref: string;
  expires_in_minutes: number;
  message: string;
}

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
  status: string;
  completion_count?: number;
  last_completed_at?: string | null;
  last_completed_by_user_id?: string | null;
  reopen_note?: string | null;
  reopen_at?: string | null;
  reopen_by_user_id?: string | null;
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
  completion_count?: number;
  last_completed_at?: string | null;
  last_completed_by_user_id?: string | null;
  reopen_note?: string | null;
  reopen_at?: string | null;
  reopen_by_user_id?: string | null;
  resolved_at?: string | null;
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

export interface ErpUserGrantInfo {
  artifact_type: string;
  is_signatory: boolean;
  is_uat_participant: boolean;
}

export interface ErpUserArtifactsResponse {
  session_id: string;
  grants: ErpUserGrantInfo[];
}

export interface ErpUserSubmission {
  id: string;
  answers: string;
  submitted_at: string;
}

export interface ErpUserQuestionnaireState {
  submitted: boolean;
  last_submission: ErpUserSubmission | null;
  template_available: boolean;
  template_download_path: string | null;
}

export interface FrdStatus {
  current_revision_id: string | null;
  current_filename: string | null;
  current_generated_at: string | null;
  signed_revision_id: string | null;
  signed_action: string | null;
  signed_at: string | null;
  signed_by_user_id: string | null;
  signed_note: string | null;
  signoff_stale: boolean;
  is_signatory: boolean;
  can_sign_off: boolean;
}

export interface UatScenarioItem {
  id: string;
  scenario: string;
  priority?: string | null;
  expected_result?: string | null;
  [key: string]: unknown;
}

export interface UatScenariosResponse {
  is_uat_participant: boolean;
  scenarios: UatScenarioItem[];
}

export interface TrainingMaterialsResponse {
  steps: Array<Record<string, unknown>>;
  documents: Array<{
    label: string;
    filename: string;
    generated_at: string | null;
    download_path: string;
  }>;
}

export interface GrantRecord {
  id: string;
  user_id: string;
  user_email: string | null;
  user_name: string | null;
  artifact_type: string;
  is_signatory: boolean;
  is_uat_participant: boolean;
  granted_at: string | null;
  granted_by_user_id: string | null;
  granted_by_email: string | null;
  revoked_at: string | null;
  revoked_by_user_id: string | null;
  revoked_by_email: string | null;
}

export interface EligibleErpUser {
  user_id: string;
  email: string;
  name: string | null;
  org_role: string;
}

export interface InboxItem {
  id: string;
  source_type: string;
  source_id: string;
  session_id: string | null;
  organization_id: string | null;
  status: "pending" | "resolved";
  created_at: string | null;
  resolved_at: string | null;
  resolved_by_user_id?: string | null;
  title: string | null;
  subtitle: string | null;
  context_url: string | null;
}

export interface InboxResponse {
  items: InboxItem[];
}

export interface InboxCountResponse {
  pending: number;
}

export interface ErpUserRequestItem {
  id: string;
  request_type: string;
  subject: string;
  body: string;
  status: "open" | "resolved";
  created_at: string | null;
  resolved_at?: string | null;
  created_by_user_id?: string | null;
  resolved_by_user_id?: string | null;
}

export interface Opportunity {
  id: string;
  organization_id: string;
  title: string;
  client_name: string;
  status: "draft" | "tor_finalized" | "won" | "lost" | "archived";
  assigned_consultant_user_id: string | null;
  converted_session_id: string | null;
  owner_user_id: string | null;
  created_by_user_id: string | null;
  created_at: string | null;
  updated_at: string | null;
  won_at: string | null;
}

export interface OpportunityRequirement {
  id: string;
  opportunity_id: string;
  external_code: string | null;
  category: string | null;
  description: string;
  priority: string;
  req_type: string;
  acceptance_criteria: string | null;
  status: string;
  importance: string | null;
  fit_response: string | null;
  fit_response_ai: string | null;
  fit_response_comment: string | null;
  fit_response_ai_comment: string | null;
  ai_draft_status: "pending" | "drafted" | "finalized";
  source: string | null;
  source_excerpt: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface EligibleConsultant {
  user_id: string;
  email: string;
  name: string | null;
  org_role: string;
}

export interface CaseStudyResponse {
  session_id: string;
  project_name: string;
  module: string;
  erp_system: string;
  current_phase: string;
  completed_phases: string[];
  created_at: string | null;
  last_updated: string | null;
  requirements: { total: number; by_status: Record<string, number> };
  deliverables: Array<{ phase: string; label: string; filename: string }>;
}