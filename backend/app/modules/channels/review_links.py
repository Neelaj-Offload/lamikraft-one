"""Review links: ``/r/{token}`` carries a 32-byte random token (stored as its SHA-256), valid 15 minutes, single
use when it leads to a decision, and bound to one user. The token is a reference, not authentication: the page
requires a web sign-in as the bound user, then redirects to the canonical screen."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta

from sqlalchemy import select

from app.core.errors import AppError, Forbidden, NotFound
from app.modules.channels.models import ReviewLink
from app.modules.channels.schemas import ReviewLinkResolved, ReviewPurpose
from app.platform.uow import UnitOfWork

TTL = timedelta(minutes=15)
PATH_PREFIX = "/r/"


class ReviewLinkExpired(AppError):
    status, code, title = 410, "review_link_expired", "This link has expired"


class ReviewLinkUsed(AppError):
    status, code, title = 410, "review_link_used", "This link was already used"


def _hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def create(
    uow: UnitOfWork, *, user_id: uuid.UUID, target_type: str, target_id: uuid.UUID, redirect_path: str,
    proposal_id: uuid.UUID | None = None, purpose: ReviewPurpose = ReviewPurpose.VIEW,
) -> tuple[ReviewLink, str]:
    """(row, token). The token is returned once and never stored."""
    if not redirect_path.startswith("/") or redirect_path.startswith("//"):
        raise ValueError("redirect_path must be an app-relative path")
    token = secrets.token_urlsafe(32)
    now = uow.now()
    row = ReviewLink(
        id=uuid.uuid7(), user_id=user_id, target_type=target_type[:80], target_id=target_id, proposal_id=proposal_id,
        purpose=purpose.value, token_hash=_hash(token), redirect_path=redirect_path[:300], expires_at=now + TTL,
        max_uses=1 if purpose == ReviewPurpose.DECIDE else 20, uses=0,
    )
    uow.add(row)
    uow.flush()
    return row, token


def url_path(token: str) -> str:
    return f"{PATH_PREFIX}{token}"


def resolve(uow: UnitOfWork, token: str) -> ReviewLinkResolved:
    """Validate and consume one use as the signed-in actor; 404 for an unknown token, 403 for another user,
    410 when expired or exhausted."""
    actor = uow.actor
    if actor.user_id is None:
        raise Forbidden(code="permission_denied")
    if not token or len(token) > 128:
        raise NotFound(code="not_found", resource_type="channels.review_link")
    row = uow.session.scalars(
        select(ReviewLink).where(ReviewLink.company_id == actor.company_id, ReviewLink.token_hash == _hash(token)).with_for_update()
    ).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="channels.review_link")
    if row.user_id != actor.user_id:
        raise Forbidden("This link was issued to another user", code="review_link_wrong_user")
    now = uow.now()
    if row.expires_at <= now:
        raise ReviewLinkExpired()
    if row.uses >= row.max_uses:
        raise ReviewLinkUsed()
    row.uses += 1
    row.last_used_at = now
    uow.audit("channels.review_link.resolved", resource_type=row.target_type, resource_id=row.target_id, details={"purpose": row.purpose})
    return ReviewLinkResolved(
        redirect_path=row.redirect_path, target_type=row.target_type, target_id=row.target_id, proposal_id=row.proposal_id,
        purpose=row.purpose,  # type: ignore[arg-type]
    )


__all__ = ["PATH_PREFIX", "TTL", "ReviewLinkExpired", "ReviewLinkUsed", "create", "resolve", "url_path"]
