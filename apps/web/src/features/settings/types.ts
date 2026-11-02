/**
 * INTERIM hand-written types for the settings area (INTERIM(api-generate): replace with the
 * generated `components["schemas"][...]` once `npm run gen:api` includes these modules).
 *
 * Sources: backend/app/platform/org/schemas.py (SettingRead, SettingRevisionRead, CurrencyRead,
 * UomRead, MyCalendar), identity/schemas.py (MeRead), system/schemas.py (IntegrationRead) and
 * audit/schemas.py (AuditEntryRead, CursorPage).
 */

export type Json = Record<string, unknown>;

export interface Capability {
  allowed: boolean;
  reason_code: string | null;
}

// ---- org settings -----------------------------------------------------------------------------

export interface SettingRead {
  key: string;
  description: string;
  scope: "company" | "branch";
  branch_id: string | null;
  value: Json;
  /** 0 while the setting still uses its default (never written). */
  version: number;
  configured: boolean;
  /** Dotted paths of values that are absent ("Not configured"). */
  not_configured_fields: string[];
  /** Dotted paths nulled for this actor (`accounts[].account_number`). */
  redacted_fields: string[];
  updated_at: string | null;
  updated_by: string | null;
  capabilities: Record<string, Capability>;
}

export interface SettingRevision {
  version: number;
  value: Json;
  redacted_fields: string[];
  changed_at: string;
  changed_by: string | null;
  change_reason: string | null;
}

// ---- reference data ---------------------------------------------------------------------------

export interface Currency {
  code: string;
  name: string;
  symbol: string;
  exponent: number;
}

export interface UomConversion {
  from_code: string;
  to_code: string;
  /** RatioStr: 1 from_code = factor to_code. Kept as a string. */
  factor: string;
  provenance: string;
}

export interface Uom {
  code: string;
  name: string;
  dimension: string;
  is_integer: boolean;
  max_decimal_places: number;
  aliases: string[];
  conversions: UomConversion[];
}

export interface Holiday {
  date: string;
  name: string;
  kind: string;
}

export interface MyCalendar {
  source: "assignment" | "company_default" | "built_in";
  calendar_code: string | null;
  calendar_name: string | null;
  time_zone: string;
  server_now: string;
  work_date: string;
  day_type: "working" | "non_working" | "holiday";
  is_working_day: boolean;
  /** `HH:MM[:SS]` local time. */
  rollover_local: string;
  /** ISO weekday numbers (1 = Monday … 7 = Sunday). */
  workweek: number[];
  shift: {
    code: string | null;
    name: string | null;
    start_local: string;
    end_local: string;
    starts_at: string;
    ends_at: string;
  };
  next_working_day: string;
  upcoming_holidays: Holiday[];
}

// ---- identity ---------------------------------------------------------------------------------

export interface MeProfile {
  id: string;
  email: string | null;
  display_name: string;
  full_name: string | null;
  locale: string;
  time_zone: string | null;
}

export interface MeMembership {
  id: string;
  status: string;
  job_title: string | null;
  company: { id: string; key: string; display_name: string; legal_name: string; is_demo: boolean; base_currency: string } | null;
  roles: { key: string; name: string }[];
  branches: { id: string; code: string; name: string; is_head_office: boolean }[];
  teams: { id: string; key: string; name: string; team_role: string }[];
  manager: { membership_id: string; display_name: string } | null;
  joined_on: string | null;
}

export interface MeSession {
  id: string;
  auth_method: string;
  created_at: string;
  idle_expires_at: string;
  absolute_expires_at: string;
}

export interface Me {
  user: MeProfile;
  membership: MeMembership;
  /** `preferences.version`, sent as `expected_version` on preference saves. */
  preferences_version: number;
  session: MeSession | null;
  time_zone: string;
  locale: string;
}

// ---- system -----------------------------------------------------------------------------------

export type IntegrationState = "not_connected" | "connected" | "error";

export interface Integration {
  key: string;
  label: string;
  mode: "demo" | "live";
  state: IntegrationState;
  label_text: string;
  verified_at: string | null;
  last_checked_at: string | null;
  last_error_code: string | null;
}

// ---- audit ------------------------------------------------------------------------------------

export const AUDIT_OUTCOMES = ["success", "denied", "failed"] as const;
export type AuditOutcome = (typeof AUDIT_OUTCOMES)[number];

export interface AuditEntry {
  id: string;
  occurred_at: string;
  actor_type: string;
  actor_user_id: string | null;
  actor_name: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  resource_label: string | null;
  outcome: AuditOutcome | (string & {});
  reason: string | null;
  request_id: string | null;
}

export interface CursorPage<T> {
  items: T[];
  next_cursor: string | null;
  limit: number;
}
