/**
 * Runtime readers for the settings area (see types.ts). Required fields are checked; decimals
 * and ratios stay strings; anything unexpected is dropped rather than guessed.
 */

import {
  AUDIT_OUTCOMES,
  type AuditEntry,
  type Capability,
  type Currency,
  type CursorPage,
  type Integration,
  type Json,
  type Me,
  type MeSession,
  type MyCalendar,
  type SettingRead,
  type SettingRevision,
  type Uom,
} from "./types";

export class SettingsShapeError extends Error {
  override readonly name = "SettingsShapeError";
}

export const isObject = (value: unknown): value is Json => value !== null && typeof value === "object" && !Array.isArray(value);
const str = (value: unknown): string | null => (typeof value === "string" && value !== "" ? value : null);
const arr = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const int = (value: unknown): number | null => (typeof value === "number" && Number.isInteger(value) ? value : null);
const strings = (value: unknown): string[] => arr(value).filter((entry): entry is string => typeof entry === "string");

function fail(what: string): never {
  throw new SettingsShapeError(`The settings response could not be read (${what}).`);
}

function capabilities(value: unknown): Record<string, Capability> {
  if (!isObject(value)) return {};
  const out: Record<string, Capability> = {};
  for (const [key, cap] of Object.entries(value)) {
    if (isObject(cap) && typeof cap.allowed === "boolean") out[key] = { allowed: cap.allowed, reason_code: str(cap.reason_code) };
  }
  return out;
}

/** A list that may arrive bare or wrapped as `{items}`. */
export function listOf<T>(raw: unknown, item: (value: unknown) => T | null, what: string): T[] {
  const list = Array.isArray(raw) ? raw : isObject(raw) && Array.isArray(raw.items) ? raw.items : null;
  if (!list) fail(what);
  return list.map(item).filter((entry): entry is T => entry !== null);
}

// ---- org settings -----------------------------------------------------------------------------

export function parseSetting(raw: unknown): SettingRead | null {
  if (!isObject(raw) || !str(raw.key) || int(raw.version) === null) return null;
  return {
    key: str(raw.key)!,
    description: str(raw.description) ?? str(raw.key)!,
    scope: raw.scope === "branch" ? "branch" : "company",
    branch_id: str(raw.branch_id),
    value: isObject(raw.value) ? raw.value : {},
    version: int(raw.version)!,
    configured: raw.configured === true,
    not_configured_fields: strings(raw.not_configured_fields),
    redacted_fields: strings(raw.redacted_fields),
    updated_at: str(raw.updated_at),
    updated_by: str(raw.updated_by),
    capabilities: capabilities(raw.capabilities),
  };
}

export function parseSettings(raw: unknown): SettingRead[] {
  return listOf(raw, parseSetting, "settings");
}

export function needSetting(raw: unknown): SettingRead {
  return parseSetting(raw) ?? fail("setting");
}

export function parseRevision(raw: unknown): SettingRevision | null {
  if (!isObject(raw) || int(raw.version) === null || !str(raw.changed_at)) return null;
  return {
    version: int(raw.version)!,
    value: isObject(raw.value) ? raw.value : {},
    redacted_fields: strings(raw.redacted_fields),
    changed_at: str(raw.changed_at)!,
    changed_by: str(raw.changed_by),
    change_reason: str(raw.change_reason),
  };
}

export function parseRevisions(raw: unknown): SettingRevision[] {
  return listOf(raw, parseRevision, "revisions").sort((a, b) => b.version - a.version);
}

// ---- reference data ---------------------------------------------------------------------------

export function parseCurrency(raw: unknown): Currency | null {
  if (!isObject(raw) || !str(raw.code)) return null;
  return { code: str(raw.code)!, name: str(raw.name) ?? str(raw.code)!, symbol: str(raw.symbol) ?? "", exponent: int(raw.exponent) ?? 2 };
}

export function parseCurrencies(raw: unknown): Currency[] {
  return listOf(raw, parseCurrency, "currencies");
}

export function parseUom(raw: unknown): Uom | null {
  if (!isObject(raw) || !str(raw.code)) return null;
  return {
    code: str(raw.code)!,
    name: str(raw.name) ?? str(raw.code)!,
    dimension: str(raw.dimension) ?? "",
    is_integer: raw.is_integer === true,
    max_decimal_places: int(raw.max_decimal_places) ?? (raw.is_integer === true ? 0 : 4),
    aliases: strings(raw.aliases),
    conversions: arr(raw.conversions).flatMap((entry) =>
      isObject(entry) && str(entry.from_code) && str(entry.to_code) && str(entry.factor)
        ? [{ from_code: str(entry.from_code)!, to_code: str(entry.to_code)!, factor: str(entry.factor)!, provenance: str(entry.provenance) ?? "" }]
        : [],
    ),
  };
}

export function parseUoms(raw: unknown): Uom[] {
  return listOf(raw, parseUom, "units of measure");
}

const SOURCES: readonly MyCalendar["source"][] = ["assignment", "company_default", "built_in"];
const DAY_TYPES: readonly MyCalendar["day_type"][] = ["working", "non_working", "holiday"];

export function parseCalendar(raw: unknown): MyCalendar {
  if (!isObject(raw) || !str(raw.time_zone) || !str(raw.work_date)) fail("calendar");
  const shift = isObject(raw.shift) ? raw.shift : {};
  return {
    source: SOURCES.find((source) => source === raw.source) ?? "built_in",
    calendar_code: str(raw.calendar_code),
    calendar_name: str(raw.calendar_name),
    time_zone: str(raw.time_zone)!,
    server_now: str(raw.server_now) ?? "",
    work_date: str(raw.work_date)!,
    day_type: DAY_TYPES.find((type) => type === raw.day_type) ?? "working",
    is_working_day: raw.is_working_day === true,
    rollover_local: str(raw.rollover_local) ?? "",
    workweek: arr(raw.workweek).filter((day): day is number => typeof day === "number" && Number.isInteger(day) && day >= 1 && day <= 7),
    shift: {
      code: str(shift.code),
      name: str(shift.name),
      start_local: str(shift.start_local) ?? "",
      end_local: str(shift.end_local) ?? "",
      starts_at: str(shift.starts_at) ?? "",
      ends_at: str(shift.ends_at) ?? "",
    },
    next_working_day: str(raw.next_working_day) ?? "",
    upcoming_holidays: arr(raw.upcoming_holidays).flatMap((entry) =>
      isObject(entry) && str(entry.date) ? [{ date: str(entry.date)!, name: str(entry.name) ?? "", kind: str(entry.kind) ?? "" }] : [],
    ),
  };
}

// ---- identity ---------------------------------------------------------------------------------

function session(raw: unknown): MeSession | null {
  if (!isObject(raw) || !str(raw.id) || !str(raw.created_at)) return null;
  return {
    id: str(raw.id)!,
    auth_method: str(raw.auth_method) ?? "",
    created_at: str(raw.created_at)!,
    idle_expires_at: str(raw.idle_expires_at) ?? "",
    absolute_expires_at: str(raw.absolute_expires_at) ?? "",
  };
}

export function parseMe(raw: unknown): Me {
  if (!isObject(raw) || !isObject(raw.user) || !str(raw.user.id)) fail("me");
  const user = raw.user;
  const membership = isObject(raw.membership) ? raw.membership : {};
  const company = isObject(membership.company) ? membership.company : null;
  const manager = isObject(membership.manager) ? membership.manager : null;
  const preferences = isObject(raw.preferences) ? raw.preferences : {};
  return {
    user: {
      id: str(user.id)!,
      email: str(user.email),
      display_name: str(user.display_name) ?? "",
      full_name: str(user.full_name),
      locale: str(user.locale) ?? str(raw.locale) ?? "",
      time_zone: str(user.time_zone),
    },
    membership: {
      id: str(membership.id) ?? "",
      status: str(membership.status) ?? "",
      job_title: str(membership.job_title),
      company:
        company && str(company.id)
          ? {
              id: str(company.id)!,
              key: str(company.key) ?? "",
              display_name: str(company.display_name) ?? "",
              legal_name: str(company.legal_name) ?? "",
              is_demo: company.is_demo === true,
              base_currency: str(company.base_currency) ?? "",
            }
          : null,
      roles: arr(membership.roles).flatMap((role) => (isObject(role) && str(role.name) ? [{ key: str(role.key) ?? "", name: str(role.name)! }] : [])),
      branches: arr(membership.branches).flatMap((branch) =>
        isObject(branch) && str(branch.id)
          ? [{ id: str(branch.id)!, code: str(branch.code) ?? "", name: str(branch.name) ?? str(branch.code) ?? "", is_head_office: branch.is_head_office === true }]
          : [],
      ),
      teams: arr(membership.teams).flatMap((team) =>
        isObject(team) && str(team.id) ? [{ id: str(team.id)!, key: str(team.key) ?? "", name: str(team.name) ?? "", team_role: str(team.team_role) ?? "" }] : [],
      ),
      manager: manager && str(manager.display_name) ? { membership_id: str(manager.membership_id) ?? "", display_name: str(manager.display_name)! } : null,
      joined_on: str(membership.joined_on),
    },
    preferences_version: int(preferences.version) ?? 0,
    session: session(raw.session),
    time_zone: str(raw.time_zone) ?? str(user.time_zone) ?? "",
    locale: str(raw.locale) ?? str(user.locale) ?? "",
  };
}

// ---- system -----------------------------------------------------------------------------------

const STATES: readonly Integration["state"][] = ["not_connected", "connected", "error"];

export function parseIntegration(raw: unknown): Integration | null {
  if (!isObject(raw) || !str(raw.key)) return null;
  const mode = raw.mode === "live" ? "live" : "demo";
  const state = STATES.find((candidate) => candidate === raw.state) ?? "not_connected";
  return {
    key: str(raw.key)!,
    label: str(raw.label) ?? str(raw.key)!,
    mode,
    state,
    label_text: str(raw.label_text) ?? (mode === "demo" ? "Demo" : state),
    verified_at: str(raw.verified_at),
    last_checked_at: str(raw.last_checked_at),
    last_error_code: str(raw.last_error_code),
  };
}

export function parseIntegrations(raw: unknown): Integration[] {
  return listOf(raw, parseIntegration, "integrations");
}

// ---- audit ------------------------------------------------------------------------------------

export function parseAuditEntry(raw: unknown): AuditEntry | null {
  if (!isObject(raw) || !str(raw.id) || !str(raw.occurred_at) || !str(raw.action)) return null;
  return {
    id: str(raw.id)!,
    occurred_at: str(raw.occurred_at)!,
    actor_type: str(raw.actor_type) ?? "",
    actor_user_id: str(raw.actor_user_id),
    actor_name: str(raw.actor_name),
    action: str(raw.action)!,
    resource_type: str(raw.resource_type),
    resource_id: str(raw.resource_id),
    resource_label: str(raw.resource_label),
    outcome: AUDIT_OUTCOMES.find((outcome) => outcome === raw.outcome) ?? str(raw.outcome) ?? "success",
    reason: str(raw.reason),
    request_id: str(raw.request_id),
  };
}

export function parseAuditPage(raw: unknown): CursorPage<AuditEntry> {
  if (!isObject(raw) || !Array.isArray(raw.items)) fail("audit entries");
  const items = raw.items.map(parseAuditEntry).filter((entry): entry is AuditEntry => entry !== null);
  return { items, next_cursor: str(raw.next_cursor), limit: int(raw.limit) ?? items.length };
}
