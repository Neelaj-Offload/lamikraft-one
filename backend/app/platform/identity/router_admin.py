"""Identity administration API (Slice 2): members, roles, the permission catalogue and the role simulator."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor
from app.platform.identity import roles_admin, user_admin
from app.platform.identity.schemas import (
    AccessCheck,
    BranchesPut,
    DeactivateBody,
    EffectiveAccess,
    PermissionCatalogue,
    RoleCreate,
    RoleDetail,
    RoleList,
    RolesPut,
    RoleUpdate,
    UserDetail,
    UserList,
    UserUpdate,
)

router = APIRouter(prefix="/identity", tags=["identity"])

_STEP_UP = {401: {"description": "mfa_required or reauth_required: confirm with the authenticator or password, then retry"}}


# ---- members ------------------------------------------------------------------------------------------------
@router.get(
    "/users",
    openapi_extra=requires("identity.user.read", "identity.user.manage"),
    operation_id="identity_list_users",
    response_model=UserList,
)
def list_users(
    actor: Actor,
    q: str | None = Query(default=None, max_length=100),
    status: Literal["invited", "active", "suspended", "deactivated"] | None = None,
    role: str | None = Query(default=None, max_length=41),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> UserList:
    return user_admin.list_users(actor, q=q, status=status, role_key=role, limit=limit, offset=offset)


@router.get(
    "/users/{user_id}",
    openapi_extra=requires("identity.user.read", "identity.user.manage"),
    operation_id="identity_get_user",
    response_model=UserDetail,
)
def get_user(user_id: uuid.UUID, actor: Actor) -> UserDetail:
    return user_admin.get_user(actor, user_id)


@router.patch(
    "/users/{user_id}",
    openapi_extra=requires("identity.user.manage"),
    operation_id="identity_update_user",
    response_model=UserDetail,
    responses={409: {"description": "version_conflict"}, **_STEP_UP},
)
def update_user(user_id: uuid.UUID, body: UserUpdate, actor: Actor) -> UserDetail:
    return user_admin.update_user(actor, user_id, body)


@router.put(
    "/users/{user_id}/roles",
    openapi_extra=requires("identity.role.manage"),
    operation_id="identity_update_user_roles",
    response_model=UserDetail,
    responses={409: {"description": "last_admin"}, **_STEP_UP},
)
def set_user_roles(user_id: uuid.UUID, body: RolesPut, actor: Actor) -> UserDetail:
    return user_admin.set_roles(actor, user_id, body.role_keys)


@router.put(
    "/users/{user_id}/branches",
    openapi_extra=requires("identity.user.manage"),
    operation_id="identity_update_user_branches",
    response_model=UserDetail,
    responses=_STEP_UP,
)
def set_user_branches(user_id: uuid.UUID, body: BranchesPut, actor: Actor) -> UserDetail:
    return user_admin.set_branches(actor, user_id, body.branch_ids)


@router.post(
    "/users/{user_id}/deactivation",
    openapi_extra=requires("identity.user.manage"),
    operation_id="identity_archive_user",
    response_model=UserDetail,
    responses={409: {"description": "last_admin or invalid_transition"}, **_STEP_UP},
)
def deactivate_user(user_id: uuid.UUID, body: DeactivateBody, actor: Actor) -> UserDetail:
    """Deactivate (never delete): sessions and open links end at once; attribution stays ("Name (inactive)")."""
    return user_admin.deactivate(actor, user_id, body)


@router.post(
    "/users/{user_id}/reactivation",
    openapi_extra=requires("identity.user.manage"),
    operation_id="identity_transition_user_reactivation",
    response_model=UserDetail,
    responses=_STEP_UP,
)
def reactivate_user(user_id: uuid.UUID, actor: Actor) -> UserDetail:
    return user_admin.reactivate(actor, user_id)


# ---- catalogue and roles ------------------------------------------------------------------------------------
@router.get(
    "/permissions",
    openapi_extra=requires("identity.role.read", "identity.role.manage"),
    operation_id="identity_list_permissions",
    response_model=PermissionCatalogue,
)
def list_permissions(actor: Actor) -> PermissionCatalogue:
    return roles_admin.permission_catalogue(actor)


@router.get(
    "/roles",
    openapi_extra=requires("identity.role.read", "identity.role.manage"),
    operation_id="identity_list_roles",
    response_model=RoleList,
)
def list_roles(actor: Actor, include_archived: bool = False) -> RoleList:
    return roles_admin.list_roles(actor, include_archived=include_archived)


@router.post(
    "/roles",
    status_code=201,
    openapi_extra=requires("identity.role.manage"),
    operation_id="identity_create_role",
    response_model=RoleDetail,
    responses={409: {"description": "duplicate_key"}, **_STEP_UP},
)
def create_role(body: RoleCreate, actor: Actor) -> RoleDetail:
    return roles_admin.create_role(actor, body)


@router.get(
    "/roles/{role_id}",
    openapi_extra=requires("identity.role.read", "identity.role.manage"),
    operation_id="identity_get_role",
    response_model=RoleDetail,
)
def get_role(role_id: uuid.UUID, actor: Actor) -> RoleDetail:
    return roles_admin.get_role(actor, role_id)


@router.patch(
    "/roles/{role_id}",
    openapi_extra=requires("identity.role.manage"),
    operation_id="identity_update_role",
    response_model=RoleDetail,
    responses={409: {"description": "role_immutable or version_conflict"}, **_STEP_UP},
)
def update_role(role_id: uuid.UUID, body: RoleUpdate, actor: Actor) -> RoleDetail:
    return roles_admin.update_role(actor, role_id, body)


@router.post(
    "/roles/{role_id}/archive",
    openapi_extra=requires("identity.role.manage"),
    operation_id="identity_archive_role",
    response_model=RoleDetail,
    responses={409: {"description": "role_in_use or role_immutable"}, **_STEP_UP},
)
def archive_role(role_id: uuid.UUID, actor: Actor) -> RoleDetail:
    return roles_admin.archive_role(actor, role_id)


# ---- simulator ------------------------------------------------------------------------------------------------
@router.get(
    "/access/effective",
    openapi_extra=requires("identity.user.read", "identity.role.read", "identity.role.manage"),
    operation_id="identity_get_effective_access",
    response_model=EffectiveAccess,
)
def effective_access(actor: Actor, user_id: uuid.UUID | None = None, role_id: uuid.UUID | None = None) -> EffectiveAccess:
    """What a member (or a role on its own) can do, with the source of every permission, what was removed and why,
    and delegated reach."""
    return roles_admin.effective_access(actor, user_id=user_id, role_id=role_id)


@router.get(
    "/access/check",
    openapi_extra=requires("identity.user.read", "identity.role.read", "identity.role.manage"),
    operation_id="identity_get_access_check",
    response_model=AccessCheck,
)
def access_check(
    actor: Actor,
    user_id: uuid.UUID,
    permission_key: str = Query(min_length=5, max_length=120),
    scope: Literal["own", "team", "branch", "company"] = "own",
) -> AccessCheck:
    """Can this member use the permission at that scope? Every reason, including the step-up it needs."""
    return roles_admin.check_access(actor, user_id=user_id, permission_key=permission_key, scope=scope)
