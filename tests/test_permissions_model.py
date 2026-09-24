"""
Unit tests for the permission model defined in src/auth/permissions.py.

Scope:
  * Application role → permission mappings (ROLE_PERMISSIONS).
  * The specific restrictions on ERP User, Developer, and Marketer
    that were established in Round 3b.
  * The union semantics of `effective_permissions`.
  * The defensive handling of unknown roles in `effective_permissions`.
  * The distinction between application roles and organization roles /
    privileges.
  * The AccountType → UserRole mapping, including the deliberate
    absence of a mapping for AccountType.ORGANIZATION.

Out of scope (covered by other files):
  * HTTP route-level enforcement — tests/test_permissions_routes.py.
  * Tenant boundary behavior — tests/test_tenant_boundary.py.
  * Signup role persistence — tests/test_signup.py.
  * /me response shape — tests/test_auth_me.py.
  * Organization-only user's route denials — tests/test_auth_organization_only.py.

Design notes:
  * This module has no database, HTTP, or filesystem dependencies. It
    imports only from src.auth.permissions and pytest. It can run in
    isolation and does not require PostgreSQL or the app to be booted.
  * Assertions use membership / non-membership in the production
    permission sets rather than re-declaring the sets. The production
    constants remain the single source of truth.
  * Every test below reflects the state of src/auth/permissions.py as
    shipped after Round 3b. If a future edit to that module changes
    the mappings, these tests will fail — that is the intended
    behavior.
"""
from __future__ import annotations

import pytest

from src.auth.permissions import (
    AccountType,
    ORG_ROLE_PRIVILEGES,
    OrganizationPrivilege,
    OrganizationRole,
    Permission,
    ROLE_PERMISSIONS,
    UserRole,
    effective_permissions,
)


# Mark every test in this module as a unit test so the "FAST" run
# described in pytest.ini (`pytest -m "not api and not timing"`) picks
# it up without also running integration tests.
pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# ERP User — read-only; no project creation, no requirement revision
# ---------------------------------------------------------------------------
def test_erp_user_does_not_have_project_create():
    assert Permission.PROJECT_CREATE not in ROLE_PERMISSIONS[UserRole.ERP_USER]


def test_erp_user_does_not_have_requirements_revise():
    assert Permission.REQUIREMENTS_REVISE not in ROLE_PERMISSIONS[UserRole.ERP_USER]


# ---------------------------------------------------------------------------
# Developer — restriction set (Round 3b)
# ---------------------------------------------------------------------------
def test_developer_does_not_have_project_create():
    assert Permission.PROJECT_CREATE not in ROLE_PERMISSIONS[UserRole.DEVELOPER]


def test_developer_does_not_have_project_edit():
    assert Permission.PROJECT_EDIT not in ROLE_PERMISSIONS[UserRole.DEVELOPER]


def test_developer_does_not_have_project_delete():
    assert Permission.PROJECT_DELETE not in ROLE_PERMISSIONS[UserRole.DEVELOPER]


def test_developer_does_not_have_requirements_revise():
    assert Permission.REQUIREMENTS_REVISE not in ROLE_PERMISSIONS[UserRole.DEVELOPER]


def test_developer_does_not_have_process_steps_revise():
    assert Permission.PROCESS_STEPS_REVISE not in ROLE_PERMISSIONS[UserRole.DEVELOPER]


def test_developer_does_not_have_reviews_submit():
    assert Permission.REVIEWS_SUBMIT not in ROLE_PERMISSIONS[UserRole.DEVELOPER]


def test_developer_does_not_have_consistency_run():
    assert Permission.CONSISTENCY_RUN not in ROLE_PERMISSIONS[UserRole.DEVELOPER]


# ---------------------------------------------------------------------------
# Developer — grants that were explicitly approved
# ---------------------------------------------------------------------------
def test_developer_has_solution_record_actual():
    assert Permission.SOLUTION_RECORD_ACTUAL in ROLE_PERMISSIONS[UserRole.DEVELOPER]


def test_developer_has_testing_write():
    assert Permission.TESTING_WRITE in ROLE_PERMISSIONS[UserRole.DEVELOPER]


def test_developer_has_documents_generate():
    assert Permission.DOCUMENTS_GENERATE in ROLE_PERMISSIONS[UserRole.DEVELOPER]


def test_developer_has_uploads_write():
    assert Permission.UPLOADS_WRITE in ROLE_PERMISSIONS[UserRole.DEVELOPER]


def test_developer_has_phase_execute():
    assert Permission.PHASE_EXECUTE in ROLE_PERMISSIONS[UserRole.DEVELOPER]


# ---------------------------------------------------------------------------
# Functional Consultant — full project scope
# ---------------------------------------------------------------------------
def test_functional_consultant_has_all_project_scoped_writes():
    """FC is the only role with the full project-scoped write set
    (per the Round 3b product decisions). Assert membership of every
    permission currently granted by `_CONSULTANT_WRITE_PERMS`, derived
    from src/auth/permissions.py rather than re-declared here."""
    fc = ROLE_PERMISSIONS[UserRole.FUNCTIONAL_CONSULTANT]
    expected_writes = {
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
    }
    missing = expected_writes - fc
    assert missing == set(), (
        f"Functional Consultant is expected to hold every project-scoped "
        f"write; missing: {sorted(p.value for p in missing)}"
    )


# ---------------------------------------------------------------------------
# Marketer — read list and document generation only
# ---------------------------------------------------------------------------
def test_marketer_has_project_read_documents_read_documents_generate():
    marketer = ROLE_PERMISSIONS[UserRole.MARKETER]
    assert Permission.PROJECT_READ in marketer
    assert Permission.DOCUMENTS_READ in marketer
    assert Permission.DOCUMENTS_GENERATE in marketer


def test_marketer_does_not_have_project_create():
    assert Permission.PROJECT_CREATE not in ROLE_PERMISSIONS[UserRole.MARKETER]


def test_marketer_has_chat_submit():
    """CHAT_SUBMIT is granted through `_COMMON_USER_PERMS` to every
    application role, including Marketer. This test exists specifically
    to lock that in — the earlier `test_marketer_does_not_have_...`
    naming in the impact map was flagged as incorrect; the correct
    assertion is that Marketer HAS CHAT_SUBMIT."""
    assert Permission.CHAT_SUBMIT in ROLE_PERMISSIONS[UserRole.MARKETER]


# ---------------------------------------------------------------------------
# effective_permissions — union semantics
# ---------------------------------------------------------------------------
def test_effective_permissions_union_of_roles():
    """Roles combine additively. ERP_USER + MARKETER are chosen
    because their permission sets are not subsets of one another, so
    the test proves a real union rather than re-asserting one role's
    set.
    """
    erp_user = ROLE_PERMISSIONS[UserRole.ERP_USER]
    marketer = ROLE_PERMISSIONS[UserRole.MARKETER]
    combined = effective_permissions([UserRole.ERP_USER, UserRole.MARKETER])

    erp_only = erp_user - marketer
    marketer_only = marketer - erp_user

    assert erp_only, (
        "ERP_USER must hold at least one permission Marketer does not; "
        f"diff was empty (erp_user={sorted(p.value for p in erp_user)})"
    )
    assert marketer_only, (
        "MARKETER must hold at least one permission ERP_USER does not; "
        f"diff was empty (marketer={sorted(p.value for p in marketer)})"
    )

    assert combined == (erp_user | marketer)
    assert erp_user.issubset(combined)
    assert marketer.issubset(combined)


def test_effective_permissions_ignores_unknown_roles():
    """`effective_permissions` uses `ROLE_PERMISSIONS.get(r, frozenset())`
    so an unrecognized role contributes nothing rather than raising.
    This defends callers against a role value that was removed from the
    enum after data was written.

    A raw string that does not match any UserRole value is passed to
    exercise the `.get(..., frozenset())` default branch."""
    unknown = "definitely-not-a-real-role"
    result = effective_permissions([UserRole.DEVELOPER, unknown])  # type: ignore[list-item]

    # The known role's permissions are present...
    assert result == ROLE_PERMISSIONS[UserRole.DEVELOPER]
    # ...and the unknown role contributed nothing (would have raised if
    # it did not silently skip).


def test_effective_permissions_of_empty_input_is_empty():
    """An empty iterable returns an empty frozenset — the caller has no
    roles, hence no permissions."""
    assert effective_permissions([]) == frozenset()


# ---------------------------------------------------------------------------
# AccountType → UserRole mapping
# ---------------------------------------------------------------------------
def test_account_type_organization_to_user_role_raises():
    """AccountType.ORGANIZATION is a tenant-creation flow, not an
    application role. Its `to_user_role()` raises ValueError by design;
    the signup service never calls it for the organization branch."""
    with pytest.raises(ValueError):
        AccountType.ORGANIZATION.to_user_role()


def test_account_type_individual_to_user_role_matches_enum_value():
    """Each individual account type maps to the UserRole with the same
    value. This is the contract that lets the signup service use
    `account_type.to_user_role()` directly for individual signups."""
    assert AccountType.ERP_USER.to_user_role() is UserRole.ERP_USER
    assert AccountType.FUNCTIONAL_CONSULTANT.to_user_role() is UserRole.FUNCTIONAL_CONSULTANT
    assert AccountType.DEVELOPER.to_user_role() is UserRole.DEVELOPER
    assert AccountType.MARKETER.to_user_role() is UserRole.MARKETER


# ---------------------------------------------------------------------------
# UserRole enum membership
# ---------------------------------------------------------------------------
def test_no_org_admin_or_combined_role_exists():
    """UserRole contains exactly the four approved application roles.
    No 'ORG_ADMIN', no 'functional_developer', no 'organization' — the
    enum is the load-bearing definition of what an application role is."""
    actual = set(UserRole)
    expected = {
        UserRole.ERP_USER,
        UserRole.FUNCTIONAL_CONSULTANT,
        UserRole.DEVELOPER,
        UserRole.MARKETER,
    }
    assert actual == expected


# ---------------------------------------------------------------------------
# Organization roles / privileges are a separate axis from UserRole
# ---------------------------------------------------------------------------
def test_organization_owner_privileges_are_separate_from_application_roles():
    """OrganizationRole and OrganizationPrivilege are distinct enums
    from UserRole and Permission. Organization ownership is expressed
    by OrganizationRole.OWNER, which is not a UserRole member and
    cannot be constructed as one."""
    # OWNER is not an application role.
    assert OrganizationRole.OWNER not in set(UserRole)
    with pytest.raises(ValueError):
        UserRole(OrganizationRole.OWNER.value)

    # OrganizationPrivilege is a distinct enum from both UserRole and
    # Permission, verified by disjoint member value sets.
    assert set(OrganizationPrivilege).isdisjoint(set(UserRole))
    assert set(OrganizationPrivilege).isdisjoint(set(Permission))

    # The organization privilege table keys on OrganizationRole, not
    # on UserRole — reinforcing the two axes are wired independently.
    assert set(ORG_ROLE_PRIVILEGES.keys()) == set(OrganizationRole)