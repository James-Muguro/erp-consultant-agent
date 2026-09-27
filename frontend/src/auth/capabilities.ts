/**
 * Frontend mirror of the backend capability model.
 *
 * The authoritative source of truth is `src/auth/permissions.py`. This
 * file duplicates ONLY the enum values as string-literal tuples so the
 * SPA can type-check capability checks. No role→permission mapping
 * lives here — the effective permission set is computed by the backend
 * and delivered on `/api/auth/me` as `User.permissions` and
 * `User.organization_privileges`.
 *
 * If a value here ever disagrees with the backend, the backend wins.
 * Update this file and `src/auth/permissions.py` together.
 */

// ---------------------------------------------------------------------------
// Application roles
// ---------------------------------------------------------------------------
// Mirrors UserRole in src/auth/permissions.py.
export const USER_ROLES = [
  "erp_user",
  "functional_consultant",
  "developer",
  "business_development",
] as const;

export type UserRole = (typeof USER_ROLES)[number];

const USER_ROLE_LOOKUP: ReadonlySet<string> = new Set(USER_ROLES);

export function isUserRole(value: string): value is UserRole {
  return USER_ROLE_LOOKUP.has(value);
}

// ---------------------------------------------------------------------------
// Organization membership roles
// ---------------------------------------------------------------------------
// Mirrors OrganizationRole in src/auth/permissions.py. Distinct from
// application roles — the two axes never combine.
export const ORGANIZATION_ROLES = ["owner", "admin", "member"] as const;

export type OrganizationRole = (typeof ORGANIZATION_ROLES)[number];

// ---------------------------------------------------------------------------
// Application permissions
// ---------------------------------------------------------------------------
// Mirrors Permission in src/auth/permissions.py. Every value must match
// the backend enum exactly; a mismatch is a silent capability failure.
export const PERMISSIONS = [
  // Cross-cutting
  "chat:submit",
  "feedback:submit",
  "profile:edit",
  // Project lifecycle
  "project:read",
  "project:create",
  "project:edit",
  "project:delete",
  // Requirements
  "requirements:read",
  "requirements:revise",
  // Process steps
  "process_steps:read",
  "process_steps:revise",
  // Solution decisions
  "solution:read",
  "solution:record_actual",
  // Testing
  "testing:read",
  "testing:write",
  // Training
  "training:read",
  // Issues / health / coverage
  "issues:read",
  "issues:write",
  "health:read",
  // Generated documents
  "documents:read",
  "documents:generate",
  // Uploaded documents
  "uploads:read",
  "uploads:write",
  // Baselines
  "baselines:create",
  // Project artifact-grant management (Functional Consultant only)
  "project:grants:manage",
  // Reviews / consistency
  "reviews:submit",
  "consistency:run",
  // Unified consultant inbox (Phase 2.5 D3)
  "inbox:read",
    // Opportunity / TOR workflow (Phase 2.5 D1)
  "opportunity:create",
  "opportunity:read",
  "opportunity:edit",
  "opportunity:upload_tor",
  "opportunity:generate_response",
  "opportunity:mark_won",
  "opportunity:case_study_read",
  // Phase execution
  "phase:execute",
] as const;

export type Permission = (typeof PERMISSIONS)[number];

const PERMISSION_LOOKUP: ReadonlySet<string> = new Set(PERMISSIONS);

export function isPermission(value: string): value is Permission {
  return PERMISSION_LOOKUP.has(value);
}

// ---------------------------------------------------------------------------
// Organization privileges
// ---------------------------------------------------------------------------
// Mirrors OrganizationPrivilege in src/auth/permissions.py.
export const ORGANIZATION_PRIVILEGES = [
  "org:member:manage",
  "org:settings:edit",
] as const;

export type OrganizationPrivilege = (typeof ORGANIZATION_PRIVILEGES)[number];

export function isOrganizationPrivilege(
  value: string,
): value is OrganizationPrivilege {
  return (ORGANIZATION_PRIVILEGES as readonly string[]).includes(value);
}