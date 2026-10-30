/**
 * INTERIM(api-generate) hand-written mirrors of backend/app/platform/identity/schemas.py (platform-2). Replace with
 * the generated `components["schemas"][...]` types once the integrator regenerates schema.d.ts.
 */

export type Scope = "own" | "team" | "branch" | "company";
export type MemberStatus = "invited" | "active" | "suspended" | "deactivated";

export interface Capability {
  allowed: boolean;
  reason_code: string | null;
}

export interface RoleRef {
  key: string;
  name: string;
}

export interface UserListItem {
  user_id: string;
  membership_id: string;
  display_name: string;
  email: string | null;
  job_title: string | null;
  status: MemberStatus;
  roles: RoleRef[];
  mfa_enrolled: boolean;
  last_login_at: string | null;
}

export interface UserList {
  items: UserListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface InvitationView {
  id: string;
  user_id: string;
  membership_id: string;
  email: string;
  status: "open" | "accepted" | "revoked" | "expired";
  created_at: string;
  expires_at: string;
  send_count: number;
  last_sent_at: string;
  invited_by_name: string | null;
}

export interface Delivery {
  mode: "demo_outbox" | "email";
  label: string;
  manual_link: string | null;
  outbox_file: string | null;
}

export interface InvitationIssued {
  invitation: InvitationView;
  delivery: Delivery;
}

export interface PasswordResetIssued {
  user_id: string;
  expires_at: string;
  delivery: Delivery;
}

export interface OverrideView {
  id: string;
  permission_key: string;
  effect: "grant" | "revoke";
  scope: Scope | null;
  reason: string;
  expires_at: string | null;
  in_effect: boolean;
  created_at: string;
  created_by: string | null;
}

export interface OverrideList {
  user_id: string;
  membership_id: string;
  items: OverrideView[];
}

export interface UserDetail {
  user_id: string;
  membership_id: string;
  email: string | null;
  display_name: string;
  full_name: string | null;
  job_title: string | null;
  department: string | null;
  status: MemberStatus;
  roles: RoleRef[];
  branches: { id: string; code: string; name: string; is_head_office: boolean }[];
  default_branch_id: string | null;
  teams: { id: string; key: string; name: string; team_role: string }[];
  manager: { membership_id: string; display_name: string } | null;
  mfa_enrolled: boolean;
  mfa_required: boolean;
  last_login_at: string | null;
  joined_on: string | null;
  deactivated_at: string | null;
  deactivation_reason: string | null;
  invitations: InvitationView[];
  overrides: OverrideView[];
  version: number;
  is_self: boolean;
  capabilities: Record<
    "update" | "assign_roles" | "manage_overrides" | "deactivate" | "reactivate" | "reset_password" | "reset_mfa" | "end_sessions" | "invite",
    Capability
  >;
}

export interface PermissionInfo {
  key: string;
  module: string;
  resource: string;
  action: string;
  description: string;
  allowed_scopes: Scope[];
  delegable: boolean;
  requires_mfa: boolean;
  requires_recent_auth: boolean;
  field_guard: boolean;
  sensitive: boolean;
}

export interface PermissionCatalogue {
  items: PermissionInfo[];
}

export interface RoleSummary {
  id: string;
  key: string;
  name: string;
  description: string | null;
  kind: "system_template" | "custom";
  inherits: RoleRef | null;
  is_assignable: boolean;
  archived: boolean;
  member_count: number;
  grant_count: number;
  deny_count: number;
  version: number;
}

export interface RoleList {
  items: RoleSummary[];
}

export interface RoleEntryIn {
  key: string;
  effect: "grant" | "deny";
  scope: Scope | null;
}

export interface SourceView {
  kind: "role" | "inherited" | "employee_base" | "override_grant" | "override_revoke" | "role_deny" | "delegation";
  label: string;
  role_key: string | null;
  scope: Scope | null;
  expires_at: string | null;
}

export interface EffectiveKey {
  key: string;
  scope: Scope | null;
  sources: SourceView[];
}

export interface RoleDetail {
  role: RoleSummary;
  entries: RoleEntryIn[];
  chain: RoleRef[];
  effective: EffectiveKey[];
  capabilities: Record<"update" | "archive" | "inherit", Capability>;
}

export interface EffectiveAccess {
  subject: "member" | "role";
  user_id: string | null;
  display_name: string | null;
  role_keys: string[];
  membership_status: string | null;
  granted: EffectiveKey[];
  removed: EffectiveKey[];
  delegated: EffectiveKey[];
}

export interface AccessCheck {
  permission_key: string;
  allowed: boolean;
  scope: Scope | null;
  needed_scope: Scope;
  reasons: string[];
  sources: SourceView[];
}

export interface MfaStatus {
  enrolled: boolean;
  pending: boolean;
  confirmed_at: string | null;
  recovery_codes_remaining: number;
  required: boolean;
  session_verified: boolean;
}

export interface MfaEnrollment {
  factor_id: string;
  secret: string;
  otpauth_uri: string;
  qr_svg: string;
}

export interface MfaConfirmed {
  recovery_codes: string[];
  confirmed_at: string;
}

export interface ReauthResult {
  recent_auth_at: string;
  auth_strength: "password" | "mfa" | "demo_link";
}

export interface SessionListItem {
  id: string;
  auth_method: string;
  created_at: string;
  last_seen_at: string;
  idle_expires_at: string;
  absolute_expires_at: string;
  mfa_verified: boolean;
  current: boolean;
}

export interface SessionList {
  items: SessionListItem[];
}

export interface DelegationView {
  id: string;
  delegator_user_id: string;
  delegator_name: string;
  delegate_user_id: string;
  delegate_name: string;
  permission_keys: string[];
  include_approvals: boolean;
  starts_at: string;
  ends_at: string;
  reason: "leave" | "travel" | "workload" | "other";
  note: string | null;
  status: "scheduled" | "active" | "ended" | "cancelled";
  cancelled_at: string | null;
  version: number;
  capabilities: Record<"cancel", Capability>;
}

export interface DelegationList {
  items: DelegationView[];
  delegable_keys: string[];
}

export interface AbsenceView {
  id: string;
  user_id: string;
  display_name: string;
  kind: "leave" | "holiday" | "training" | "other";
  starts_on: string;
  ends_on: string;
  status: "requested" | "approved" | "rejected" | "cancelled";
  note: string | null;
  cover_user_id: string | null;
  cover_name: string | null;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_note: string | null;
  version: number;
  capabilities: Record<"decide" | "cancel", Capability>;
}

export interface AbsenceList {
  items: AbsenceView[];
}

export interface AccessRequestView {
  id: string;
  requester_user_id: string;
  requester_name: string;
  permission_key: string;
  scope: Scope;
  reason: string;
  duration_days: number;
  status: "pending" | "approved" | "rejected" | "withdrawn";
  decided_by_name: string | null;
  decided_at: string | null;
  decision_note: string | null;
  grant_expires_at: string | null;
  created_at: string;
  version: number;
  capabilities: Record<"decide" | "withdraw", Capability>;
}

export interface AccessRequestList {
  items: AccessRequestView[];
}
