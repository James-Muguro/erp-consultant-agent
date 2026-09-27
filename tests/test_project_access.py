"""
Tests for src/auth/project_access.py and the ERP User role tightening.

Scope:
  * Project membership resolution (personal + organization-owned).
  * Artifact grant lifecycle (create, revoke, idempotency).
  * Designation semantics (FRD signatory, UAT participant).
  * Artifact-type and designation coherence validation.
  * Historical grants coexisting with regrants.
  * Attribution (granted_by_user_id / revoked_by_user_id).
  * The Phase 2.3 role-permission change: ERP User no longer holds
    blanket project-artifact read permissions; Functional Consultant
    holds PROJECT_GRANTS_MANAGE.

No endpoints, no routes, no frontend. This file exercises the helper
module directly against a real database session, using the same schema
that migrations produce.

Database cleanup: every test uses the `tracked` fixture, which records
created user IDs, session IDs, and org IDs and deletes them at teardown
in FK-safe order (sessions -> orgs -> users). Session cascade removes
any grants attached to those sessions; user cascade removes any
remaining grants.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List

import pytest
from sqlalchemy.orm import Session

from src.auth import project_access
from src.auth.permissions import (
    Permission,
    ROLE_PERMISSIONS,
    UserRole,
)
from src.auth.project_access import ArtifactType
from src.db.base import SessionLocal, init_db
from src.db.models import (
    Organization,
    OrganizationMembership,
    SessionRecord,
    SessionUserArtifactGrant,
    User,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module", autouse=True)
def _ensure_schema():
    init_db()
    yield


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


class _Tracked:
    def __init__(self) -> None:
        self.user_ids: List[str] = []
        self.session_ids: List[str] = []
        self.org_ids: List[str] = []


@pytest.fixture
def tracked():
    """Record created rows and clean them up at teardown.

    Order: sessions first (they hold the only RESTRICT-ref to
    organizations), then organizations, then users. Session cascade
    removes child grants; user cascade removes any remaining grants and
    organization memberships. A final safety pass deletes any lingering
    grants by user_id in case a session was created indirectly.
    """
    t = _Tracked()
    yield t
    session = SessionLocal()
    try:
        if t.session_ids:
            session.query(SessionRecord).filter(
                SessionRecord.session_id.in_(t.session_ids)
            ).delete(synchronize_session=False)
        if t.org_ids:
            session.query(Organization).filter(
                Organization.id.in_(t.org_ids)
            ).delete(synchronize_session=False)
        if t.user_ids:
            session.query(SessionUserArtifactGrant).filter(
                SessionUserArtifactGrant.user_id.in_(t.user_ids)
            ).delete(synchronize_session=False)
            session.query(User).filter(
                User.id.in_(t.user_ids)
            ).delete(synchronize_session=False)
        session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_user(db: Session, tracked: _Tracked, suffix: str = "") -> User:
    uid = uuid.uuid4().hex
    user = User(
        id=uid,
        email=f"pa-{suffix or uid[:12]}@example.com",
        hashed_password="not-a-real-hash",
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()
    tracked.user_ids.append(uid)
    return user


def _make_personal_session(db: Session, tracked: _Tracked, owner_id: str) -> SessionRecord:
    sid = f"prj_pa_{uuid.uuid4().hex[:12]}"
    record = SessionRecord(
        session_id=sid,
        user_id=owner_id,
        organization_id=None,
        project_name="PA Personal Test",
        module="FI",
        erp_system="SAP S/4HANA",
        current_phase="requirements_gathering",
        is_casual=False,
        data={},
    )
    db.add(record)
    db.commit()
    tracked.session_ids.append(sid)
    return record


def _make_org(db: Session, tracked: _Tracked, owner_id: str) -> Organization:
    oid = uuid.uuid4().hex
    org = Organization(
        id=oid,
        name=f"PA Org {oid[:6]}",
        created_by=owner_id,
    )
    db.add(org)
    db.add(OrganizationMembership(
        id=uuid.uuid4().hex,
        organization_id=oid,
        user_id=owner_id,
        role="owner",
    ))
    db.commit()
    tracked.org_ids.append(oid)
    return org


def _add_org_member(
    db: Session, org_id: str, user_id: str, role: str = "member",
) -> None:
    db.add(OrganizationMembership(
        id=uuid.uuid4().hex,
        organization_id=org_id,
        user_id=user_id,
        role=role,
    ))
    db.commit()


def _make_org_session(db: Session, tracked: _Tracked, org_id: str) -> SessionRecord:
    sid = f"prj_pa_{uuid.uuid4().hex[:12]}"
    record = SessionRecord(
        session_id=sid,
        user_id=None,
        organization_id=org_id,
        project_name="PA Org Test",
        module="FI",
        erp_system="SAP S/4HANA",
        current_phase="requirements_gathering",
        is_casual=False,
        data={},
    )
    db.add(record)
    db.commit()
    tracked.session_ids.append(sid)
    return record


# ===========================================================================
# Membership resolution
# ===========================================================================
class TestIsProjectMember:
    def test_personal_project_membership(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        assert project_access.is_project_member(db, session.session_id, owner.id) is True

    def test_personal_project_non_owner_is_not_member(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        other = _make_user(db, tracked, "other")
        session = _make_personal_session(db, tracked, owner.id)
        assert project_access.is_project_member(db, session.session_id, other.id) is False

    def test_org_project_membership_via_organization_membership(self, db, tracked):
        owner = _make_user(db, tracked, "orgowner")
        member = _make_user(db, tracked, "orgmember")
        org = _make_org(db, tracked, owner.id)
        _add_org_member(db, org.id, member.id, role="member")
        session = _make_org_session(db, tracked, org.id)

        assert project_access.is_project_member(db, session.session_id, owner.id) is True
        assert project_access.is_project_member(db, session.session_id, member.id) is True

    def test_org_project_non_member_is_not_member(self, db, tracked):
        owner = _make_user(db, tracked, "orgowner")
        outsider = _make_user(db, tracked, "outsider")
        org = _make_org(db, tracked, owner.id)
        session = _make_org_session(db, tracked, org.id)

        assert project_access.is_project_member(db, session.session_id, outsider.id) is False

    def test_org_project_ignores_session_user_id(self, db, tracked):
        """An org-owned project's `user_id` is attribution, not access.
        A user recorded as the session's user_id but without a
        membership in the owning organization is NOT a member."""
        org_owner = _make_user(db, tracked, "orgowner")
        attributed = _make_user(db, tracked, "attributed")
        org = _make_org(db, tracked, org_owner.id)

        sid = f"prj_pa_{uuid.uuid4().hex[:12]}"
        record = SessionRecord(
            session_id=sid,
            user_id=attributed.id,
            organization_id=org.id,
            project_name="PA Org Attribution",
            module="FI",
            erp_system="SAP S/4HANA",
            current_phase="requirements_gathering",
            is_casual=False,
            data={},
        )
        db.add(record)
        db.commit()
        tracked.session_ids.append(sid)

        assert project_access.is_project_member(db, sid, attributed.id) is False

    def test_missing_project_is_not_member(self, db, tracked):
        user = _make_user(db, tracked, "any")
        assert project_access.is_project_member(db, "prj_does_not_exist", user.id) is False


# ===========================================================================
# Artifact access
# ===========================================================================
class TestUserHasArtifactAccess:
    def test_member_with_active_grant_has_access(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        project_access.create_grant(
            db, session.session_id, owner.id,
            ArtifactType.REQUIREMENTS_QUESTIONNAIRE, owner.id,
        )
        db.commit()
        assert project_access.user_has_artifact_access(
            db, session.session_id, owner.id,
            ArtifactType.REQUIREMENTS_QUESTIONNAIRE,
        ) is True

    def test_member_without_grant_has_no_access(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        assert project_access.user_has_artifact_access(
            db, session.session_id, owner.id, ArtifactType.FRD,
        ) is False

    def test_non_member_with_grant_does_not_have_access(self, db, tracked):
        """A grant is not sufficient by itself. Membership is required.
        This can only happen if a grant survives a membership
        revocation; the helper must still deny access."""
        owner = _make_user(db, tracked, "orgowner")
        revoked_member = _make_user(db, tracked, "revokedmember")
        org = _make_org(db, tracked, owner.id)
        _add_org_member(db, org.id, revoked_member.id, role="member")
        session = _make_org_session(db, tracked, org.id)

        project_access.create_grant(
            db, session.session_id, revoked_member.id,
            ArtifactType.FRD, owner.id,
        )
        db.commit()

        # Revoke membership.
        db.query(OrganizationMembership).filter(
            OrganizationMembership.organization_id == org.id,
            OrganizationMembership.user_id == revoked_member.id,
        ).delete(synchronize_session=False)
        db.commit()

        assert project_access.user_has_artifact_access(
            db, session.session_id, revoked_member.id, ArtifactType.FRD,
        ) is False

    def test_grant_scoped_to_project(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session_a = _make_personal_session(db, tracked, owner.id)
        session_b = _make_personal_session(db, tracked, owner.id)
        project_access.create_grant(
            db, session_a.session_id, owner.id,
            ArtifactType.FRD, owner.id,
        )
        db.commit()
        assert project_access.user_has_artifact_access(
            db, session_a.session_id, owner.id, ArtifactType.FRD,
        ) is True
        assert project_access.user_has_artifact_access(
            db, session_b.session_id, owner.id, ArtifactType.FRD,
        ) is False

    def test_grant_scoped_to_artifact(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        project_access.create_grant(
            db, session.session_id, owner.id,
            ArtifactType.FRD, owner.id,
        )
        db.commit()
        assert project_access.user_has_artifact_access(
            db, session.session_id, owner.id, ArtifactType.FRD,
        ) is True
        assert project_access.user_has_artifact_access(
            db, session.session_id, owner.id,
            ArtifactType.TRAINING_MATERIALS,
        ) is False

    def test_revoked_grant_denies_access(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        project_access.create_grant(
            db, session.session_id, owner.id,
            ArtifactType.FRD, owner.id,
        )
        db.commit()
        assert project_access.user_has_artifact_access(
            db, session.session_id, owner.id, ArtifactType.FRD,
        ) is True

        revoked = project_access.revoke_grant(
            db, session.session_id, owner.id, ArtifactType.FRD, owner.id,
        )
        db.commit()
        assert revoked is True
        assert project_access.user_has_artifact_access(
            db, session.session_id, owner.id, ArtifactType.FRD,
        ) is False

    def test_multiple_artifact_types_are_independent(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        for artifact in (
            ArtifactType.REQUIREMENTS_QUESTIONNAIRE,
            ArtifactType.FRD,
            ArtifactType.UAT_SCENARIOS,
            ArtifactType.TRAINING_MATERIALS,
        ):
            project_access.create_grant(
                db, session.session_id, owner.id, artifact, owner.id,
            )
        db.commit()
        for artifact in (
            ArtifactType.REQUIREMENTS_QUESTIONNAIRE,
            ArtifactType.FRD,
            ArtifactType.UAT_SCENARIOS,
            ArtifactType.TRAINING_MATERIALS,
        ):
            assert project_access.user_has_artifact_access(
                db, session.session_id, owner.id, artifact,
            ) is True


# ===========================================================================
# Signatory and UAT designation
# ===========================================================================
class TestSignatory:
    def test_frd_grant_without_signatory_is_not_signatory(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        project_access.create_grant(
            db, session.session_id, owner.id,
            ArtifactType.FRD, owner.id,
        )
        db.commit()
        assert project_access.user_is_frd_signatory(
            db, session.session_id, owner.id,
        ) is False

    def test_frd_grant_with_signatory_is_signatory(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        project_access.create_grant(
            db, session.session_id, owner.id,
            ArtifactType.FRD, owner.id, is_signatory=True,
        )
        db.commit()
        assert project_access.user_is_frd_signatory(
            db, session.session_id, owner.id,
        ) is True
        # Signatory implies FRD access.
        assert project_access.user_has_artifact_access(
            db, session.session_id, owner.id, ArtifactType.FRD,
        ) is True

    def test_signatory_revoked_removes_designation(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        project_access.create_grant(
            db, session.session_id, owner.id,
            ArtifactType.FRD, owner.id, is_signatory=True,
        )
        db.commit()
        assert project_access.user_is_frd_signatory(
            db, session.session_id, owner.id,
        ) is True
        project_access.revoke_grant(
            db, session.session_id, owner.id, ArtifactType.FRD, owner.id,
        )
        db.commit()
        assert project_access.user_is_frd_signatory(
            db, session.session_id, owner.id,
        ) is False

    def test_signatory_on_wrong_artifact_rejected(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        with pytest.raises(ValueError, match="is_signatory"):
            project_access.create_grant(
                db, session.session_id, owner.id,
                ArtifactType.REQUIREMENTS_QUESTIONNAIRE, owner.id,
                is_signatory=True,
            )


class TestUatParticipant:
    def test_uat_grant_without_participant_flag_is_not_participant(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        project_access.create_grant(
            db, session.session_id, owner.id,
            ArtifactType.UAT_SCENARIOS, owner.id,
        )
        db.commit()
        assert project_access.user_is_uat_participant(
            db, session.session_id, owner.id,
        ) is False

    def test_uat_grant_with_participant_flag_is_participant(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        project_access.create_grant(
            db, session.session_id, owner.id,
            ArtifactType.UAT_SCENARIOS, owner.id, is_uat_participant=True,
        )
        db.commit()
        assert project_access.user_is_uat_participant(
            db, session.session_id, owner.id,
        ) is True

    def test_uat_participant_does_not_grant_general_testing(self, db, tracked):
        """UAT participant is a designation on the UAT scenarios grant.
        It does not extend to other testing artifacts or to any general
        testing access; TESTING_READ remains a role capability."""
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        project_access.create_grant(
            db, session.session_id, owner.id,
            ArtifactType.UAT_SCENARIOS, owner.id, is_uat_participant=True,
        )
        db.commit()
        # Not granted any other artifact.
        assert project_access.user_has_artifact_access(
            db, session.session_id, owner.id,
            ArtifactType.TRAINING_MATERIALS,
        ) is False

    def test_uat_participant_on_wrong_artifact_rejected(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        with pytest.raises(ValueError, match="is_uat_participant"):
            project_access.create_grant(
                db, session.session_id, owner.id,
                ArtifactType.FRD, owner.id, is_uat_participant=True,
            )


# ===========================================================================
# Grant mutation
# ===========================================================================
class TestCreateGrant:
    def test_create_grant_requires_membership(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        outsider = _make_user(db, tracked, "outsider")
        session = _make_personal_session(db, tracked, owner.id)
        with pytest.raises(ValueError, match="not a member"):
            project_access.create_grant(
                db, session.session_id, outsider.id,
                ArtifactType.FRD, owner.id,
            )

    def test_create_grant_idempotent_same_designation(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        g1 = project_access.create_grant(
            db, session.session_id, owner.id,
            ArtifactType.FRD, owner.id,
        )
        db.commit()
        g2 = project_access.create_grant(
            db, session.session_id, owner.id,
            ArtifactType.FRD, owner.id,
        )
        db.commit()
        assert g1.id == g2.id
        # Exactly one active row.
        active = (
            db.query(SessionUserArtifactGrant)
            .filter(
                SessionUserArtifactGrant.session_id == session.session_id,
                SessionUserArtifactGrant.user_id == owner.id,
                SessionUserArtifactGrant.artifact_type == ArtifactType.FRD.value,
                SessionUserArtifactGrant.revoked_at.is_(None),
            )
            .all()
        )
        assert len(active) == 1

    def test_create_grant_idempotent_with_designation_change(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        g1 = project_access.create_grant(
            db, session.session_id, owner.id,
            ArtifactType.FRD, owner.id,
        )
        db.commit()
        assert g1.is_signatory is False

        g2 = project_access.create_grant(
            db, session.session_id, owner.id,
            ArtifactType.FRD, owner.id, is_signatory=True,
        )
        db.commit()
        # Same physical row, flag updated in place.
        assert g1.id == g2.id
        assert g2.is_signatory is True
        assert project_access.user_is_frd_signatory(
            db, session.session_id, owner.id,
        ) is True

    def test_create_grant_rejects_unknown_artifact_type(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        with pytest.raises(ValueError, match="Unknown artifact type"):
            project_access.create_grant(
                db, session.session_id, owner.id,
                "not_a_real_artifact_type", owner.id,
            )

    def test_get_active_grant_rejects_unknown_artifact_type(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        with pytest.raises(ValueError, match="Unknown artifact type"):
            project_access.get_active_grant(
                db, session.session_id, owner.id, "not_a_real_artifact_type",
            )


class TestRevokeGrant:
    def test_revoke_grant_idempotent(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        project_access.create_grant(
            db, session.session_id, owner.id,
            ArtifactType.FRD, owner.id,
        )
        db.commit()
        assert project_access.revoke_grant(
            db, session.session_id, owner.id, ArtifactType.FRD, owner.id,
        ) is True
        db.commit()
        # Second revoke is a no-op that reports False.
        assert project_access.revoke_grant(
            db, session.session_id, owner.id, ArtifactType.FRD, owner.id,
        ) is False

    def test_revoke_nonexistent_is_false(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        assert project_access.revoke_grant(
            db, session.session_id, owner.id, ArtifactType.FRD, owner.id,
        ) is False


# ===========================================================================
# Historical grants and regrant
# ===========================================================================
class TestHistoricalGrants:
    def test_regrant_after_revoke_creates_new_active_row(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        session = _make_personal_session(db, tracked, owner.id)
        g1 = project_access.create_grant(
            db, session.session_id, owner.id,
            ArtifactType.FRD, owner.id,
        )
        db.commit()
        project_access.revoke_grant(
            db, session.session_id, owner.id, ArtifactType.FRD, owner.id,
        )
        db.commit()

        g2 = project_access.create_grant(
            db, session.session_id, owner.id,
            ArtifactType.FRD, owner.id,
        )
        db.commit()

        assert g1.id != g2.id

        # Both rows exist: one revoked (historical), one active (current).
        all_rows = (
            db.query(SessionUserArtifactGrant)
            .filter(
                SessionUserArtifactGrant.session_id == session.session_id,
                SessionUserArtifactGrant.user_id == owner.id,
                SessionUserArtifactGrant.artifact_type == ArtifactType.FRD.value,
            )
            .all()
        )
        assert len(all_rows) == 2
        active = [r for r in all_rows if r.revoked_at is None]
        revoked = [r for r in all_rows if r.revoked_at is not None]
        assert len(active) == 1 and active[0].id == g2.id
        assert len(revoked) == 1 and revoked[0].id == g1.id


# ===========================================================================
# Attribution
# ===========================================================================
class TestAttribution:
    def test_grant_attribution_recorded(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        consultant = _make_user(db, tracked, "consultant")
        session = _make_personal_session(db, tracked, owner.id)
        grant = project_access.create_grant(
            db, session.session_id, owner.id,
            ArtifactType.FRD, consultant.id,
        )
        db.commit()
        assert grant.granted_by_user_id == consultant.id
        assert grant.granted_at is not None

    def test_revoke_attribution_recorded(self, db, tracked):
        owner = _make_user(db, tracked, "owner")
        consultant = _make_user(db, tracked, "consultant")
        session = _make_personal_session(db, tracked, owner.id)
        project_access.create_grant(
            db, session.session_id, owner.id,
            ArtifactType.FRD, consultant.id,
        )
        db.commit()
        project_access.revoke_grant(
            db, session.session_id, owner.id, ArtifactType.FRD, consultant.id,
        )
        db.commit()
        revoked = (
            db.query(SessionUserArtifactGrant)
            .filter(
                SessionUserArtifactGrant.session_id == session.session_id,
                SessionUserArtifactGrant.user_id == owner.id,
                SessionUserArtifactGrant.artifact_type == ArtifactType.FRD.value,
            )
            .one()
        )
        assert revoked.revoked_by_user_id == consultant.id
        assert revoked.revoked_at is not None


# ===========================================================================
# Role permission changes (Phase 2.3)
# ===========================================================================
class TestRolePermissionChanges:
    def test_erp_user_no_longer_holds_blanket_project_read_permissions(self):
        """ERP User's project-artifact access is context-scoped and
        grant-driven, not role-level. The read permissions that used to
        be bundled must no longer appear on the role."""
        erp_perms = ROLE_PERMISSIONS[UserRole.ERP_USER]
        forbidden = {
            Permission.REQUIREMENTS_READ,
            Permission.PROCESS_STEPS_READ,
            Permission.SOLUTION_READ,
            Permission.TESTING_READ,
            Permission.TRAINING_READ,
            Permission.ISSUES_READ,
            Permission.HEALTH_READ,
            Permission.DOCUMENTS_READ,
            Permission.UPLOADS_READ,
        }
        overlap = erp_perms & forbidden
        assert overlap == frozenset(), (
            f"ERP User must not hold role-level artifact read "
            f"permissions; unexpected: {sorted(p.value for p in overlap)}"
        )

    def test_erp_user_retains_cross_cutting_and_project_read(self):
        erp_perms = ROLE_PERMISSIONS[UserRole.ERP_USER]
        for perm in (
            Permission.CHAT_SUBMIT,
            Permission.FEEDBACK_SUBMIT,
            Permission.PROFILE_EDIT,
            Permission.PROJECT_READ,
        ):
            assert perm in erp_perms, f"ERP User should hold {perm.value}"

    def test_functional_consultant_holds_project_grants_manage(self):
        assert (
            Permission.PROJECT_GRANTS_MANAGE
            in ROLE_PERMISSIONS[UserRole.FUNCTIONAL_CONSULTANT]
        )

    def test_developer_does_not_hold_project_grants_manage(self):
        assert (
            Permission.PROJECT_GRANTS_MANAGE
            not in ROLE_PERMISSIONS[UserRole.DEVELOPER]
        )

    def test_erp_user_does_not_hold_project_grants_manage(self):
        assert (
            Permission.PROJECT_GRANTS_MANAGE
            not in ROLE_PERMISSIONS[UserRole.ERP_USER]
        )

    def test_business_development_does_not_hold_project_grants_manage(self):
        assert (
            Permission.PROJECT_GRANTS_MANAGE
            not in ROLE_PERMISSIONS[UserRole.BUSINESS_DEVELOPMENT]
        )