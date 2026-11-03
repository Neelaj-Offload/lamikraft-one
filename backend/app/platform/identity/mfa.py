"""TOTP multi-factor authentication (RFC 6238 via pyotp) with recovery codes.

- A 160-bit seed is generated per enrolment and stored AES-GCM encrypted (``identity.crypto``), bound to its
  user by the associated data.
- Codes are checked against the business clock with a window of one step either side; a code from a step at or
  before ``last_used_step`` is a replay and is refused.
- Ten single-use recovery codes are generated at confirmation (and on regeneration) and shown once; only keyed
  HMACs are stored.
- Policy (permissions.md §6, platform design §4): members holding a *privileged* MFA-flagged key (identity, org,
  audit, system and numbering administration) must use MFA at sign-in; the ``security_policy`` setting can extend
  that to every member. Other MFA-flagged keys are enforced at use time through ``authz.stepup``.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import pyotp
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.platform.authz.permissions import Scope
from app.platform.identity.credential_models import MfaFactor, MfaRecoveryCode
from app.platform.identity.crypto import Sealed, seal, unseal
from app.platform.identity.tokens import keyed_hash

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

ISSUER = "Lamikraft One"
STEP_SECONDS = 30
VALID_WINDOW = 1
RECOVERY_CODE_COUNT = 10
MAX_PENDING_ATTEMPTS = 5
#: modules whose MFA-flagged keys make a member "privileged" (MFA required at sign-in)
PRIVILEGED_MODULES = frozenset({"identity", "org", "audit", "system", "numbering"})
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def _aad(user_id: uuid.UUID) -> str:
    return f"mfa_factor:{user_id}"


def new_secret() -> str:
    return pyotp.random_base32(length=32)  # 32 base32 characters = 160 bits


def seal_secret(user_id: uuid.UUID, secret: str) -> Sealed:
    return seal(secret.encode("ascii"), aad=_aad(user_id))


def open_secret(factor: MfaFactor) -> str:
    return unseal(Sealed(factor.key_id, bytes(factor.secret_ciphertext)), aad=_aad(factor.user_id)).decode("ascii")


def provisioning_uri(secret: str, account: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=ISSUER)


def qr_svg(uri: str) -> str:
    """An inline SVG QR code of the provisioning URI (no external service ever sees the seed)."""
    import io

    import segno

    out = io.BytesIO()
    segno.make(uri, error="m").save(out, kind="svg", scale=4, border=2, xmldecl=False, svgns=True, dark="#1f2a24")
    return out.getvalue().decode("utf-8")


def normalize_code(code: str) -> str:
    return "".join(ch for ch in code.strip().lower() if ch.isalnum())


def matching_step(secret: str, code: str, now: datetime) -> int | None:
    """The time step ``code`` belongs to (within the window around ``now``), or None."""
    code = normalize_code(code)
    if len(code) != 6 or not code.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    current = totp.timecode(now)
    for step in range(current - VALID_WINDOW, current + VALID_WINDOW + 1):
        if secrets.compare_digest(totp.generate_otp(step), code):
            return step
    return None


def code_at(secret: str, when: datetime) -> str:
    """The TOTP code for ``when`` (tests and the demo helper)."""
    return pyotp.TOTP(secret).at(when)


# ---- persistence --------------------------------------------------------------------------------------
def active_factor(session: Session, user_id: uuid.UUID, *, for_update: bool = False) -> MfaFactor | None:
    """The user's open factor (confirmed or still pending confirmation)."""
    stmt = select(MfaFactor).where(MfaFactor.user_id == user_id, MfaFactor.disabled_at.is_(None))
    if for_update:
        stmt = stmt.with_for_update()
    return session.scalars(stmt).first()


def confirmed_factor(session: Session, user_id: uuid.UUID, *, for_update: bool = False) -> MfaFactor | None:
    factor = active_factor(session, user_id, for_update=for_update)
    return factor if factor is not None and factor.confirmed_at is not None else None


def verify_totp(factor: MfaFactor, code: str, now: datetime) -> bool:
    """Check a TOTP code and record its step (replays of that step or earlier are refused)."""
    step = matching_step(open_secret(factor), code, now)
    if step is None or (factor.last_used_step is not None and step <= factor.last_used_step):
        return False
    factor.last_used_step = step
    return True


def _recovery_hash(user_id: uuid.UUID, code: str) -> bytes:
    return keyed_hash("mfa_recovery", f"{user_id}:{normalize_code(code)}")


def new_recovery_codes(session: Session, factor: MfaFactor, now: datetime) -> list[str]:
    """Replace the factor's recovery codes with ten fresh ones; returns the plaintext (shown once)."""
    session.execute(
        update(MfaRecoveryCode)
        .where(MfaRecoveryCode.factor_id == factor.id, MfaRecoveryCode.used_at.is_(None))
        .values(used_at=now)
    )
    codes: list[str] = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        code = f"{raw[:5]}-{raw[5:]}"
        codes.append(code)
        session.add(
            MfaRecoveryCode(
                id=uuid.uuid7(), user_id=factor.user_id, factor_id=factor.id, code_hash=_recovery_hash(factor.user_id, code), created_at=now
            )
        )
    session.flush()
    return codes


def use_recovery_code(session: Session, factor: MfaFactor, code: str, now: datetime) -> bool:
    """Consume one unused recovery code (single use; the row lock serialises concurrent use)."""
    row = session.scalars(
        select(MfaRecoveryCode)
        .where(
            MfaRecoveryCode.factor_id == factor.id,
            MfaRecoveryCode.code_hash == _recovery_hash(factor.user_id, code),
            MfaRecoveryCode.used_at.is_(None),
        )
        .with_for_update()
    ).first()
    if row is None:
        return False
    row.used_at = now
    return True


def remaining_recovery_codes(session: Session, factor: MfaFactor) -> int:
    from sqlalchemy import func

    return int(
        session.scalar(
            select(func.count()).select_from(MfaRecoveryCode).where(
                MfaRecoveryCode.factor_id == factor.id, MfaRecoveryCode.used_at.is_(None)
            )
        )
        or 0
    )


def verify_any(session: Session, factor: MfaFactor, code: str, now: datetime) -> str | None:
    """TOTP first, then a recovery code. Returns ``"totp"``, ``"recovery_code"`` or None."""
    if verify_totp(factor, code, now):
        return "totp"
    if use_recovery_code(session, factor, code, now):
        return "recovery_code"
    return None


def disable(session: Session, factor: MfaFactor, *, now: datetime, by: uuid.UUID | None, reason: str) -> None:
    factor.disabled_at = now
    factor.disabled_by = by
    factor.disabled_reason = reason[:40]
    session.execute(
        update(MfaRecoveryCode)
        .where(MfaRecoveryCode.factor_id == factor.id, MfaRecoveryCode.used_at.is_(None))
        .values(used_at=now)
    )


# ---- policy -------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class MfaPolicy:
    required_for: str = "privileged"  # privileged | all


def privileged_keys() -> frozenset[str]:
    from app.registry import get_registry

    return frozenset(
        p.key for p in get_registry().permissions.values() if p.requires_mfa and p.module in PRIVILEGED_MODULES
    )


def requires_mfa(permissions: Mapping[str, Scope], policy: MfaPolicy) -> bool:
    """Whether a member with these effective permissions must use MFA at sign-in."""
    if policy.required_for == "all":
        return True
    keys = privileged_keys()
    return any(k in keys for k in permissions)


def policy_for(uow: UnitOfWork) -> MfaPolicy:
    """The company's ``security_policy`` setting (defaults to privileged members only)."""
    from app.platform.org.settings import read_security_policy

    return MfaPolicy(required_for=read_security_policy(uow).mfa_required_for)


def member_requires_mfa(uow: UnitOfWork, membership_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    from app.platform.identity.actors import load_access

    company_id = uow.actor.company_id
    if company_id is None:
        return False
    access = load_access(uow.session, company_id, membership_id, user_id, now=uow.now())
    return requires_mfa(access.permissions, policy_for(uow))
