"""
Centralized permission model for the application.

This module is the single source of truth for:
  * what application roles exist (UserRole)
  * what permissions exist (Permission)
  * what permissions each application role grants (ROLE_PERMISSIONS)
  * what organization membership roles exist (OrganizationRole)
  * what administrative privileges each org role grants (ORG_ROLE_PRIVILEGES)

It contains no database access and no FastAPI dependencies. DB queries
live in src/auth/rbac.py; FastAPI guards live in src/auth/guards.py.

Two axes, never combined
------------------------
  * Application roles grant feature permissions across the whole product.
  * Organization membership roles grant administrative capability within
    a single organization. Neither axis implies the other.

A user's effective application permissions are the UNION of the
permission sets of every application role they hold. Roles add, never
subtract. 'Functional Consultant + Developer' is strictly more capable
than either alone.

Role capability authority
-------------------------
The product capability lists provided for each role are authoritative.
Where this file's mappings disagree with a list, this file is updated to
match the list. Do not infer a permission from a generic phrase such as
'Project workspace'; permission grants are only added when the capability
list names the specific action or it is unambiguously entailed.

Known capability gaps (not compensated for here)
------------------------------------------------
Several product capabilities named in the role lists have no backend
support yet. They are deliberately NOT modelled as permissions in this
module, because granting a permission for a capability that has no
enforcement point would create the illusion of security without
protecting anything. Current gaps:

  * ERP User 'Assigned project, read-only' - no project-assignments
    table, no assignment endpoint. ERP User holds read permissions but
    has no project to read until the assignment mechanism exists.
  * ERP User 'My tickets/requests' - no ticket/request entity.
  * Marketer 'Content library', 'Testimonial/outcome tracker' - no
    corresponding entities or endpoints.
  * Organization 'Cross-project analytics', 'Firm knowledge base',
    'Billing/subscription', 'Invitations' - each requires new product
    surfaces, none of which are part of the RBAC/multitenancy
    foundation.

Each of these is a separate feature, not a permission-module change.
"""
from __future__ import annotations

from enum import Enum
from typing import Iterable


# ---------------------------------------------------------------------------
# Application roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    """The four application roles.

    'Organization' is deliberately NOT a member of this enum. Organization
    is a tenant context created by signing up with the 'organization'
    account type; it is not a role a user holds.
    """
    ERP_USER = "erp_user"
    FUNCTIONAL_CONSULTANT = "functional_consultant"
    DEVELOPER = "developer"
    MARKETER = "marketer"


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
class Permission(str, Enum):
    """Every feature permission the application recognizes.

    Naming convention: 'resource:action'. Read and write are always
    distinct permissions so that a read-only role (ERP User) cannot be
    accidentally granted a write path by conflating the two.

    Only permissions that map to an existing endpoint are listed here.
    """
    # Cross-cutting
    CHAT_SUBMIT = "chat:submit"
    FEEDBACK_SUBMIT = "feedback:submit"
    PROFILE_EDIT = "profile:edit"

    # Project lifecycle
    PROJECT_READ = "project:read"
    PROJECT_CREATE = "project:create"
    PROJECT_EDIT = "project:edit"
    PROJECT_DELETE = "project:delete"

    # Requirements
    REQUIREMENTS_READ = "requirements:read"
    REQUIREMENTS_REVISE = "requirements:revise"

    # Process steps
    PROCESS_STEPS_READ = "process_steps:read"
    PROCESS_STEPS_REVISE = "process_steps:revise"

    # Solution decisions
    SOLUTION_READ = "solution:read"
    SOLUTION_RECORD_ACTUAL = "solution:record_actual"

    # Testing (QA + UAT)
    TESTING_READ = "testing:read"
    TESTING_WRITE = "testing:write"

    # Training
    TRAINING_READ = "training:read"

    # Issues / health / coverage
    ISSUES_READ = "issues:read"
    HEALTH_READ = "health:read"

    # Generated documents
    DOCUMENTS_READ = "documents:read"
    DOCUMENTS_GENERATE = "documents:generate"

    # Uploaded project documents
    UPLOADS_READ = "uploads:read"
    UPLOADS_WRITE = "uploads:write"

    # Baselines
    BASELINES_CREATE = "baselines:create"

    # Reviews and consistency checks
    REVIEWS_SUBMIT = "reviews:submit"
    CONSISTENCY_RUN = "consistency:run"

    # Phase execution
    PHASE_EXECUTE = "phase:execute"


# ---------------------------------------------------------------------------
# Role -> permission mappings
# ---------------------------------------------------------------------------
# Read permissions shared by every role with any project visibility.
_READ_PERMS: frozenset = frozenset({
    Permission.PROJECT_READ,
    Permission.REQUIREMENTS_READ,
    Permission.PROCESS_STEPS_READ,
    Permission.SOLUTION_READ,
    Permission.TESTING_READ,
    Permission.TRAINING_READ,
    Permission.ISSUES_READ,
    Permission.HEALTH_READ,
    Permission.DOCUMENTS_READ,
    Permission.UPLOADS_READ,
})

# Cross-cutting permissions every signed-in user has regardless of role.
_COMMON_USER_PERMS: frozenset = frozenset({
    Permission.CHAT_SUBMIT,
    Permission.FEEDBACK_SUBMIT,
    Permission.PROFILE_EDIT,
})

# Functional Consultant write set. Derived from the Functional Consultant
# capability list: Requirements, Process mapping, Solution design,
# Testing, Training, Traceability view, Review/audit trail, New project
# creation, Documents, plus phase execution.
_CONSULTANT_WRITE_PERMS: frozenset = frozenset({
    Permission.PROJECT_CREATE,
    Permission.PROJECT_EDIT,
    Permission.PROJECT_DELETE,
    Permission.REQUIREMENTS_REVISE,
    Permission.PROCESS_STEPS_REVISE,
    Permission.SOLUTION_RECORD_ACTUAL,
    Permission.TESTING_WRITE,
    Permission.DOCUMENTS_GENERATE,
    Permission.UPLOADS_WRITE,
    Permission.BASELINES_CREATE,
    Permission.REVIEWS_SUBMIT,
    Permission.CONSISTENCY_RUN,
    Permission.PHASE_EXECUTE,
})

# Developer write set. Derived from the Developer capability list:
#   * Solution design        -> SOLUTION_RECORD_ACTUAL
#   * Testing                -> TESTING_WRITE
#   * Documents              -> DOCUMENTS_GENERATE, UPLOADS_WRITE
#   * Configuration/implementation notes -> part of the workspace work
#     surface, covered by the write set below.
#   * Phase execution is required to produce design/test artifacts.
#
# Deliberately EXCLUDED (per product decisions on Round 3b):
#   * PROJECT_CREATE, PROJECT_EDIT, PROJECT_DELETE - project management
#     belongs to Functional Consultant.
#   * REQUIREMENTS_REVISE - Developer sees requirements read-only.
#   * PROCESS_STEPS_REVISE - process mapping belongs to Functional
#     Consultant.
#   * REVIEWS_SUBMIT, CONSISTENCY_RUN, BASELINES_CREATE - these writes
#     belong to Functional Consultant only.
#
# Written as an explicit set rather than 'consultant minus X' so that
# future changes to the consultant set do not silently leak into the
# Developer set.
_DEVELOPER_WRITE_PERMS: frozenset = frozenset({
    Permission.SOLUTION_RECORD_ACTUAL,
    Permission.TESTING_WRITE,
    Permission.DOCUMENTS_GENERATE,
    Permission.UPLOADS_WRITE,
    Permission.PHASE_EXECUTE,
})

# Marketer permission set. The product capability list grants:
#   * Chat                   -> CHAT_SUBMIT
#   * Project list, case-study view -> PROJECT_READ
#   * Document generation    -> DOCUMENTS_GENERATE, DOCUMENTS_READ
#   * Account/profile        -> PROFILE_EDIT
#
# 'Content library' and 'Testimonial/outcome tracker' have no backend
# support and are NOT modelled as permissions (see module docstring).
_MARKETER_PERMS: frozenset = _COMMON_USER_PERMS | frozenset({
    Permission.PROJECT_READ,
    Permission.DOCUMENTS_READ,
    Permission.DOCUMENTS_GENERATE,
})


ROLE_PERMISSIONS: dict = {
    # ERP User: assigned-project read-only plus cross-cutting. No
    # PROJECT_CREATE - see the module docstring's capability-gap note.
    UserRole.ERP_USER: _COMMON_USER_PERMS | _READ_PERMS,

    # Functional Consultant: full project scope.
    UserRole.FUNCTIONAL_CONSULTANT: (
        _COMMON_USER_PERMS | _READ_PERMS | _CONSULTANT_WRITE_PERMS
    ),

    # Developer: full read scope, targeted writes.
    UserRole.DEVELOPER: (
        _COMMON_USER_PERMS | _READ_PERMS | _DEVELOPER_WRITE_PERMS
    ),

    # Marketer: cross-cutting plus project read and documents.
    UserRole.MARKETER: _MARKETER_PERMS,
}


def effective_permissions(roles: Iterable[UserRole]) -> frozenset:
    """Union of the permission sets of every application role held."""
    out: set = set()
    for r in roles:
        out.update(ROLE_PERMISSIONS.get(r, frozenset()))
    return frozenset(out)


# ---------------------------------------------------------------------------
# Organization roles and privileges
# ---------------------------------------------------------------------------
class OrganizationRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class OrganizationPrivilege(str, Enum):
    MEMBER_MANAGE = "org:member:manage"
    SETTINGS_EDIT = "org:settings:edit"


ORG_ROLE_PRIVILEGES: dict = {
    OrganizationRole.OWNER: frozenset({
        OrganizationPrivilege.MEMBER_MANAGE,
        OrganizationPrivilege.SETTINGS_EDIT,
    }),
    OrganizationRole.ADMIN: frozenset({
        OrganizationPrivilege.MEMBER_MANAGE,
    }),
    OrganizationRole.MEMBER: frozenset(),
}


# ---------------------------------------------------------------------------
# Signup account types
# ---------------------------------------------------------------------------
class AccountType(str, Enum):
    """The five account choices presented at signup.

    The first four map 1:1 to a UserRole. The fifth ('organization') is
    a tenant creation flow: it creates a User with an ERP_USER application
    role, creates an Organization, and creates an OrganizationMembership
    with role OWNER. It does NOT persist 'organization' as a UserRole.
    """
    ERP_USER = "erp_user"
    FUNCTIONAL_CONSULTANT = "functional_consultant"
    DEVELOPER = "developer"
    MARKETER = "marketer"
    ORGANIZATION = "organization"

    @property
    def is_individual(self) -> bool:
        return self is not AccountType.ORGANIZATION

    def to_user_role(self) -> UserRole:
        if not self.is_individual:
            raise ValueError(
                "AccountType.ORGANIZATION does not map to a UserRole; "
                "handle it via the organization creation flow."
            )
        return UserRole(self.value)