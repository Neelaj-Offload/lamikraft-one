/**
 * Runtime parsing of the bootstrap and poll payloads into the interim session model.
 *
 * Until the generated types exist, the web cannot rely on TypeScript alone for a payload
 * another lane is writing in parallel, so required fields are checked and reported together,
 * optional sections fall back to explicit "unavailable"/false values (never invented data).
 */

import { DEFAULT_UI_PREFERENCES, MOTION_PREFERENCES, THEMES } from "@/lib/ui-preferences";
import type {
  BriefingState,
  EffectivePermission,
  FeatureReadiness,
  InboxCounts,
  IntegrationMode,
  IntegrationModes,
  IntegrationStatus,
  NavEntry,
  PermissionScope,
  SectionValue,
  SessionBootstrap,
  SessionCapabilities,
  UiPollState,
  UiPreferencesState,
} from "./types";

export class BootstrapShapeError extends Error {
  override readonly name = "BootstrapShapeError";

  constructor(readonly problems: string[]) {
    super(`The session bootstrap response is missing or has invalid fields: ${problems.join(", ")}`);
  }
}

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function bool(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

const SCOPES: readonly PermissionScope[] = ["own", "team", "branch", "company"];
const MODES: readonly IntegrationMode[] = ["live", "demo", "not_connected"];

/** A UiSection is a dict, or `{status: "unavailable"}`; sections may sit at the top level or under `sections`. */
function readSection<T>(raw: Json, key: string, parse: (value: Json) => T | null): SectionValue<T> {
  const holder = isObject(raw.sections) ? raw.sections : raw;
  const value = holder[key];
  if (!isObject(value) || value.status === "unavailable") return { status: "unavailable" };
  const parsed = parse(value);
  return parsed === null ? { status: "unavailable" } : { status: "ok", value: parsed };
}

/** Tabs whose open items make up the Inbox badge; `exceptions` overlaps them (overdue items). */
const COUNTED_TABS = ["tasks", "approvals", "conversations"] as const;

/**
 * The tasks module's `inbox_counts` section is flat (`InboxCounts{tasks, approvals,
 * conversations, exceptions}`, tasks/schemas.py). The earlier `{total, tabs}` shape is still
 * read. The badge total counts each open item once: exceptions are overdue items that already
 * sit in another tab, so they are not added again.
 */
function parseInboxCounts(value: Json): InboxCounts | null {
  const tabs: Record<string, number> = {};
  const rawTabs = isObject(value.tabs) ? value.tabs : value;
  for (const [tab, n] of Object.entries(rawTabs)) {
    if (tab === "total" || tab === "status") continue;
    const parsed = count(n);
    if (parsed !== null) tabs[tab] = parsed;
  }
  const explicit = count(value.total);
  if (explicit !== null) return { total: explicit, tabs };
  if (!COUNTED_TABS.some((tab) => tab in tabs)) return null;
  return { total: COUNTED_TABS.reduce((sum, tab) => sum + (tabs[tab] ?? 0), 0), tabs };
}

function parseBriefingState(value: Json): BriefingState | null {
  const version = value.version === null ? null : count(value.version);
  if (version === null && value.version !== null) return null;
  return { version, work_date: str(value.work_date) };
}

function parseIntegrations(value: Json): IntegrationStatus[] | null {
  const items = Array.isArray(value.items) ? value.items : null;
  if (!items) return null;
  const out: IntegrationStatus[] = [];
  for (const item of items) {
    if (!isObject(item)) continue;
    const key = str(item.key);
    const mode = MODES.find((m) => m === item.mode);
    if (key && mode) out.push({ key, label: str(item.label) ?? key, mode });
  }
  return out;
}

function parseUi(raw: unknown): UiPreferencesState {
  const ui = isObject(raw) ? raw : {};
  const theme = THEMES.find((t) => t === ui.theme) ?? DEFAULT_UI_PREFERENCES.theme;
  const motion = MOTION_PREFERENCES.find((m) => m === ui.motion) ?? DEFAULT_UI_PREFERENCES.motion;
  return {
    theme,
    motion,
    sidebar_collapsed: bool(ui.sidebar_collapsed),
    context_rail_open: bool(ui.context_rail_open),
    density: ui.density === "compact" ? "compact" : "comfortable",
    shortcuts_enabled: bool(ui.shortcuts_enabled, true),
  };
}

function parseNav(raw: unknown): NavEntry[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const out: NavEntry[] = [];
  for (const entry of raw) {
    const key = typeof entry === "string" ? entry : isObject(entry) ? str(entry.key) : null;
    const enabled = isObject(entry) ? entry.enabled !== false : true;
    if (key && enabled && !seen.has(key)) {
      seen.add(key);
      out.push({ key });
    }
  }
  return out;
}

function parseFeatures(raw: unknown): FeatureReadiness {
  const features = isObject(raw) ? raw : {};
  return Object.fromEntries(Object.entries(features).filter((entry): entry is [string, boolean] => typeof entry[1] === "boolean"));
}

/** The permission that gates the assistant API (permissions.md §7.5). */
export const ASSISTANT_PERMISSION = "agents.assistant.use";

/**
 * INTERIM: `capabilities{assistant,voice}`, else the same keys in `features`; false when absent.
 * The assistant is also available when the user holds `agents.assistant.use` (the server
 * gates every agents route with it). Voice stays off in Slice 1.
 */
function parseCapabilities(raw: Json, permissions: readonly EffectivePermission[]): SessionCapabilities {
  const source = isObject(raw.capabilities) ? raw.capabilities : isObject(raw.features) ? raw.features : {};
  const permitted = permissions.some((permission) => permission.key === ASSISTANT_PERMISSION);
  return { assistant: bool(source.assistant) || permitted, voice: bool(source.voice) };
}

const AI_MODES: readonly IntegrationModes["ai"][] = ["demo", "live"];

/** `integration_modes{ai, whatsapp, email}` from the bootstrap (ui/schemas.py `IntegrationModes`). */
function parseIntegrationModes(raw: unknown): IntegrationModes | null {
  if (!isObject(raw)) return null;
  const ai = AI_MODES.find((mode) => mode === raw.ai);
  if (!ai) return null;
  return {
    ai,
    whatsapp: raw.whatsapp === "live" ? "live" : "demo",
    email: raw.email === "smtp" ? "smtp" : "demo",
  };
}

/**
 * The integrations list: the `integrations` section when a module provides one, otherwise
 * derived from `integration_modes`, so Demo labels are truthful either way.
 */
function integrationsFrom(raw: Json, modes: IntegrationModes | null): SectionValue<IntegrationStatus[]> {
  const section = readSection(raw, "integrations", parseIntegrations);
  if (section.status === "ok" || !modes) return section;
  return {
    status: "ok",
    value: [
      { key: "ai", label: "Assistant", mode: modes.ai },
      { key: "whatsapp", label: "WhatsApp", mode: modes.whatsapp },
      { key: "email", label: "Email", mode: modes.email === "smtp" ? "live" : "demo" },
    ],
  };
}

export function parseBootstrap(raw: unknown): SessionBootstrap {
  if (!isObject(raw)) throw new BootstrapShapeError(["<body>"]);
  const problems: string[] = [];
  const need = (value: string | null, field: string): string => {
    if (value === null) problems.push(field);
    return value ?? "";
  };

  const user = isObject(raw.user) ? raw.user : {};
  const membership = isObject(raw.membership) ? raw.membership : {};
  const company = isObject(raw.company) ? raw.company : {};

  const permissions: EffectivePermission[] = [];
  if (!Array.isArray(raw.permissions)) problems.push("permissions");
  else {
    for (const entry of raw.permissions) {
      const key = isObject(entry) ? str(entry.key) : str(entry);
      const scope = isObject(entry) ? SCOPES.find((s) => s === entry.scope) : "company";
      if (key && scope) permissions.push({ key, scope });
    }
  }

  const serverNow = str(raw.server_now);
  if (serverNow !== null && Number.isNaN(Date.parse(serverNow))) problems.push("server_now");

  const companyIsDemo = bool(company.is_demo);
  const integrationModes = parseIntegrationModes(raw.integration_modes);
  const greeting = raw.greeting_period;

  const bootstrap: SessionBootstrap = {
    user: {
      id: need(str(user.id), "user.id"),
      display_name: need(str(user.display_name), "user.display_name"),
      email: str(user.email),
    },
    membership: {
      id: str(membership.id),
      role_names: Array.isArray(membership.role_names)
        ? membership.role_names.filter((name): name is string => typeof name === "string")
        : [],
      is_demo: bool(membership.is_demo, companyIsDemo),
    },
    company: {
      id: need(str(company.id), "company.id"),
      display_name: need(str(company.display_name) ?? str(company.name), "company.display_name"),
      legal_name: str(company.legal_name),
      is_demo: companyIsDemo,
    },
    branches: Array.isArray(raw.branches)
      ? raw.branches.flatMap((branch) => {
          if (!isObject(branch)) return [];
          const id = str(branch.id);
          return id ? [{ id, code: str(branch.code) ?? "", name: str(branch.name) ?? str(branch.code) ?? "" }] : [];
        })
      : [],
    time_zone: need(str(raw.time_zone), "time_zone"),
    locale: need(str(raw.locale), "locale"),
    server_now: need(serverNow, "server_now"),
    greeting_period: greeting === "morning" || greeting === "afternoon" || greeting === "evening" ? greeting : null,
    permissions,
    ui: parseUi(raw.ui_preferences ?? (isObject(raw.preferences) ? raw.preferences.ui : undefined)),
    preferences_version: isObject(raw.preferences) ? (count(raw.preferences.version) ?? 0) : 0,
    nav: parseNav(raw.nav),
    features: parseFeatures(raw.features),
    capabilities: parseCapabilities(raw, permissions),
    integration_modes: integrationModes,
    integrations: integrationsFrom(raw, integrationModes),
    inbox_counts: readSection(raw, "inbox_counts", parseInboxCounts),
    briefing: readSection(raw, "briefing", parseBriefingState),
    csrf_token: str(raw.csrf_token),
  };

  if (bootstrap.time_zone && !isValidTimeZone(bootstrap.time_zone)) problems.push("time_zone");
  if (problems.length > 0) throw new BootstrapShapeError(problems);
  return bootstrap;
}

export function parseUiPoll(raw: unknown): UiPollState {
  const body = isObject(raw) ? raw : {};
  return {
    inbox_counts: readSection(body, "inbox_counts", parseInboxCounts),
    briefing: readSection(body, "briefing", parseBriefingState),
  };
}

function isValidTimeZone(zone: string): boolean {
  try {
    new Intl.DateTimeFormat("en", { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}
