/**
 * Settings area API calls (platform-2: members, roles, simulator, security, delegation, leave, access requests).
 *
 * INTERIM(api-generate): these endpoints are new in this lane, so the calls go through `requestUntyped` with the
 * hand-written types in ./types.ts; replace with the typed `api.GET(...)` once the integrator regenerates the
 * schema. Every call is same-origin and cookie-authenticated; CSRF is added by the client middleware.
 */

import { api, requestUntyped } from "@/lib/api/client";
import type {
  AbsenceList,
  AbsenceView,
  AccessCheck,
  AccessRequestList,
  AccessRequestView,
  DelegationList,
  DelegationView,
  EffectiveAccess,
  InvitationIssued,
  InvitationView,
  MfaConfirmed,
  MfaEnrollment,
  MfaStatus,
  OverrideList,
  OverrideView,
  PasswordResetIssued,
  PermissionCatalogue,
  ReauthResult,
  RoleDetail,
  RoleEntryIn,
  RoleList,
  SessionList,
  UserDetail,
  UserList,
} from "./types";

const I = "/api/v1/identity";

export interface UserListParams {
  q: string | null;
  status: string | null;
  role: string | null;
  offset: number;
}

export const USERS_PAGE_SIZE = 25;

export const fetchUsers = (p: UserListParams, signal?: AbortSignal) =>
  requestUntyped<UserList>(api, "get", `${I}/users`, { params: { query: { q: p.q, status: p.status, role: p.role, offset: p.offset, limit: USERS_PAGE_SIZE } }, signal });
export const fetchUser = (userId: string, signal?: AbortSignal) => requestUntyped<UserDetail>(api, "get", `${I}/users/${userId}`, { signal });
export const updateUser = (userId: string, body: Record<string, unknown>) => requestUntyped<UserDetail>(api, "patch", `${I}/users/${userId}`, { body });
export const setUserRoles = (userId: string, roleKeys: string[]) =>
  requestUntyped<UserDetail>(api, "put", `${I}/users/${userId}/roles`, { body: { role_keys: roleKeys } });
export const deactivateUser = (userId: string, reason: string, reassignTo: string | null) =>
  requestUntyped<UserDetail>(api, "post", `${I}/users/${userId}/deactivation`, { body: { reason, reassign_to_user_id: reassignTo } });
export const reactivateUser = (userId: string) => requestUntyped<UserDetail>(api, "post", `${I}/users/${userId}/reactivation`);
export const issuePasswordReset = (userId: string) => requestUntyped<PasswordResetIssued>(api, "post", `${I}/users/${userId}/password-reset`);
export const resetMemberMfa = (userId: string, reason: string) => requestUntyped<void>(api, "delete", `${I}/users/${userId}/mfa`, { body: { reason } });
export const endMemberSessions = (userId: string) => requestUntyped<{ revoked: number }>(api, "delete", `${I}/users/${userId}/sessions`);

export const fetchOverrides = (userId: string, signal?: AbortSignal) =>
  requestUntyped<OverrideList>(api, "get", `${I}/users/${userId}/permission-overrides`, { signal });
export const putOverride = (userId: string, key: string, body: { effect: "grant" | "revoke"; scope?: string | null; reason: string; expires_at?: string | null }) =>
  requestUntyped<OverrideView>(api, "put", `${I}/users/${userId}/permission-overrides/${key}`, { body });
export const deleteOverride = (userId: string, key: string) => requestUntyped<void>(api, "delete", `${I}/users/${userId}/permission-overrides/${key}`);

export const invite = (body: Record<string, unknown>) => requestUntyped<InvitationIssued>(api, "post", `${I}/invitations`, { body });
export const reissueInvitation = (id: string) => requestUntyped<InvitationIssued>(api, "post", `${I}/invitations/${id}/reissue`);
export const revokeInvitation = (id: string) => requestUntyped<InvitationView>(api, "delete", `${I}/invitations/${id}`);

export const fetchRoles = (signal?: AbortSignal) => requestUntyped<RoleList>(api, "get", `${I}/roles`, { signal });
export const fetchRole = (roleId: string, signal?: AbortSignal) => requestUntyped<RoleDetail>(api, "get", `${I}/roles/${roleId}`, { signal });
export const fetchCatalogue = (signal?: AbortSignal) => requestUntyped<PermissionCatalogue>(api, "get", `${I}/permissions`, { signal });
export const createRole = (body: { key: string; name: string; description: string | null; inherits_role_id: string | null; entries: RoleEntryIn[] }) =>
  requestUntyped<RoleDetail>(api, "post", `${I}/roles`, { body });
export const updateRole = (roleId: string, body: Record<string, unknown>) => requestUntyped<RoleDetail>(api, "patch", `${I}/roles/${roleId}`, { body });
export const archiveRole = (roleId: string) => requestUntyped<RoleDetail>(api, "post", `${I}/roles/${roleId}/archive`);
export const fetchEffective = (subject: { userId?: string | null; roleId?: string | null }, signal?: AbortSignal) =>
  requestUntyped<EffectiveAccess>(api, "get", `${I}/access/effective`, { params: { query: { user_id: subject.userId, role_id: subject.roleId } }, signal });
export const fetchAccessCheck = (userId: string, key: string, scope: string, signal?: AbortSignal) =>
  requestUntyped<AccessCheck>(api, "get", `${I}/access/check`, { params: { query: { user_id: userId, permission_key: key, scope } }, signal });

export const fetchMfa = (signal?: AbortSignal) => requestUntyped<MfaStatus>(api, "get", `${I}/me/mfa`, { signal });
export const startTotp = () => requestUntyped<MfaEnrollment>(api, "post", `${I}/me/mfa/totp`);
export const confirmTotp = (code: string) => requestUntyped<MfaConfirmed>(api, "post", `${I}/me/mfa/totp/confirmation`, { body: { code } });
export const removeTotp = (code: string) => requestUntyped<MfaStatus>(api, "delete", `${I}/me/mfa/totp`, { body: { code } });
export const regenerateCodes = (code: string) => requestUntyped<{ recovery_codes: string[] }>(api, "post", `${I}/me/mfa/recovery-codes`, { body: { code } });
export const reauthenticate = (body: { password?: string; code?: string }) => requestUntyped<ReauthResult>(api, "post", `${I}/session/reauthentication`, { body });
export const fetchMySessions = (signal?: AbortSignal) => requestUntyped<SessionList>(api, "get", `${I}/me/sessions`, { signal });
export const endMySession = (id: string) => requestUntyped<void>(api, "delete", `${I}/me/sessions/${id}`);
export const endMyOtherSessions = () => requestUntyped<{ revoked: number }>(api, "delete", `${I}/me/sessions`);
export const changePassword = (current: string, next: string) =>
  requestUntyped<unknown>(api, "post", `${I}/me/password`, { body: { current_password: current, new_password: next } });

export const fetchDelegations = (scope: "mine" | "all", signal?: AbortSignal) =>
  requestUntyped<DelegationList>(api, "get", `${I}/delegations`, { params: { query: { scope } }, signal });
export const createDelegation = (body: Record<string, unknown>) => requestUntyped<DelegationView>(api, "post", `${I}/delegations`, { body });
export const cancelDelegation = (id: string) => requestUntyped<DelegationView>(api, "post", `${I}/delegations/${id}/cancel`);

export const fetchAbsences = (scope: "mine" | "team", signal?: AbortSignal) =>
  requestUntyped<AbsenceList>(api, "get", `${I}/absences`, { params: { query: { scope } }, signal });
export const requestAbsence = (body: Record<string, unknown>) => requestUntyped<AbsenceView>(api, "post", `${I}/absences`, { body });
export const decideAbsence = (id: string, body: { expected_version: number; decision: "approve" | "reject"; note?: string | null }) =>
  requestUntyped<AbsenceView>(api, "post", `${I}/absences/${id}/decision`, { body });
export const cancelAbsence = (id: string) => requestUntyped<AbsenceView>(api, "post", `${I}/absences/${id}/cancel`);

export const fetchAccessRequests = (scope: "mine" | "all", signal?: AbortSignal) =>
  requestUntyped<AccessRequestList>(api, "get", `${I}/access-requests`, { params: { query: { scope } }, signal });
export const submitAccessRequest = (body: Record<string, unknown>) => requestUntyped<AccessRequestView>(api, "post", `${I}/access-requests`, { body });
export const decideAccessRequest = (id: string, body: { expected_version: number; decision: "approve" | "reject"; note?: string | null }) =>
  requestUntyped<AccessRequestView>(api, "post", `${I}/access-requests/${id}/decision`, { body });
export const withdrawAccessRequest = (id: string) => requestUntyped<AccessRequestView>(api, "post", `${I}/access-requests/${id}/withdrawal`);
