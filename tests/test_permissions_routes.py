"""
HTTP-level permission enforcement tests.

Purpose: verify that `require_permission` is actually wired into the
route dependency chain and produces the expected 401 / 403 / 404
response for each category of caller.

Response-code contract exercised by this file:
  * 401 — unauthenticated (no token). Not the focus here; the
    existing suite already covers it.
  * 403 — authenticated and correctly resolved to a user, but the
    user holds no application role that grants the route's
    required permission. Produced by `require_permission`.
  * 404 — authenticated and permitted, but the session is outside
    the caller's tenant/owner boundary. Produced by
    `_get_owned_session` for both personal and organization-owned
    sessions.

Test-design notes:

  * Every test uses explicit `account_type` values on signup so the
    application role under test is deterministic.

  * Where the caller needs the application permission to reach the
    tenant check (permission-granted paths), the caller owns a
    personal project created via the direct `agent_memory.create_project`
    call. That call writes the SessionRecord and seeds memory without
    going through HTTP or requiring any permission, matching the
    direct-seeding pattern used in tests/test_cascading_deletes.py and
    tests/test_orchestrator.py.

  * Where the caller does not have the permission (denial tests), the
    `require_permission` guard fires before the tenant check, so the
    session id does not need to exist. Those tests use a sentinel
    `session_id` to make that explicit.

  * Where the caller has the permission but is outside the tenant
    (tenant-boundary-after-permission tests), the caller owns their own
    project but targets a foreign session.

  * Chat tests that expect 404 use the guard-before-body order: the
    route calls `_get_owned_session` before touching the LLM, so the
    LLM does not need to be mocked for those tests. Chat tests that
    expect 200 mock `get_llm` and `info_retriever` following the
    pattern in tests/test_orchestrator_api.py.

  * Upload tests use the moto mock_aws pattern from
    tests/test_project_uploads_api.py.

  * Phase-execution tests use the `patch.dict('src.orchestrator_api.
    _PHASE_EXECUTORS', ...)` pattern from tests/test_orchestrator_api.py.

  * No production code, migration, existing test, fixture,
    configuration, or frontend file is modified.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Iterator, List
from unittest.mock import MagicMock, patch

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.db.base import SessionLocal
from src.db.models import (
    Organization,
    OrganizationMembership,
    SessionRecord,
    User,
    UserRoleRecord,
)
from src.memory import agent_memory
from src.orchestrator_api import app, doc_generator
from src.services import project_intelligence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# A sentinel session id for tests whose caller lacks the route's
# permission. The `require_permission` dependency rejects the request
# before any lookup of this id, so the value is deliberately one that
# would never exist.
_FAKE_SESSION_ID = "prj_nonexistent_permission_test"


@contextmanager
def _db_session() -> Iterator[Session]:
    """Session lifecycle helper, matching the pattern used in
    tests/test_consistency_check_api.py and tests/test_tenant_boundary.py."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _unique_email(prefix: str = "perm-test") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def _signup(
    client: TestClient,
    email: str,
    account_type: str = "functional_consultant",
) -> str:
    """Sign up with an explicit account type and return the access token."""
    r = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "testpassword123",
            "account_type": account_type,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _user_id_for_email(email: str) -> str:
    with _db_session() as db:
        uid = db.query(User.id).filter(User.email == email.lower()).scalar()
    assert uid is not None, f"no user row for {email!r}"
    return uid


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _own_project(user_id: str, name: str = "Owned Project") -> str:
    """Create a personal project owned by `user_id` without going
    through HTTP. This bypasses permission checks, which is exactly
    what is needed to give a restricted caller (Developer, Marketer,
    etc.) a session they legitimately own at the tenant level so a
    subsequent 403 can be attributed to the missing permission rather
    than to a failed tenant check.
    """
    return agent_memory.create_project(
        project_name=name,
        module="FI",
        user_id=user_id,
    )


def _grant_role(user_id: str, role_value: str) -> None:
    """Directly insert a UserRoleRecord. Used to construct multi-role
    users where no endpoint exists to grant a second role."""
    with _db_session() as db:
        db.add(UserRoleRecord(
            id=uuid.uuid4().hex,
            user_id=user_id,
            role=role_value,
        ))
        db.commit()


def _insert_org_with_owner(owner_user_id: str, name: str) -> str:
    """Insert an Organization and its owner membership. Returns the
    organization id. Mirrors the helper in tests/test_tenant_boundary.py."""
    org_id = uuid.uuid4().hex
    with _db_session() as db:
        db.add(Organization(id=org_id, name=name, created_by=owner_user_id))
        db.add(OrganizationMembership(
            id=uuid.uuid4().hex,
            organization_id=org_id,
            user_id=owner_user_id,
            role="owner",
        ))
        db.commit()
    return org_id


def _seed_solution_decision(session_id: str) -> str:
    """Insert one SolutionDecision for the given session. Returns its id."""
    created = project_intelligence.sync_solution_decisions_from_structured(
        session_id,
        {"configurations": [{"component": "Test", "description": "Test decision"}]},
    )
    assert created, "expected sync_solution_decisions_from_structured to create a row"
    return created[0]


def _seed_test_case(session_id: str) -> str:
    """Insert one TestCaseRecord for the given session. Returns its id."""
    created = project_intelligence.sync_test_cases_from_structured(
        session_id, "QA", [{"id": "TC-001", "scenario": "Test"}],
    )
    assert created, "expected sync_test_cases_from_structured to create a row"
    return created[0]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    """TestClient entered as a context manager so the lifespan runs."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class _Registry:
    def __init__(self):
        self.emails: List[str] = []
        self.org_ids: List[str] = []


@pytest.fixture
def reg():
    """Track users and directly-inserted organizations for cleanup.

    Session rows are cleaned up after the fact by querying for rows
    owned by the tracked users, so tests do not need to register each
    session id explicitly.
    """
    r = _Registry()
    yield r
    lowered = [e.lower() for e in r.emails]

    # Phase 1: ask the session service to delete any sessions it has
    # cached for the tracked users. This keeps the in-memory cache
    # consistent with the DB.
    with _db_session() as db:
        user_rows = db.query(User).filter(User.email.in_(lowered)).all() if lowered else []
        user_ids = {u.id for u in user_rows}

    for sid, session in list(agent_memory.session_service.sessions.items()):
        if getattr(session, "user_id", None) in user_ids:
            try:
                agent_memory.session_service.delete_session(sid)
            except Exception:  # noqa: BLE001
                pass

    # Phase 2: direct DB cleanup, order chosen to respect FK
    # constraints (sessions.organization_id RESTRICT).
    with _db_session() as db:
        user_rows = db.query(User).filter(User.email.in_(lowered)).all() if lowered else []
        user_ids = [u.id for u in user_rows]

        if user_ids:
            db.query(SessionRecord).filter(
                SessionRecord.user_id.in_(user_ids)
            ).delete(synchronize_session=False)
        if r.org_ids:
            db.query(SessionRecord).filter(
                SessionRecord.organization_id.in_(r.org_ids)
            ).delete(synchronize_session=False)

        if r.org_ids:
            db.query(Organization).filter(
                Organization.id.in_(r.org_ids)
            ).delete(synchronize_session=False)
        if user_ids:
            db.query(Organization).filter(
                Organization.created_by.in_(user_ids)
            ).delete(synchronize_session=False)

        if user_ids:
            db.query(User).filter(
                User.id.in_(user_ids)
            ).delete(synchronize_session=False)

        db.commit()


@pytest.fixture
def s3_configured(monkeypatch):
    """Configure S3 via settings + moto. Mirrors the fixture in
    tests/test_project_uploads_api.py."""
    monkeypatch.setattr(settings, "s3_bucket_name", "test-bucket")
    monkeypatch.setattr(settings, "s3_access_key_id", "fake-key")
    monkeypatch.setattr(settings, "s3_secret_access_key", "fake-secret")
    monkeypatch.setattr(settings, "s3_endpoint_url", None)
    monkeypatch.setattr(settings, "s3_region", "us-east-1")
    with mock_aws():
        boto_client = boto3.client("s3", region_name="us-east-1")
        boto_client.create_bucket(Bucket="test-bucket")
        yield


# ---------------------------------------------------------------------------
# 1. Project creation — POST /api/projects/start (PROJECT_CREATE)
# ---------------------------------------------------------------------------
class TestProjectCreationPermission:
    def test_functional_consultant_can_create_project(self, client, reg):
        email = _unique_email("fc")
        reg.emails.append(email)
        token = _signup(client, email, "functional_consultant")

        r = client.post(
            "/api/projects/start",
            json={"project_name": "FC Project", "module": "FI"},
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True

    def test_developer_cannot_create_project(self, client, reg):
        email = _unique_email("dev")
        reg.emails.append(email)
        token = _signup(client, email, "developer")

        r = client.post(
            "/api/projects/start",
            json={"project_name": "Dev Project", "module": "FI"},
            headers=_headers(token),
        )
        # 403 is produced by the permission guard. The request has no
        # session_id, so there is no tenant lookup that could produce
        # a 404 instead — the 403 unambiguously isolates the missing
        # PROJECT_CREATE permission.
        assert r.status_code == 403, r.text
        assert r.json()["error"]["code"] == 403

    def test_erp_user_cannot_create_project(self, client, reg):
        email = _unique_email("erp")
        reg.emails.append(email)
        token = _signup(client, email, "erp_user")

        r = client.post(
            "/api/projects/start",
            json={"project_name": "ERP Project", "module": "FI"},
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text

    def test_marketer_cannot_create_project(self, client, reg):
        email = _unique_email("mkt")
        reg.emails.append(email)
        token = _signup(client, email, "marketer")

        r = client.post(
            "/api/projects/start",
            json={"project_name": "Mkt Project", "module": "FI"},
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# 2. Project lifecycle — PATCH and DELETE /permanent
# ---------------------------------------------------------------------------
class TestProjectLifecyclePermission:
    def test_developer_cannot_edit_project(self, client, reg):
        email = _unique_email("dev-edit")
        reg.emails.append(email)
        token = _signup(client, email, "developer")
        user_id = _user_id_for_email(email)

        # Developer owns a personal project so the tenant check would
        # pass. The 403 must therefore come from the missing
        # PROJECT_EDIT permission, not from a failed tenant lookup.
        sid = _own_project(user_id, name="Dev Owned")

        r = client.patch(
            f"/api/projects/{sid}",
            json={"project_name": "Renamed"},
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text
        assert r.json()["error"]["code"] == 403

    def test_developer_cannot_delete_project_permanently(self, client, reg):
        email = _unique_email("dev-del")
        reg.emails.append(email)
        token = _signup(client, email, "developer")
        user_id = _user_id_for_email(email)

        sid = _own_project(user_id, name="Dev Owned")

        r = client.delete(
            f"/api/projects/{sid}/permanent",
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text
        assert r.json()["error"]["code"] == 403


# ---------------------------------------------------------------------------
# 3. Requirement and process-step revision
# ---------------------------------------------------------------------------
class TestStructuredArtifactRevisionPermission:
    def test_developer_cannot_revise_requirements(self, client, reg):
        email = _unique_email("dev-reqrev")
        reg.emails.append(email)
        token = _signup(client, email, "developer")
        user_id = _user_id_for_email(email)

        sid = _own_project(user_id)

        r = client.post(
            f"/api/projects/{sid}/requirements/{uuid.uuid4().hex}/revise",
            json={"description": "updated"},
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text

    def test_developer_cannot_revise_process_steps(self, client, reg):
        email = _unique_email("dev-steprev")
        reg.emails.append(email)
        token = _signup(client, email, "developer")
        user_id = _user_id_for_email(email)

        sid = _own_project(user_id)

        r = client.post(
            f"/api/projects/{sid}/process-steps/{uuid.uuid4().hex}/revise",
            json={"name": "updated"},
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# 4. Developer permissions that should succeed
# ---------------------------------------------------------------------------
class TestDeveloperAllowedActions:
    def test_developer_can_record_actual_solution(self, client, reg):
        email = _unique_email("dev-sol")
        reg.emails.append(email)
        token = _signup(client, email, "developer")
        user_id = _user_id_for_email(email)

        sid = _own_project(user_id)
        did = _seed_solution_decision(sid)

        r = client.post(
            f"/api/projects/{sid}/solution-decisions/{did}/actual",
            json={"description": "Implemented as configured"},
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "new_decision_id" in body

    def test_developer_can_mark_test_case_retested(self, client, reg):
        email = _unique_email("dev-tc")
        reg.emails.append(email)
        token = _signup(client, email, "developer")
        user_id = _user_id_for_email(email)

        sid = _own_project(user_id)
        tcid = _seed_test_case(sid)

        r = client.post(
            f"/api/projects/{sid}/test-cases/{tcid}/mark-retested",
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True

    def test_developer_can_generate_project_report(self, client, reg):
        email = _unique_email("dev-report")
        reg.emails.append(email)
        token = _signup(client, email, "developer")
        user_id = _user_id_for_email(email)

        sid = _own_project(user_id)

        with patch.object(
            doc_generator,
            "generate_project_report",
            return_value="/tmp/fake-report.docx",
        ):
            r = client.post(
                f"/api/projects/{sid}/report",
                headers=_headers(token),
            )
        assert r.status_code == 200, r.text
        assert r.json()["filename"] == "fake-report.docx"

    def test_developer_can_upload_project_document(
        self, client, reg, s3_configured,
    ):
        email = _unique_email("dev-upload")
        reg.emails.append(email)
        token = _signup(client, email, "developer")
        user_id = _user_id_for_email(email)

        sid = _own_project(user_id)

        r = client.post(
            f"/api/projects/{sid}/uploads",
            files={"file": ("notes.txt", b"implementation notes", "text/plain")},
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["filename"] == "notes.txt"
        assert body["size_bytes"] == len(b"implementation notes")

    def test_developer_can_execute_phase(self, client, reg):
        email = _unique_email("dev-phase")
        reg.emails.append(email)
        token = _signup(client, email, "developer")
        user_id = _user_id_for_email(email)

        sid = _own_project(user_id)

        # The route looks up `_PHASE_EXECUTORS[phase_name]` after the
        # permission guard passes. patch.dict mutates the module dict
        # in place and restores it on exit; the guard has already
        # succeeded by the time the mock is consulted.
        with patch.dict(
            "src.orchestrator_api._PHASE_EXECUTORS",
            {"qa_testing": MagicMock(return_value={"success": True, "duration": 0.1})},
        ):
            r = client.post(
                f"/api/projects/{sid}/phase/qa_testing/execute",
                json={},
                headers=_headers(token),
            )
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# 5. Review / consistency / baseline restrictions
# ---------------------------------------------------------------------------
class TestDeveloperRestrictedActions:
    def test_developer_cannot_submit_review(self, client, reg):
        email = _unique_email("dev-review")
        reg.emails.append(email)
        token = _signup(client, email, "developer")
        user_id = _user_id_for_email(email)

        sid = _own_project(user_id)

        r = client.post(
            f"/api/projects/{sid}/review",
            json={
                "object_type": "requirement",
                "object_id": uuid.uuid4().hex,
                "action": "approved",
            },
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text

    def test_developer_cannot_run_consistency_check(self, client, reg):
        email = _unique_email("dev-cc")
        reg.emails.append(email)
        token = _signup(client, email, "developer")
        user_id = _user_id_for_email(email)

        sid = _own_project(user_id)

        r = client.post(
            f"/api/projects/{sid}/consistency-check",
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text

    def test_developer_cannot_create_baseline(self, client, reg):
        email = _unique_email("dev-base")
        reg.emails.append(email)
        token = _signup(client, email, "developer")
        user_id = _user_id_for_email(email)

        sid = _own_project(user_id)

        r = client.post(
            f"/api/projects/{sid}/baselines",
            json={"label": "v1"},
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# 6. Marketer permissions
# ---------------------------------------------------------------------------
class TestMarketerPermissions:
    def test_marketer_can_list_projects(self, client, reg):
        email = _unique_email("mkt-list")
        reg.emails.append(email)
        token = _signup(client, email, "marketer")

        r = client.get("/api/projects", headers=_headers(token))
        assert r.status_code == 200, r.text
        assert "projects" in r.json()

    def test_marketer_cannot_read_requirements(self, client, reg):
        email = _unique_email("mkt-req")
        reg.emails.append(email)
        token = _signup(client, email, "marketer")

        # The permission guard fires before tenant lookup, so the
        # session id does not need to exist.
        r = client.get(
            f"/api/projects/{_FAKE_SESSION_ID}/requirements",
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text

    def test_marketer_cannot_read_process_steps(self, client, reg):
        email = _unique_email("mkt-ps")
        reg.emails.append(email)
        token = _signup(client, email, "marketer")

        r = client.get(
            f"/api/projects/{_FAKE_SESSION_ID}/process-steps",
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text

    def test_marketer_cannot_read_solution_decisions(self, client, reg):
        email = _unique_email("mkt-sd")
        reg.emails.append(email)
        token = _signup(client, email, "marketer")

        r = client.get(
            f"/api/projects/{_FAKE_SESSION_ID}/solution-decisions",
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text

    def test_marketer_cannot_read_test_cases(self, client, reg):
        email = _unique_email("mkt-tc")
        reg.emails.append(email)
        token = _signup(client, email, "marketer")

        r = client.get(
            f"/api/projects/{_FAKE_SESSION_ID}/test-cases",
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text

    def test_marketer_cannot_read_training_steps(self, client, reg):
        email = _unique_email("mkt-tr")
        reg.emails.append(email)
        token = _signup(client, email, "marketer")

        r = client.get(
            f"/api/projects/{_FAKE_SESSION_ID}/training-steps",
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text

    def test_marketer_cannot_read_issues(self, client, reg):
        email = _unique_email("mkt-iss")
        reg.emails.append(email)
        token = _signup(client, email, "marketer")

        r = client.get(
            f"/api/projects/{_FAKE_SESSION_ID}/issues",
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text

    def test_marketer_cannot_read_health(self, client, reg):
        email = _unique_email("mkt-health")
        reg.emails.append(email)
        token = _signup(client, email, "marketer")

        r = client.get(
            f"/api/projects/{_FAKE_SESSION_ID}/health",
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text

    def test_marketer_cannot_read_coverage_gaps(self, client, reg):
        email = _unique_email("mkt-cov")
        reg.emails.append(email)
        token = _signup(client, email, "marketer")

        r = client.get(
            f"/api/projects/{_FAKE_SESSION_ID}/coverage-gaps",
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text

    def test_marketer_cannot_execute_phase(self, client, reg):
        email = _unique_email("mkt-phase")
        reg.emails.append(email)
        token = _signup(client, email, "marketer")

        r = client.post(
            f"/api/projects/{_FAKE_SESSION_ID}/phase/qa_testing/execute",
            json={},
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text

    def test_marketer_can_read_documents(self, client, reg):
        email = _unique_email("mkt-docs")
        reg.emails.append(email)
        token = _signup(client, email, "marketer")
        user_id = _user_id_for_email(email)

        sid = _own_project(user_id)

        r = client.get(
            f"/api/projects/{sid}/documents",
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text
        assert "documents" in r.json()

    def test_marketer_can_generate_documents(self, client, reg):
        email = _unique_email("mkt-gendoc")
        reg.emails.append(email)
        token = _signup(client, email, "marketer")
        user_id = _user_id_for_email(email)

        sid = _own_project(user_id)

        with patch.object(
            doc_generator,
            "generate_project_report",
            return_value="/tmp/fake-marketer-report.docx",
        ):
            r = client.post(
                f"/api/projects/{sid}/report",
                headers=_headers(token),
            )
        assert r.status_code == 200, r.text
        assert r.json()["filename"] == "fake-marketer-report.docx"


# ---------------------------------------------------------------------------
# 7. ERP User permissions
# ---------------------------------------------------------------------------
class TestErpUserPermissions:
    @patch("src.orchestrator_api.info_retriever")
    @patch("src.utils.llm.get_llm")
    def test_erp_user_can_chat(
        self, mock_get_llm, mock_info_retriever, client, reg,
    ):
        email = _unique_email("erp-chat")
        reg.emails.append(email)
        token = _signup(client, email, "erp_user")

        mock_info_retriever.return_value = {
            "kb_results": [],
            "web_results": [],
            "sources": [],
        }
        mock_llm = MagicMock()
        mock_llm.generate_content.return_value.text = "hello from mock"
        mock_get_llm.return_value = mock_llm

        r = client.post(
            "/api/chat",
            json={"message": "hi"},
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True

    def test_erp_user_cannot_create_project(self, client, reg):
        email = _unique_email("erp-noproj")
        reg.emails.append(email)
        token = _signup(client, email, "erp_user")

        r = client.post(
            "/api/projects/start",
            json={"project_name": "Nope", "module": "FI"},
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text

    def test_erp_user_can_submit_feedback(self, client, reg):
        email = _unique_email("erp-fb")
        reg.emails.append(email)
        token = _signup(client, email, "erp_user")

        # No session_id: global feedback has no tenant check.
        r = client.post(
            "/api/feedback",
            json={"rating": 5, "comment": "Great product"},
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# 8. Multi-role union at the HTTP layer
# ---------------------------------------------------------------------------
class TestMultiRoleUnion:
    def test_multi_role_developer_plus_marketer_gets_union(self, client, reg):
        """A user holding both Developer and Marketer can perform an
        action permitted by Developer and an action permitted by
        Marketer. This proves the union computed by
        `get_user_permissions` reaches the route guard.

        Note (flagged in the summary): in v1, Marketer's permission set
        is a strict subset of Developer's, so this test does not
        distinguish Developer-only from Developer+Marketer. It proves
        the multi-role mechanism produces a guard-satisfying result
        for both roles' actions, but a future role pair with disjoint
        permissions would be a stronger union demonstration."""
        email = _unique_email("multi")
        reg.emails.append(email)
        token = _signup(client, email, "developer")
        user_id = _user_id_for_email(email)

        # Add Marketer on top of Developer.
        _grant_role(user_id, "marketer")

        sid = _own_project(user_id)

        # Developer-granted action: SOLUTION_READ.
        r1 = client.get(
            f"/api/projects/{sid}/solution-decisions",
            headers=_headers(token),
        )
        assert r1.status_code == 200, r1.text

        # Marketer-granted action: PROJECT_READ on the project list.
        r2 = client.get("/api/projects", headers=_headers(token))
        assert r2.status_code == 200, r2.text


# ---------------------------------------------------------------------------
# 9. Generic permission denial
# ---------------------------------------------------------------------------
class TestGenericPermissionDenial:
    def test_user_without_required_permission_receives_403(self, client, reg):
        """An ERP User lacks DOCUMENTS_GENERATE. POST /report returns
        403 before the route body runs."""
        email = _unique_email("erp-nodoc")
        reg.emails.append(email)
        token = _signup(client, email, "erp_user")

        r = client.post(
            f"/api/projects/{_FAKE_SESSION_ID}/report",
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text
        assert r.json()["error"]["code"] == 403


# ---------------------------------------------------------------------------
# 10. Permission vs. tenant ordering
# ---------------------------------------------------------------------------
class TestPermissionTenantOrdering:
    def test_permission_guard_runs_before_tenant_boundary_for_missing_permission(
        self, client, reg,
    ):
        """A Marketer lacks REQUIREMENTS_READ. The request targets a
        nonexistent session id. The response is 403 (permission), not
        404 (tenant). If the tenant check ran first, it would produce
        404 because the session does not exist."""
        email = _unique_email("mkt-order-1")
        reg.emails.append(email)
        token = _signup(client, email, "marketer")

        r = client.get(
            f"/api/projects/{_FAKE_SESSION_ID}/requirements",
            headers=_headers(token),
        )
        assert r.status_code == 403, r.text

    def test_tenant_boundary_runs_after_permission_guard_for_authorized_but_wrong_tenant(
        self, client, reg,
    ):
        """A Functional Consultant has PROJECT_READ (so the permission
        guard passes) but is not the owner of a foreign personal
        session. The response is 404, not 200. This isolates the
        tenant boundary: with the permission granted, the only thing
        that can deny access is `_get_owned_session`."""
        foreign_email = _unique_email("foreign-owner")
        caller_email = _unique_email("fc-caller")
        reg.emails.extend([foreign_email, caller_email])

        _signup(client, foreign_email, "functional_consultant")
        foreign_user_id = _user_id_for_email(foreign_email)
        foreign_sid = _own_project(foreign_user_id, name="Foreign Project")

        caller_token = _signup(client, caller_email, "functional_consultant")

        r = client.get(
            f"/api/projects/{foreign_sid}/status",
            headers=_headers(caller_token),
        )
        assert r.status_code == 404, r.text
        assert r.json()["error"]["code"] == 404


# ---------------------------------------------------------------------------
# 11. Chat tenant enforcement
# ---------------------------------------------------------------------------
class TestChatTenantBoundary:
    def test_chat_with_foreign_session_returns_404(self, client, reg):
        """A caller with CHAT_SUBMIT is denied 404 when targeting
        another user's personal session. `_get_owned_session` runs
        before the LLM is touched, so no LLM mocking is required."""
        foreign_email = _unique_email("chat-foreign")
        caller_email = _unique_email("chat-caller")
        reg.emails.extend([foreign_email, caller_email])

        _signup(client, foreign_email, "functional_consultant")
        foreign_user_id = _user_id_for_email(foreign_email)
        foreign_sid = _own_project(foreign_user_id, name="Foreign Chat Project")

        caller_token = _signup(client, caller_email, "functional_consultant")

        r = client.post(
            "/api/chat",
            json={"message": "hi", "session_id": foreign_sid},
            headers=_headers(caller_token),
        )
        assert r.status_code == 404, r.text
        assert r.json()["error"]["code"] == 404

    def test_chat_with_org_session_foreign_org_returns_404(self, client, reg):
        """A caller with CHAT_SUBMIT who is not a member of the
        organization owning the target session receives 404."""
        owner_email = _unique_email("chat-org-owner")
        caller_email = _unique_email("chat-org-outsider")
        reg.emails.extend([owner_email, caller_email])

        _signup(client, owner_email, "functional_consultant")
        owner_id = _user_id_for_email(owner_email)

        org_id = _insert_org_with_owner(owner_id, _unique_email("org"))
        reg.org_ids.append(org_id)

        # Org-owned project created directly, so the session carries
        # organization_id = org_id.
        org_sid = agent_memory.create_project(
            project_name="Org Chat Project",
            module="FI",
            user_id=owner_id,
            organization_id=org_id,
        )

        caller_token = _signup(client, caller_email, "functional_consultant")

        r = client.post(
            "/api/chat",
            json={"message": "hi", "session_id": org_sid},
            headers=_headers(caller_token),
        )
        assert r.status_code == 404, r.text
        assert r.json()["error"]["code"] == 404


# ---------------------------------------------------------------------------
# 12. Feedback enforcement
# ---------------------------------------------------------------------------
class TestFeedbackPermissions:
    def test_feedback_global_has_no_tenant_check(self, client, reg):
        """POST /api/feedback without a session_id is not tenant-scoped.
        Any role with FEEDBACK_SUBMIT (all four hold it via
        `_COMMON_USER_PERMS`) succeeds."""
        email = _unique_email("fb-global")
        reg.emails.append(email)
        token = _signup(client, email, "marketer")

        r = client.post(
            "/api/feedback",
            json={"rating": 4, "comment": "Global feedback"},
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True

    def test_feedback_session_scoped_enforces_tenant_boundary(self, client, reg):
        """POST /api/feedback with a session_id from a foreign personal
        session returns 404 via `_get_owned_session`."""
        foreign_email = _unique_email("fb-foreign")
        caller_email = _unique_email("fb-caller")
        reg.emails.extend([foreign_email, caller_email])

        _signup(client, foreign_email, "functional_consultant")
        foreign_user_id = _user_id_for_email(foreign_email)
        foreign_sid = _own_project(foreign_user_id, name="Foreign FB Project")

        caller_token = _signup(client, caller_email, "functional_consultant")

        r = client.post(
            "/api/feedback",
            json={"session_id": foreign_sid, "rating": 4},
            headers=_headers(caller_token),
        )
        assert r.status_code == 404, r.text
        assert r.json()["error"]["code"] == 404


# ---------------------------------------------------------------------------
# 13. Profile edit — current behavior locks in the deferred enforcement
# ---------------------------------------------------------------------------
class TestProfileEditCurrentBehavior:
    def test_profile_edit_defined_but_not_enforced(self, client, reg):
        """`PROFILE_EDIT` is defined in the permission enum and held by
        every role via `_COMMON_USER_PERMS`, but `PATCH /api/auth/settings`
        is on `get_current_user` rather than `require_permission`.
        Enforcement is deliberately deferred to the account/profile
        round. This test locks in the current behavior so an accidental
        addition of a guard would surface as a focused failure rather
        than as an unexplained response change elsewhere."""
        email = _unique_email("profile")
        reg.emails.append(email)
        token = _signup(client, email, "marketer")

        r = client.patch(
            "/api/auth/settings",
            json={"name": "New Name"},
            headers=_headers(token),
        )
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "New Name"