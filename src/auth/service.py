"""
User account operations against the `users` table.

Kept as plain functions taking a SQLAlchemy Session rather than a class,
matching the lightweight style of the rest of the codebase.

Signup transaction boundary
---------------------------
create_user performs the ENTIRE signup in one transaction:
  1. the user row
  2. for individual account types: the initial application role row
     (user_roles)
  3. for organization signup: the organization row and its Owner
     membership row (organization_memberships)

There is exactly one commit. Any failure - including a race on the
users.email unique constraint - rolls back every insert from this call.
The invariant the signup flow relies on: a successfully created user is
never left in a partially-signed-up state.

An explicit flush is issued immediately after the user is added. Without
it, SQLAlchemy's flush-time ordering of pending INSERTs cannot be relied
on to emit `users` before `organizations` for this object graph (the
three mappers declare bare column-level ForeignKeys with no
relationship() between them). The observed effect on PostgreSQL was a
ForeignKeyViolation on `organizations_created_by_fkey` because the
INSERT INTO organizations was emitted before the INSERT INTO users. The
flush makes the required emission order explicit: the users row is
written inside the transaction first, then organizations, then
organization_memberships, all committed together by the same single
commit().

Application roles vs. organization roles
----------------------------------------
An individual signup grants exactly one application role: the role
matching the chosen AccountType. An organization signup grants NO
application role. Organization is a tenant context, not a role; the
creator's authorization for organization features comes from their
OrganizationMembership.role ('owner'), which is a separate axis from
application roles.

Design notes carried over from prior revisions:

  * authenticate_user is timing-resistant.
  * create_user handles the concurrent-signup race via IntegrityError.
  * Every mutating function rolls back explicitly on failure.
  * Failed authentications are logged with reason class but never the
    password or a distinguishing detail.
"""
from __future__ import annotations

from src.utils.logger import get_logger
import uuid
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.auth.permissions import AccountType
from src.auth.rbac import create_organization, grant_role
from src.auth.security import hash_password, verify_password
from src.db.models import User

logger = get_logger(__name__)


class EmailAlreadyRegistered(Exception):
    """Raised when a signup targets an email that already exists.
    Endpoint translates this to HTTP 409."""


# ---------------------------------------------------------------------------
# Dummy hash for timing-resistant authentication
# ---------------------------------------------------------------------------
_DUMMY_HASH_FOR_TIMING = hash_password(
    "definitely-not-a-real-password-for-timing-resistance"
)


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email.lower()).first()


def get_user_by_id(db: Session, user_id: str) -> Optional[User]:
    return db.get(User, user_id)


def create_user(
    db: Session,
    email: str,
    password: str,
    account_type: AccountType,
    organization_name: Optional[str] = None,
) -> User:
    """Create a user account for one of the five account types.

    account_type is required. It determines what is created atomically
    alongside the user row:

      * Individual account types (ERP_USER, FUNCTIONAL_CONSULTANT,
        DEVELOPER, MARKETER): one UserRoleRecord with the matching
        application role.

      * Organization: one Organization row and one OrganizationMembership
        with role='owner'. NO UserRoleRecord. Organization is a tenant
        context, not an application role.

    organization_name is only consulted when account_type is
    ORGANIZATION. It is validated by SignupRequest before this function
    is called; the ValueError below is a defensive second check so a
    direct caller that bypasses the schema cannot create a nameless
    tenant.

    Raises:
        EmailAlreadyRegistered: if the email is already in use, or if a
            concurrent signup wins the race on the unique constraint.
        ValueError: if organization signup is missing organization_name.
    """
    email = email.lower()

    # Validate before touching the DB so we do not start a transaction
    # that cannot succeed.
    if account_type is AccountType.ORGANIZATION:
        if not organization_name or not organization_name.strip():
            raise ValueError(
                "organization_name is required for organization signup."
            )

    # Cheap pre-check so we can return a fast, clean error in the common
    # case. Not sufficient on its own - see the IntegrityError handler
    # below, which catches the race.
    if get_user_by_email(db, email):
        raise EmailAlreadyRegistered(f"{email} is already registered")

    # Hash BEFORE the try block: hash_password does not touch the DB, and
    # keeping it outside means a hashing failure cannot leave a pending
    # transaction behind.
    hashed = hash_password(password)

    user = User(
        id=uuid.uuid4().hex,
        email=email,
        hashed_password=hashed,
    )
    db.add(user)
    # Emit the users INSERT before any dependent rows are added. See the
    # module docstring for the reason: without this, SQLAlchemy's
    # flush-time ordering of pending INSERTs can emit `organizations`
    # before `users` for this object graph, producing a ForeignKeyViolation
    # on organizations_created_by_fkey.
    db.flush()

    try:
        # SQLAlchemy's unit-of-work orders INSERTs to satisfy foreign
        # keys, so the user row is inserted before user_roles or
        # organization_memberships rows that reference it. The explicit
        # flush above makes this ordering deterministic rather than
        # relying on the sorter.
        if account_type is AccountType.ORGANIZATION:
            # Tenant creation only. Deliberately NO grant_role call:
            # Organization is not an application role, and the four
            # application roles are not being granted to org owners as
            # a side effect of creating a tenant. The user's `roles`
            # field will be empty on GET /api/auth/me until an
            # application role is granted by a later mechanism.
            create_organization(db, organization_name.strip(), user.id)
        else:
            grant_role(db, user.id, account_type.to_user_role())

        db.commit()
    except IntegrityError as e:
        db.rollback()
        # The only unique constraint that a fresh signup can plausibly
        # race on is users.email: a concurrent signup for the same email
        # passed the pre-check in parallel and reached the constraint
        # first. Any other IntegrityError is unexpected and propagated
        # rather than mislabelled.
        err_text = str(e).lower()
        if "email" in err_text:
            logger.info(
                "Signup raced on email unique constraint",
                email_lower=email,
                account_type=account_type.value,
            )
            raise EmailAlreadyRegistered(f"{email} is already registered") from e
        logger.error(
            "Unexpected IntegrityError during signup",
            error=str(e),
            account_type=account_type.value,
        )
        raise
    except Exception:
        # Any other commit failure (DB down, disk full): roll back so the
        # session is not left with a pending transaction, then propagate.
        db.rollback()
        raise

    db.refresh(user)
    logger.info(
        "User signed up",
        user_id=user.id,
        account_type=account_type.value,
        organization_created=account_type is AccountType.ORGANIZATION,
    )
    return user


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    """Verify credentials.

    Timing-resistant: a login against a nonexistent email spends the same
    bcrypt work as a login against an existing email with a wrong
    password. Returns None on any failure - the endpoint turns that into
    a uniform 401.
    """
    user = get_user_by_email(db, email)

    if user is None:
        verify_password(password, _DUMMY_HASH_FOR_TIMING)
        logger.info("Authentication failed", reason="unknown_email")
        return None

    if not verify_password(password, user.hashed_password):
        logger.info("Authentication failed", reason="bad_password", user_id=user.id)
        return None

    return user


def update_profile(
    db: Session,
    user: User,
    name: Optional[str],
    profile_picture_url: Optional[str],
) -> User:
    """Update display name and/or profile picture URL. Full-replace for
    both fields - a caller passing None clears it."""
    user.name = name.strip() if name and name.strip() else None
    user.profile_picture_url = (
        profile_picture_url.strip() if profile_picture_url and profile_picture_url.strip() else None
    )

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(user)
    return user


def change_password(
    db: Session,
    user: User,
    current_password: str,
    new_password: str,
) -> bool:
    """Change a user's password. Returns True on success, False if the
    current password is wrong.

    Does not invalidate existing access tokens - see the module docstring
    and SECURITY.md for the reasoning.
    """
    if not verify_password(current_password, user.hashed_password):
        logger.info("Password change rejected", reason="bad_current_password", user_id=user.id)
        return False

    user.hashed_password = hash_password(new_password)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    logger.info("Password changed", user_id=user.id)
    return True