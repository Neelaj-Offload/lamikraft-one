/**
 * INTERIM hand-written types for the session bootstrap and the UI poll.
 *
 * Source contracts: docs/architecture/api-conventions.md §8 (bootstrap) and §12 (poll), and
 * backend/app/platform/bootstrap.py (UiSection registry: each section is a dict, or
 * `{"status": "unavailable"}` when its contributor failed). The `ui` module that serves
 * `GET /api/v1/session/bootstrap` and `GET /api/v1/ui/poll` is built by another lane in this
 * wave, so the endpoints are not in `src/lib/api/schema.d.ts` yet.
 *
 * INTERIM(api-generate): replace every type in this file with the generated
 * `components["schemas"][...]` types once the ui module merges, and delete `parse.ts`'s
 * tolerant field fallbacks that the generated contract makes unnecessary.
 */

import type { MotionPreference, ThemePreference } from "@/lib/ui-preferences";

export type PermissionScope = "own" | "team" | "branch" | "company";

export interface EffectivePermission {
  key: string;
  scope: PermissionScope;
}

export interface SessionUser {
  id: string;
  display_name: string;
  email: string | null;
}

export interface SessionMembership {
  id: string | null;
  role_names: string[];
  is_demo: boolean;
}

export interface SessionCompany {
  id: string;
  display_name: string;
  legal_name: string | null;
  is_demo: boolean;
}

export interface SessionBranch {
  id: string;
  code: string;
  name: string;
}

export type GreetingPeriod = "morning" | "afternoon" | "evening";
export type Density = "comfortable" | "compact";

/** The `ui` preference section (frontend_verification §17 `user_ui_preferences`). */
export interface UiPreferencesState {
  theme: ThemePreference;
  motion: MotionPreference;
  sidebar_collapsed: boolean;
  context_rail_open: boolean;
  density: Density;
  /** WCAG 2.1.4: single-character shortcuts ("/") can be turned off. */
  shortcuts_enabled: boolean;
}

export type IntegrationMode = "live" | "demo" | "not_connected";

export interface IntegrationStatus {
  key: string;
  label: string;
  mode: IntegrationMode;
}

/** Inbox counts per tab, computed server-side over the actor's visible tasks. */
export interface InboxCounts {
  total: number;
  tabs: Partial<Record<string, number>>;
}

export interface BriefingState {
  version: number | null;
  work_date: string | null;
}

/** A UiSection result: its value, or unavailable when its contributor failed. */
export type SectionValue<T> = { status: "ok"; value: T } | { status: "unavailable" };

/** One authorised, implemented navigation area, in display order. */
export interface NavEntry {
  key: string;
}

/**
 * api-conventions §8 "feature readiness flags for nav": feature or area key → whether it is
 * implemented and switched on for this workspace. Only boolean entries are kept.
 */
export type FeatureReadiness = Readonly<Record<string, boolean>>;

/**
 * INTERIM(api-generate): capability flags for controls that depend on later slices. §8 does not
 * name them yet (lane contract question), so the parser reads `capabilities` and falls back to
 * the same keys inside `features`; both default to false (the control is not rendered).
 */
export interface SessionCapabilities {
  /** The text assistant (agent runtime) accepts commands from the Today command bar. */
  assistant: boolean;
  /** Push-to-talk voice capture is available for this user (Slice 3). */
  voice: boolean;
}

/** Configured provider modes (ui/schemas.py `IntegrationModes`), for truthful Demo labels. */
export interface IntegrationModes {
  ai: "demo" | "live";
  whatsapp: "demo" | "live";
  email: "demo" | "smtp";
}

export interface SessionBootstrap {
  user: SessionUser;
  membership: SessionMembership;
  company: SessionCompany;
  branches: SessionBranch[];
  /** IANA zone used for every date and time on screen. */
  time_zone: string;
  /** BCP 47 locale, e.g. en-IN. */
  locale: string;
  /** RFC 3339 UTC instant used as "now" for server-rendered labels. */
  server_now: string;
  greeting_period: GreetingPeriod | null;
  permissions: EffectivePermission[];
  ui: UiPreferencesState;
  /** `preferences.version`: sent as `expected_version` with every preference change (0 if absent). */
  preferences_version: number;
  nav: NavEntry[];
  features: FeatureReadiness;
  capabilities: SessionCapabilities;
  /** Null when the server did not send `integration_modes`. */
  integration_modes: IntegrationModes | null;
  integrations: SectionValue<IntegrationStatus[]>;
  inbox_counts: SectionValue<InboxCounts>;
  briefing: SectionValue<BriefingState>;
  /** The rotated CSRF value (the browser also receives it as the `lk_csrf` cookie). */
  csrf_token: string | null;
}

/** `GET /api/v1/ui/poll`: the sections registered with `in_poll=True`. */
export interface UiPollState {
  inbox_counts: SectionValue<InboxCounts>;
  briefing: SectionValue<BriefingState>;
}
