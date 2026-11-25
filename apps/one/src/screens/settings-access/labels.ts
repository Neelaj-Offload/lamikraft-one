import type { Route } from "next";
import type { Scope } from "@/app/(app)/settings/_lib/types";
import { isNetworkError, isProblemError } from "@/lib/api/errors";
import type { Crumb } from "~/shell/page";
import type { Tone } from "~/ui";

/** Words, tones and links shared by the people-and-access screens. */

export const SETTINGS_CRUMB: Crumb = { label: "Settings", href: "/settings" as Route };
export const USERS_CRUMB: Crumb = { label: "People", href: "/settings/users" as Route };
export const ROLES_CRUMB: Crumb = { label: "Roles", href: "/settings/roles" as Route };

export const userHref = (userId: string, view?: string): Route =>
  (view && view !== "overview" ? `/settings/users/${encodeURIComponent(userId)}?view=${view}` : `/settings/users/${encodeURIComponent(userId)}`) as Route;

export const roleHref = (roleId: string, view?: string): Route =>
  (view && view !== "overview" ? `/settings/roles/${encodeURIComponent(roleId)}?view=${view}` : `/settings/roles/${encodeURIComponent(roleId)}`) as Route;

export function simulateHref(subject: { user?: string | null; role?: string | null }): Route {
  const params = new URLSearchParams();
  if (subject.user) params.set("user", subject.user);
  if (subject.role) params.set("role", subject.role);
  const query = params.toString();
  return (query ? `/settings/roles/simulate?${query}` : "/settings/roles/simulate") as Route;
}

// ---- record views (the `?view=` of a person and of a role) ----------------------------------------

export const USER_VIEWS = ["overview", "access", "sign-in"] as const;
export type UserView = (typeof USER_VIEWS)[number];

export const ROLE_VIEWS = ["overview", "permissions"] as const;
export type RoleView = (typeof ROLE_VIEWS)[number];

const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

export function userViewFrom(value: string | string[] | undefined): UserView {
  return USER_VIEWS.find((view) => view === first(value)) ?? "overview";
}

export function roleViewFrom(value: string | string[] | undefined): RoleView {
  return ROLE_VIEWS.find((view) => view === first(value)) ?? "overview";
}

// ---- statuses ------------------------------------------------------------------------------------

export const MEMBER_LABEL: Record<string, string> = { active: "Active", invited: "Invited", suspended: "Suspended", deactivated: "Inactive" };
export const MEMBER_TONE: Record<string, Tone> = { active: "leaf", invited: "cobalt", suspended: "amber", deactivated: "neutral" };

/** One vocabulary for requests, leave and delegations. */
export const REQUEST_LABEL: Record<string, string> = {
  pending: "Waiting",
  requested: "Waiting",
  approved: "Approved",
  active: "Active",
  scheduled: "Scheduled",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
  cancelled: "Cancelled",
  ended: "Ended",
};
export const REQUEST_TONE: Record<string, Tone> = {
  pending: "amber",
  requested: "amber",
  approved: "leaf",
  active: "leaf",
  scheduled: "cobalt",
  rejected: "ember",
  withdrawn: "neutral",
  cancelled: "neutral",
  ended: "neutral",
};

export const humanise = (value: string): string => {
  const text = value.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
};

// ---- permissions ---------------------------------------------------------------------------------

export const SCOPES: readonly Scope[] = ["own", "team", "branch", "company"];
export const SCOPE_LABEL: Record<string, string> = { own: "Own records", team: "Team", branch: "Branch", company: "Whole company" };
export const scopeOptions = (scopes: readonly Scope[] = SCOPES) => scopes.map((scope) => ({ value: scope, label: SCOPE_LABEL[scope] ?? scope }));
export const scopeFrom = (value: string, fallback: Scope): Scope => SCOPES.find((scope) => scope === value) ?? fallback;

/** A permission key in words: `sales.quote.export` reads "Sales · quote · export". */
export function keyLabel(key: string): string {
  const text = key
    .split(".")
    .map((part) => part.replace(/_/g, " "))
    .join(" · ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export const DELEGATION_REASONS = [
  { value: "leave", label: "Leave" },
  { value: "travel", label: "Travel" },
  { value: "workload", label: "Workload" },
  { value: "other", label: "Other" },
] as const;

// ---- failed commands -----------------------------------------------------------------------------

/** Thrown by the step-up dialog when the person closes it instead of confirming. */
export const STEP_UP_CANCELLED = "step_up_cancelled";

export const isStepUpCancelled = (error: unknown): boolean => error instanceof Error && error.message === STEP_UP_CANCELLED;

/** One sentence for a failed command: the server's own words when it sent some. */
export function problemText(error: unknown): string {
  if (isProblemError(error)) return error.detail || error.title;
  if (isStepUpCancelled(error)) return "Nothing changed. You closed the confirmation before it finished.";
  if (isNetworkError(error)) return "The connection dropped before the server answered. Check your network, then try again.";
  return "Something went wrong. Try again.";
}

/** Field messages from a 422, keyed by the last location segment (`body.email` becomes `email`). */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!isProblemError(error)) return {};
  const out: Record<string, string> = {};
  for (const issue of error.validationIssues) {
    const field = String(issue.loc[issue.loc.length - 1] ?? "");
    const parent = String(issue.loc[issue.loc.length - 2] ?? "");
    const key = /^\d+$/.test(field) ? parent : field;
    if (key && !out[key]) out[key] = issue.msg;
  }
  return out;
}

/** The failure to show above a form: nothing when the 422 already named its fields. */
export function formFailure(error: unknown): string | null {
  if (!error) return null;
  return Object.keys(fieldErrors(error)).length > 0 ? null : problemText(error);
}

/** A local `YYYY-MM-DD` day as the instant it starts or ends in this browser's zone (the old forms' rule). */
export function dayToInstant(day: string | null, edge: "start" | "end"): string | null {
  if (!day) return null;
  return new Date(`${day}T${edge === "start" ? "00:00:00" : "23:59:59"}`).toISOString();
}
