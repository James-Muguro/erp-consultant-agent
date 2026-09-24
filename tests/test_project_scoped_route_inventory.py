"""
Route-inventory regression test for project-scoped endpoint
authorization.

Purpose
-------
Guarantee that every project-scoped route is protected by BOTH layers
of authorization:

  1. An application-level permission guard, `require_permission(...)`,
     with the expected `Permission` for that route.
  2. A tenant/ownership check, `_get_owned_session(...)`, invoked in the
     endpoint body (or an equivalent explicit tenant check where
     `_get_owned_session` is not applicable).

If a future change silently drops either guard from a project-scoped
route, this file fails at that specific route's parametrized test case,
rather than leaving a gap that only shows up under adversarial input.

Design
------
This file does NOT exercise runtime behavior; no HTTP requests are
issued and no database is touched. It introspects the FastAPI
application's registered routes and inspects:

  * the route's dependency tree (via `APIRoute.dependant`) to confirm a
    `require_permission(Permission.X)` guard is present and to extract
    the required permission from the guard's closure;
  * the endpoint function's code object (`__code__.co_names`) to
    confirm `_get_owned_session` is referenced in the body.

Both checks are stable across refactors that preserve the semantics and
do not depend on source whitespace, line numbers, or textual
formatting. The `co_names` check operates on the code object produced
by the Python compiler, so a rename of `_get_owned_session` deliberately
breaks the test, prompting a documented inventory update.

Category coverage
-----------------
Project-scoped routes fall into three categories:

  1. Path-parameterized (`/api/projects/{session_id}/...`): must have
     a permission guard and must call `_get_owned_session`.

  2. Project-collection (`GET /api/projects`, `POST
     /api/projects/start`): must have a permission guard. Tenant
     handling differs and is documented by dedicated tests.

  3. Session-carrying without path parameter (`POST /api/chat`,
     `POST /api/chat/stream`, `POST /api/feedback`): must have a
     permission guard and must call `_get_owned_session` when the
     optional `session_id` body field is supplied.

Excluded routes (documented by a dedicated test)
-----------------------------------------------
  * `/api/auth/*` — not project-scoped. `PATCH /api/auth/settings` and
    `POST /api/auth/profile-picture` operate on the caller's own user
    and remain on `get_current_user`; `PROFILE_EDIT` enforcement is
    deferred to the account/profile round.
  * `/health`, `/ready` — infrastructure probes.
  * `/metrics` — authenticated but not permission-guarded and not
    project-scoped.
  * `/{full_path:path}` — SPA catch-all.

No production code, migration, existing test, fixture, or configuration
is modified by this file.
"""
from __future__ import annotations

import inspect
from typing import Iterable, Optional, Set, Tuple

import pytest
from fastapi.routing import APIRoute

from src.auth.permissions import Permission
from src.orchestrator_api import app


# Mark every test in this module as a unit test.
pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Inventory: path-parameterized project routes
# ---------------------------------------------------------------------------
# Each entry:
#   (HTTP method, path, expected permission, requires _get_owned_session)
#
# `requires_tenant_check` is always True in this table. Routes whose
# tenancy is handled by a different mechanism live in the
# PROJECT_COLLECTION_ROUTES or CONDITIONAL_TENANT_ROUTES tables.
PROJECT_SCOPED_ROUTES: Tuple[Tuple[str, str, Permission, bool], ...] = (
    # -- Project lifecycle ------------------------------------------------
    ("PATCH", "/api/projects/{session_id}", Permission.PROJECT_EDIT, True),
    ("DELETE", "/api/projects/{session_id}", Permission.PROJECT_EDIT, True),
    ("DELETE", "/api/projects/{session_id}/permanent", Permission.PROJECT_DELETE, True),
    ("GET", "/api/projects/{session_id}/status", Permission.PROJECT_READ, True),

    # -- Requirements -----------------------------------------------------
    ("GET", "/api/projects/{session_id}/requirements", Permission.REQUIREMENTS_READ, True),
    ("POST", "/api/projects/{session_id}/requirements/{requirement_id}/revise", Permission.REQUIREMENTS_REVISE, True),
    ("GET", "/api/projects/{session_id}/requirements/{lineage_id}/history", Permission.REQUIREMENTS_READ, True),

    # -- Review / issues / health / consistency ---------------------------
    ("POST", "/api/projects/{session_id}/review", Permission.REVIEWS_SUBMIT, True),
    ("GET", "/api/projects/{session_id}/issues", Permission.ISSUES_READ, True),
    ("GET", "/api/projects/{session_id}/health", Permission.HEALTH_READ, True),
    ("POST", "/api/projects/{session_id}/consistency-check", Permission.CONSISTENCY_RUN, True),
    ("GET", "/api/projects/{session_id}/coverage-gaps", Permission.HEALTH_READ, True),

    # -- Phase execution --------------------------------------------------
    ("POST", "/api/projects/{session_id}/phase/{phase_name}/execute", Permission.PHASE_EXECUTE, True),

    # -- Documents / messages ---------------------------------------------
    ("GET", "/api/projects/{session_id}/documents", Permission.DOCUMENTS_READ, True),
    ("GET", "/api/projects/{session_id}/documents/{filename}", Permission.DOCUMENTS_READ, True),
    ("POST", "/api/projects/{session_id}/report", Permission.DOCUMENTS_GENERATE, True),
    ("GET", "/api/projects/{session_id}/messages", Permission.PROJECT_READ, True),

    # -- Uploads ----------------------------------------------------------
    ("POST", "/api/projects/{session_id}/uploads", Permission.UPLOADS_WRITE, True),
    ("GET", "/api/projects/{session_id}/uploads", Permission.UPLOADS_READ, True),
    ("GET", "/api/projects/{session_id}/uploads/{document_id}/download", Permission.UPLOADS_READ, True),
    ("DELETE", "/api/projects/{session_id}/uploads/{document_id}", Permission.UPLOADS_WRITE, True),

    # -- Process steps ----------------------------------------------------
    ("GET", "/api/projects/{session_id}/process-steps", Permission.PROCESS_STEPS_READ, True),
    ("POST", "/api/projects/{session_id}/process-steps/{step_id}/revise", Permission.PROCESS_STEPS_REVISE, True),
    ("GET", "/api/projects/{session_id}/process-steps/{lineage_id}/history", Permission.PROCESS_STEPS_READ, True),

    # -- Solution decisions -----------------------------------------------
    ("GET", "/api/projects/{session_id}/solution-decisions", Permission.SOLUTION_READ, True),
    ("POST", "/api/projects/{session_id}/solution-decisions/{decision_id}/actual", Permission.SOLUTION_RECORD_ACTUAL, True),
    ("GET", "/api/projects/{session_id}/solution-decisions/{lineage_id}/history", Permission.SOLUTION_READ, True),

    # -- Test cases / failures --------------------------------------------
    ("GET", "/api/projects/{session_id}/test-cases", Permission.TESTING_READ, True),
    ("POST", "/api/projects/{session_id}/test-cases/{test_case_id}/mark-retested", Permission.TESTING_WRITE, True),
    ("POST", "/api/projects/{session_id}/test-cases/{test_case_id}/report-failure", Permission.TESTING_WRITE, True),
    ("GET", "/api/projects/{session_id}/test-failures", Permission.TESTING_READ, True),

    # -- Training ---------------------------------------------------------
    ("GET", "/api/projects/{session_id}/training-steps", Permission.TRAINING_READ, True),

    # -- Baselines --------------------------------------------------------
    ("POST", "/api/projects/{session_id}/baselines", Permission.BASELINES_CREATE, True),
    ("GET", "/api/projects/{session_id}/baselines", Permission.PROJECT_READ, True),
    ("GET", "/api/projects/{session_id}/baselines/active", Permission.PROJECT_READ, True),
)


# ---------------------------------------------------------------------------
# Inventory: project-collection routes (no {session_id} in path)
# ---------------------------------------------------------------------------
# These are project-scoped in the sense of operating on the collection of
# projects the caller can access, or creating a project. Tenant handling
# is different from the standard `_get_owned_session` pattern and is
# documented by dedicated tests below.
PROJECT_COLLECTION_ROUTES: Tuple[Tuple[str, str, Permission], ...] = (
    # Tenant-aware listing: the underlying service method unions the
    # caller's personal projects with the projects of every organization
    # the caller belongs to. There is no per-session ownership check
    # because there is no session id.
    ("GET", "/api/projects", Permission.PROJECT_READ),

    # Project creation. For organization-owned projects, the route
    # performs an inline `get_membership` check on the supplied
    # organization_id before calling the orchestrator.
    ("POST", "/api/projects/start", Permission.PROJECT_CREATE),
)


# ---------------------------------------------------------------------------
# Inventory: session-carrying routes without {session_id} in path
# ---------------------------------------------------------------------------
# These accept an optional `session_id` in the request body. The tenant
# boundary is conditional: enforced when `session_id` is present.
CONDITIONAL_TENANT_ROUTES: Tuple[Tuple[str, str, Permission], ...] = (
    ("POST", "/api/chat", Permission.CHAT_SUBMIT),
    ("POST", "/api/chat/stream", Permission.CHAT_SUBMIT),
    ("POST", "/api/feedback", Permission.FEEDBACK_SUBMIT),
)


# ---------------------------------------------------------------------------
# Exclusion documentation
# ---------------------------------------------------------------------------
# These routes exist in the application but are not part of the
# project-scoped inventory. Documented here so the exclusion is a
# deliberate, reviewable decision rather than an omission.
EXCLUDED_ROUTES: Set[Tuple[str, str]] = {
    ("POST", "/api/auth/signup"),
    ("POST", "/api/auth/login"),
    ("GET", "/api/auth/me"),
    ("GET", "/api/auth/settings"),
    ("PATCH", "/api/auth/settings"),
    ("POST", "/api/auth/profile-picture"),
    ("GET", "/api/auth/profile-picture/{filename}"),
    ("POST", "/api/auth/password"),
    ("DELETE", "/api/auth/account"),
    ("GET", "/health"),
    ("GET", "/ready"),
    ("GET", "/metrics"),
}


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------
def _all_api_routes() -> Iterable[APIRoute]:
    for r in app.routes:
        if isinstance(r, APIRoute):
            yield r


def _find_route(method: str, path: str) -> Optional[APIRoute]:
    for r in _all_api_routes():
        if r.path == path and method in r.methods:
            return r
    return None


def _unwrapped_endpoint(route: APIRoute):
    """Return the innermost function behind any slowapi or middleware
    wrapper. `require_permission`, `limiter.limit`, and `functools.wraps`
    all participate in the wrapper chain; `inspect.unwrap` collapses
    that chain by following `__wrapped__` links. For an unwrapped
    function this returns the function itself."""
    try:
        return inspect.unwrap(route.endpoint)
    except Exception:  # noqa: BLE001
        return route.endpoint


def _find_required_permission(route: APIRoute) -> Optional[Permission]:
    """Walk the route's dependency tree and return the `Permission`
    captured by a `require_permission(...)` guard, or None if no such
    guard is present.

    `require_permission(Permission.X)` returns a closure. FastAPI stores
    that closure as a `Dependant.call`. The closure's `__qualname__`
    begins with `require_permission.<locals>.dep`. The captured
    `Permission` value lives in the closure's cells, and is extracted
    by iterating the cells and returning the first `Permission` found.
    """
    def walk(dependant) -> Optional[Permission]:
        for sub in getattr(dependant, "dependencies", ()) or ():
            call = getattr(sub, "call", None)
            if call is not None:
                qualname = getattr(call, "__qualname__", "")
                if qualname.startswith("require_permission."):
                    closure = getattr(call, "__closure__", None) or ()
                    for cell in closure:
                        try:
                            val = cell.cell_contents
                        except ValueError:
                            continue
                        if isinstance(val, Permission):
                            return val
            found = walk(sub)
            if found is not None:
                return found
        return None

    return walk(route.dependant)


def _endpoint_references_name(route: APIRoute, name: str) -> bool:
    """True if the endpoint function's code object references `name` as
    a global lookup. A function that calls `name()` compiles to a
    `LOAD_GLOBAL name` instruction, which puts `name` into
    `co_names`. This check is stable across source formatting changes
    and independent of line numbers."""
    endpoint = _unwrapped_endpoint(route)
    code = getattr(endpoint, "__code__", None)
    if code is None:
        return False
    return name in code.co_names


# ---------------------------------------------------------------------------
# 1. Path-parameterized project routes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "method,path,expected_permission,requires_tenant",
    PROJECT_SCOPED_ROUTES,
    ids=[f"{m} {p}" for m, p, _, _ in PROJECT_SCOPED_ROUTES],
)
def test_project_scoped_route_has_permission_and_tenant_guard(
    method: str,
    path: str,
    expected_permission: Permission,
    requires_tenant: bool,
):
    route = _find_route(method, path)
    assert route is not None, (
        f"route {method} {path} is not registered in the FastAPI app; "
        f"either the inventory entry is stale or the route was removed "
        f"without updating this file"
    )

    actual_permission = _find_required_permission(route)
    assert actual_permission == expected_permission, (
        f"{method} {path} must be guarded by "
        f"`require_permission({expected_permission.value!r})`, but the "
        f"route's dependency tree "
        f"{'has no require_permission guard' if actual_permission is None else f'requires {actual_permission.value!r} instead'}"
    )

    if requires_tenant:
        assert _endpoint_references_name(route, "_get_owned_session"), (
            f"{method} {path} must call `_get_owned_session` in its "
            f"endpoint body to enforce the tenant boundary, but the "
            f"endpoint's code object does not reference that name"
        )


# ---------------------------------------------------------------------------
# 2. Project-collection routes (no {session_id} in path)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "method,path,expected_permission",
    PROJECT_COLLECTION_ROUTES,
    ids=[f"{m} {p}" for m, p, _ in PROJECT_COLLECTION_ROUTES],
)
def test_project_collection_route_has_permission_guard(
    method: str,
    path: str,
    expected_permission: Permission,
):
    route = _find_route(method, path)
    assert route is not None, f"route {method} {path} is not registered"

    actual_permission = _find_required_permission(route)
    assert actual_permission == expected_permission, (
        f"{method} {path} must be guarded by "
        f"`require_permission({expected_permission.value!r})`, but the "
        f"route's dependency tree "
        f"{'has no require_permission guard' if actual_permission is None else f'requires {actual_permission.value!r} instead'}"
    )


def test_get_projects_uses_tenant_aware_listing():
    """`GET /api/projects` must use the tenant-aware listing method
    `list_project_summaries_for_user`, which unions the caller's
    personal projects with the projects of every organization the
    caller belongs to. This is the discoverability half of the Round 3a
    tenant correction; it must not be replaced by a plain
    `user_id`-filtered listing."""
    route = _find_route("GET", "/api/projects")
    assert route is not None
    assert _endpoint_references_name(route, "list_project_summaries_for_user"), (
        "GET /api/projects must call the tenant-aware listing method "
        "`list_project_summaries_for_user`; the endpoint's code object "
        "does not reference that name"
    )


def test_post_projects_start_enforces_organization_membership():
    """`POST /api/projects/start` must perform an inline
    `get_membership` check when `organization_id` is supplied, so a
    caller cannot create an organization-owned project in an
    organization they do not belong to."""
    route = _find_route("POST", "/api/projects/start")
    assert route is not None
    assert _endpoint_references_name(route, "get_membership"), (
        "POST /api/projects/start must call `get_membership` to enforce "
        "the organization boundary for organization-owned project "
        "creation; the endpoint's code object does not reference that "
        "name"
    )


# ---------------------------------------------------------------------------
# 3. Session-carrying routes without {session_id} in path
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "method,path,expected_permission",
    CONDITIONAL_TENANT_ROUTES,
    ids=[f"{m} {p}" for m, p, _ in CONDITIONAL_TENANT_ROUTES],
)
def test_conditional_tenant_route_has_permission_and_tenant_check(
    method: str,
    path: str,
    expected_permission: Permission,
):
    """`/api/chat`, `/api/chat/stream`, and `/api/feedback` accept an
    optional `session_id` in the body. They must be permission-guarded
    on the outer route and must call `_get_owned_session` in the body
    (conditionally, when the field is present).

    Because the tenant check is conditional, this test asserts the
    reference to `_get_owned_session` is present in the endpoint's
    code object. A change that would remove the boundary entirely
    (dropping the helper call) fails here; a change that alters the
    condition does not, because that is a behavioral decision better
    covered by the integration tests in
    tests/test_permissions_routes.py."""
    route = _find_route(method, path)
    assert route is not None, f"route {method} {path} is not registered"

    actual_permission = _find_required_permission(route)
    assert actual_permission == expected_permission, (
        f"{method} {path} must be guarded by "
        f"`require_permission({expected_permission.value!r})`, but the "
        f"route's dependency tree "
        f"{'has no require_permission guard' if actual_permission is None else f'requires {actual_permission.value!r} instead'}"
    )

    assert _endpoint_references_name(route, "_get_owned_session"), (
        f"{method} {path} must call `_get_owned_session` when a "
        f"session_id is supplied; the endpoint's code object does not "
        f"reference that name"
    )


# ---------------------------------------------------------------------------
# 4. Completeness
# ---------------------------------------------------------------------------
def test_every_path_parameterized_project_route_is_inventoried():
    """Every registered route whose path contains `{session_id}` must
    appear in `PROJECT_SCOPED_ROUTES`. A future route added without an
    inventory entry fails this test, prompting an explicit
    authorization declaration rather than letting the route slip in
    without one.

    The check is two-directional: a registered route missing from the
    inventory is an unreviewed addition; an inventory entry with no
    corresponding route is a stale entry (either the route was removed
    without updating the file, or an entry was added by mistake)."""
    inventoried: Set[Tuple[str, str]] = {
        (m, p) for m, p, _, _ in PROJECT_SCOPED_ROUTES
    }

    registered: Set[Tuple[str, str]] = set()
    for r in _all_api_routes():
        if "{session_id}" not in r.path:
            continue
        for method in r.methods:
            # FastAPI auto-adds HEAD for GET and OPTIONS for preflight;
            # those are not distinct authorization units and are
            # intentionally not inventoried.
            if method in {"HEAD", "OPTIONS"}:
                continue
            registered.add((method, r.path))

    missing = registered - inventoried
    assert not missing, (
        "The following registered project-scoped routes are not in "
        "PROJECT_SCOPED_ROUTES. Add each with its expected permission "
        f"and tenant-check flag: {sorted(missing)}"
    )

    extra = inventoried - registered
    assert not extra, (
        "The following entries in PROJECT_SCOPED_ROUTES do not "
        "correspond to any registered route. Either a route was removed "
        "without updating the inventory, or an entry was added by "
        f"mistake: {sorted(extra)}"
    )


# ---------------------------------------------------------------------------
# 5. Exclusion documentation
# ---------------------------------------------------------------------------
def test_inventory_does_not_include_non_project_scoped_routes():
    """Documentation check: the excluded routes are exactly those that
    are known not to be project-scoped. This test makes the exclusion
    an explicit, reviewable decision in code rather than a silent
    omission."""
    inventoried_paths: Set[str] = (
        {p for _, p, _, _ in PROJECT_SCOPED_ROUTES}
        | {p for _, p, _ in PROJECT_COLLECTION_ROUTES}
        | {p for _, p, _ in CONDITIONAL_TENANT_ROUTES}
    )
    excluded_paths = {p for _, p in EXCLUDED_ROUTES}

    overlap = inventoried_paths & excluded_paths
    assert not overlap, (
        "The following paths appear both in the project-scoped "
        f"inventory and in the exclusion list: {sorted(overlap)}"
    )

    # Every excluded path is registered — otherwise the exclusion list
    # is stale.
    registered_paths: Set[str] = {r.path for r in _all_api_routes()}
    stale = excluded_paths - registered_paths
    assert not stale, (
        "The following paths are in the exclusion list but are not "
        f"registered routes: {sorted(stale)}"
    )