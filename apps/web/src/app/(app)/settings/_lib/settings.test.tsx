import { describe, expect, it, vi } from "vitest";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { controlsWithoutVisibleFocus, nestedInteractive, renderWithQueries, seedQueryError, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { SettingsHub } from "@/features/settings/settings-hub";
import { AccessRequestsScreen, DelegationScreen, LeaveScreen } from "./people";
import { RoleDetailScreen, RoleListScreen, SimulatorScreen } from "./roles";
import { SecurityScreen } from "./security";
import { needsStepUp } from "./step-up";
import type { AccessRequestList, DelegationList, EffectiveAccess, MfaStatus, RoleDetail, RoleList, UserDetail, UserList } from "./types";
import { fieldErrors, keyLabel, problemText } from "./ui";
import { UserDetailScreen, UserListScreen, userListHref, userListStateFrom } from "./users";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/settings",
  useSearchParams: () => new URLSearchParams(),
}));

const USER = "0192a000-0000-7000-8000-00000000000b";
const ROLE = "0192a000-0000-7000-8000-0000000000e1";
const cap = (allowed: boolean, reason: string | null = null) => ({ allowed, reason_code: allowed ? null : (reason ?? "permission_denied") });
const problem = (status: number, code: string, extra: Record<string, unknown> = {}) =>
  new ProblemError({ title: code, status, code, detail: `${code} detail`, ...extra });

const admin = () =>
  testBootstrap({
    permissions: [
      { key: "identity.user.read", scope: "company" },
      { key: "identity.user.manage", scope: "company" },
      { key: "identity.role.read", scope: "company" },
      { key: "identity.role.manage", scope: "company" },
      { key: "identity.access_request.approve", scope: "company" },
      { key: "sales.quote.read", scope: "company" },
    ],
  });

const users: UserList = {
  items: [
    { user_id: USER, membership_id: "m1", display_name: "Meera Iyer", email: "meera@demo.test", job_title: "Sales", status: "active", roles: [{ key: "sales", name: "Sales" }], mfa_enrolled: false, last_login_at: null },
    { user_id: "u2", membership_id: "m2", display_name: "Old Hand (inactive)", email: null, job_title: null, status: "deactivated", roles: [], mfa_enrolled: true, last_login_at: "2026-10-01T05:00:00Z" },
  ],
  total: 2,
  limit: 25,
  offset: 0,
};

function detail(overrides: Partial<UserDetail> = {}): UserDetail {
  return {
    user_id: USER,
    membership_id: "m1",
    email: "meera@demo.test",
    display_name: "Meera Iyer",
    full_name: "Meera Iyer",
    job_title: "Sales",
    department: null,
    status: "active",
    roles: [{ key: "sales", name: "Sales" }],
    branches: [{ id: "b1", code: "HO", name: "Head office", is_head_office: true }],
    default_branch_id: "b1",
    teams: [],
    manager: null,
    mfa_enrolled: false,
    mfa_required: false,
    last_login_at: null,
    joined_on: null,
    deactivated_at: null,
    deactivation_reason: null,
    invitations: [],
    overrides: [{ id: "o1", permission_key: "sales.quote.export", effect: "revoke", scope: null, reason: "No exports", expires_at: null, in_effect: true, created_at: "2026-10-10T00:00:00Z", created_by: null }],
    version: 3,
    is_self: false,
    capabilities: {
      update: cap(true),
      assign_roles: cap(true),
      manage_overrides: cap(true),
      deactivate: cap(true),
      reactivate: cap(false, "invalid_transition"),
      reset_password: cap(true),
      reset_mfa: cap(true),
      end_sessions: cap(true),
      invite: cap(false),
    },
    ...overrides,
  };
}

describe("users", () => {
  it("parse and build list URLs (filters before paging)", () => {
    const state = userListStateFrom({ q: " meera ", status: "deactivated", role: "sales", offset: "25" });
    expect(state).toEqual({ q: "meera", status: "deactivated", role: "sales", offset: 25 });
    expect(userListStateFrom({ status: "nope", role: "Bad Role", offset: "-3" })).toEqual({ q: null, status: null, role: null, offset: 0 });
    expect(userListHref({ ...state, offset: 0 })).toBe("/settings/users?q=meera&status=deactivated&role=sales");
  });

  it("render the member table with statuses and the invite action", () => {
    const state = userListStateFrom({});
    const html = renderWithQueries(<UserListScreen state={state} />, (c) => {
      c.setQueryData(queryKeys.identity.users(state), users);
      c.setQueryData(queryKeys.identity.roles(), { items: [] });
    }, admin());
    const text = textOf(html);
    expect(text).toContain("Meera Iyer");
    expect(text).toContain("Old Hand (inactive)");
    expect(text).toContain("Invite someone");
    expect(text).toContain("Inactive");
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);
    expect(nestedInteractive(html)).toEqual([]);
  });

  it("show loading, empty, forbidden and error states", () => {
    const state = userListStateFrom({});
    expect(textOf(renderWithQueries(<UserListScreen state={state} />, () => undefined, admin()))).toMatch(/Loading/i);
    const empty = renderWithQueries(<UserListScreen state={state} />, (c) => c.setQueryData(queryKeys.identity.users(state), { ...users, items: [], total: 0 }), admin());
    expect(textOf(empty)).toContain("No one matches");
    const forbidden = renderWithQueries(<UserListScreen state={state} />, (c) => seedQueryError(c, queryKeys.identity.users(state), problem(403, "permission_denied")), admin());
    expect(textOf(forbidden)).not.toContain("Meera");
    expect(forbidden).toMatch(/user administration/);
    const failed = renderWithQueries(<UserListScreen state={state} />, (c) => seedQueryError(c, queryKeys.identity.users(state), problem(500, "internal")), admin());
    expect(textOf(failed)).toMatch(/Try again|Retry/i);
  });

  it("show only the controls the server allows on a member", () => {
    const allowed = textOf(renderWithQueries(<UserDetailScreen userId={USER} />, (c) => c.setQueryData(queryKeys.identity.user(USER), detail()), admin()));
    expect(allowed).toContain("Deactivate");
    expect(allowed).toContain("Change roles");
    expect(allowed).toContain("Send a password reset link");
    expect(allowed).toContain("Add grant or revoke");
    expect(allowed).toContain("No exports");
    expect(allowed).not.toContain("Reactivate");

    const self = detail({
      is_self: true,
      capabilities: { ...detail().capabilities, deactivate: cap(false, "self_access_change"), assign_roles: cap(false, "self_access_change"), manage_overrides: cap(false, "self_access_change"), reset_password: cap(false) },
    });
    const own = textOf(renderWithQueries(<UserDetailScreen userId={USER} />, (c) => c.setQueryData(queryKeys.identity.user(USER), self), admin()));
    expect(own).not.toContain("Deactivate");
    expect(own).not.toContain("Change roles");
    expect(own).toContain("You cannot change your own permissions");

    const inactive = detail({ status: "deactivated", display_name: "Meera Iyer (inactive)", deactivation_reason: "Left", capabilities: { ...detail().capabilities, deactivate: cap(false), reactivate: cap(true) } });
    const back = textOf(renderWithQueries(<UserDetailScreen userId={USER} />, (c) => c.setQueryData(queryKeys.identity.user(USER), inactive), admin()));
    expect(back).toContain("Reactivate");
    expect(back).toContain("Left");
  });

  it("show a not-found member without data", () => {
    const html = renderWithQueries(<UserDetailScreen userId={USER} />, (c) => seedQueryError(c, queryKeys.identity.user(USER), problem(404, "not_found")), admin());
    expect(textOf(html)).not.toContain("meera@demo.test");
  });
});

const roles: RoleList = {
  items: [
    { id: ROLE, key: "senior_sales", name: "Senior sales", description: null, kind: "custom", inherits: { key: "sales", name: "Sales" }, is_assignable: true, archived: false, member_count: 2, grant_count: 1, deny_count: 1, version: 2 },
    { id: "r2", key: "sales", name: "Sales", description: null, kind: "system_template", inherits: null, is_assignable: true, archived: false, member_count: 5, grant_count: 40, deny_count: 0, version: 1 },
  ],
};

const roleDetail: RoleDetail = {
  role: roles.items[0]!,
  entries: [
    { key: "sales.quote.read", effect: "grant", scope: "company" },
    { key: "sales.quote.export", effect: "deny", scope: null },
  ],
  chain: [
    { key: "sales", name: "Sales" },
    { key: "senior_sales", name: "Senior sales" },
  ],
  effective: [{ key: "sales.quote.read", scope: "company", sources: [{ kind: "role", label: "Role senior_sales", role_key: "senior_sales", scope: "company", expires_at: null }] }],
  capabilities: { update: cap(true), archive: cap(false, "role_in_use"), inherit: cap(true) },
};

describe("roles", () => {
  it("list system and custom roles, with create only for role managers", () => {
    const html = renderWithQueries(<RoleListScreen />, (c) => c.setQueryData(queryKeys.identity.roles(), roles), admin());
    expect(textOf(html)).toContain("Senior sales");
    expect(textOf(html)).toContain("New custom role");
    const reader = testBootstrap({ permissions: [{ key: "identity.role.read", scope: "company" }] });
    expect(textOf(renderWithQueries(<RoleListScreen />, (c) => c.setQueryData(queryKeys.identity.roles(), roles), reader))).not.toContain("New custom role");
  });

  it("explain inheritance and denies; archive is disabled with its reason while assigned", () => {
    const html = renderWithQueries(<RoleDetailScreen roleId={ROLE} />, (c) => c.setQueryData(queryKeys.identity.role(ROLE), roleDetail), admin());
    const text = textOf(html);
    expect(text).toContain("Sales → Senior sales");
    expect(text).toContain("Denies: sales · quote · export");
    expect(text).toContain("Unassign it first");
    expect(html).toMatch(/disabled/);
  });

  it("simulate a member: granted, removed with reasons, delegated", () => {
    const effective: EffectiveAccess = {
      subject: "member",
      user_id: USER,
      display_name: "Meera Iyer",
      role_keys: ["sales"],
      membership_status: "active",
      granted: [{ key: "sales.quote.read", scope: "own", sources: [{ kind: "role", label: "Role Sales", role_key: "sales", scope: "own", expires_at: null }] }],
      removed: [{ key: "sales.quote.export", scope: null, sources: [{ kind: "override_revoke", label: "Personal revoke: No exports", role_key: null, scope: null, expires_at: null }] }],
      delegated: [],
    };
    const html = renderWithQueries(<SimulatorScreen userId={USER} roleId={null} />, (c) => {
      c.setQueryData(queryKeys.identity.effective({ userId: USER, roleId: null }), effective);
      c.setQueryData(queryKeys.identity.roles(), roles);
    }, admin());
    const text = textOf(html);
    expect(text).toContain("Personal revoke: No exports");
    expect(text).toContain("Why or why not?");
    expect(textOf(renderWithQueries(<SimulatorScreen userId={null} roleId={null} />, () => undefined, admin()))).toContain("Choose someone");
  });
});

describe("security and self-service", () => {
  const mfa = (o: Partial<MfaStatus> = {}): MfaStatus => ({ enrolled: true, pending: false, confirmed_at: "2026-10-10T04:00:00Z", recovery_codes_remaining: 8, required: true, session_verified: true, ...o });

  it("never offer to remove a required authenticator; offer set-up when there is none", () => {
    const required = textOf(renderWithQueries(<SecurityScreen />, (c) => {
      c.setQueryData(queryKeys.identity.mfa(), mfa());
      c.setQueryData(queryKeys.identity.sessions(), { items: [] });
    }));
    expect(required).toContain("Your role requires it");
    expect(required).toContain("8 recovery codes left");
    expect(required).not.toMatch(/\bRemove\b/);
    const optional = textOf(renderWithQueries(<SecurityScreen />, (c) => {
      c.setQueryData(queryKeys.identity.mfa(), mfa({ required: false }));
      c.setQueryData(queryKeys.identity.sessions(), { items: [] });
    }));
    expect(optional).toMatch(/\bRemove\b/);
    const none = textOf(renderWithQueries(<SecurityScreen />, (c) => {
      c.setQueryData(queryKeys.identity.mfa(), mfa({ enrolled: false, confirmed_at: null, required: false }));
      c.setQueryData(queryKeys.identity.sessions(), { items: [] });
    }));
    expect(none).toContain("Set up an authenticator app");
  });

  it("list delegations with server-decided cancel controls", () => {
    const list: DelegationList = {
      delegable_keys: ["sales.quote.read"],
      items: [
        { id: "d1", delegator_user_id: "a", delegator_name: "Meera Iyer", delegate_user_id: "b", delegate_name: "Neha Joshi", permission_keys: ["sales.quote.read"], include_approvals: false, starts_at: "2026-10-12T03:25:00Z", ends_at: "2026-10-15T03:25:00Z", reason: "leave", note: null, status: "active", cancelled_at: null, version: 1, capabilities: { cancel: cap(true) } },
        { id: "d2", delegator_user_id: "c", delegator_name: "Sahil Mehta", delegate_user_id: "a", delegate_name: "Meera Iyer", permission_keys: ["sales.quote.read"], include_approvals: false, starts_at: "2026-10-12T03:25:00Z", ends_at: "2026-10-15T03:25:00Z", reason: "travel", note: null, status: "active", cancelled_at: null, version: 1, capabilities: { cancel: cap(false) } },
      ],
    };
    const text = textOf(renderWithQueries(<DelegationScreen />, (c) => c.setQueryData(queryKeys.identity.delegations("mine"), list)));
    expect(text).toContain("Meera Iyer → Neha Joshi");
    expect(text.match(/\bCancel\b/g)?.length).toBe(1);
    const empty = textOf(renderWithQueries(<DelegationScreen />, (c) => c.setQueryData(queryKeys.identity.delegations("mine"), { items: [], delegable_keys: [] })));
    expect(empty).toContain("No delegations");
  });

  it("show leave with approve only where allowed, and a 403 as permission denied", () => {
    const html = renderWithQueries(<LeaveScreen />, (c) => {
      c.setQueryData(queryKeys.identity.absences("mine"), { items: [] });
      c.setQueryData(queryKeys.identity.absences("team"), {
        items: [{ id: "a1", user_id: "x", display_name: "Neha Joshi", kind: "leave", starts_on: "2026-10-15", ends_on: "2026-10-17", status: "requested", note: null, cover_user_id: null, cover_name: "Meera Iyer", decided_by_name: null, decided_at: null, decision_note: null, version: 1, capabilities: { decide: cap(true), cancel: cap(true) } }],
      });
    });
    const text = textOf(html);
    expect(text).toContain("To approve");
    expect(text).toContain("Approve");
    expect(text).toContain("No leave recorded");
    const denied = renderWithQueries(<LeaveScreen />, (c) => seedQueryError(c, queryKeys.identity.absences("mine"), problem(403, "permission_denied")));
    expect(textOf(denied)).not.toContain("Neha");
  });

  it("show access requests; the decide section only for approvers", () => {
    const list: AccessRequestList = {
      items: [{ id: "q1", requester_user_id: "x", requester_name: "Meera Iyer", permission_key: "pricing.cost.read", scope: "company", reason: "Margin review", duration_days: 7, status: "pending", decided_by_name: null, decided_at: null, decision_note: null, grant_expires_at: null, created_at: "2026-10-12T03:00:00Z", version: 1, capabilities: { decide: cap(true), withdraw: cap(false) } }],
    };
    const approver = textOf(renderWithQueries(<AccessRequestsScreen />, (c) => {
      c.setQueryData(queryKeys.identity.accessRequests("mine"), { items: [] });
      c.setQueryData(queryKeys.identity.accessRequests("all"), list);
    }, admin()));
    expect(approver).toContain("Requests to decide");
    expect(approver).toContain("Grant");
    const member = textOf(renderWithQueries(<AccessRequestsScreen />, (c) => c.setQueryData(queryKeys.identity.accessRequests("mine"), list)));
    expect(member).not.toContain("Requests to decide");
  });

  it("show administration on the hub only to holders of identity keys", () => {
    const full = textOf(renderWithQueries(<SettingsHub />, () => undefined, admin()));
    expect(full).toContain("Users");
    expect(full).toContain("Roles");
    const member = textOf(renderWithQueries(<SettingsHub />, () => undefined));
    expect(member).not.toContain("Users");
    expect(member).toContain("Security");
  });
});

describe("helpers", () => {
  it("recognise step-up problems", () => {
    expect(needsStepUp(problem(401, "mfa_required"))).toBe("code");
    expect(needsStepUp(problem(401, "reauth_required"))).toBe("password");
    expect(needsStepUp(problem(401, "session_expired"))).toBeNull();
  });

  it("map 422 field errors and problem text", () => {
    const err = problem(422, "validation_failed", { errors: [{ loc: ["body", "email"], msg: "already used", code: "dup" }, { loc: ["body", "entries", 0, "scope"], msg: "bad scope", code: "x" }] });
    expect(fieldErrors(err)).toEqual({ email: "already used", scope: "bad scope" });
    expect(problemText(problem(409, "last_admin"))).toBe("last_admin detail");
    expect(problemText(new Error("step_up_cancelled"))).toMatch(/cancelled/);
    expect(keyLabel("sales.quote_price.override")).toBe("sales · quote price · override");
  });
});
