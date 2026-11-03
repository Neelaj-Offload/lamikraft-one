import { describe, expect, it, vi } from "vitest";
import { controlsWithoutVisibleFocus, nestedInteractive, renderInSession, renderWithQueries, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { queryKeys } from "@/lib/api/query-keys";
import { AreaOverview } from "@/features/areas/area-overview";
import { CompanySettings } from "./company-settings";
import { parseSetting } from "./parse";
import { SettingCard, settingItems } from "./setting-card";
import { SettingsHub, workspaceModes } from "./settings-hub";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/settings",
  useSearchParams: () => new URLSearchParams(),
}));

const admin = () =>
  testBootstrap({
    permissions: [
      { key: "org.settings.read", scope: "company" },
      { key: "audit.log.read", scope: "company" },
      { key: "system.integration.read", scope: "company" },
    ],
    integration_modes: { ai: "demo", whatsapp: "demo", email: "smtp" },
  });

const quoteDefaults = parseSetting({
  key: "quote_defaults",
  description: "Defaults for new quotes",
  scope: "company",
  branch_id: null,
  value: { currency: "EUR", incoterm: "FOB", validity_days: 30, brand: "LK", price_type: "export", duplicate_copies_assignee: true },
  version: 0,
  configured: false,
  not_configured_fields: [],
  redacted_fields: [],
  updated_at: null,
  updated_by: null,
  capabilities: { update: { allowed: true, reason_code: null } },
})!;

describe("settings hub", () => {
  it("lists only the sections the role may open and labels integration modes truthfully", () => {
    const html = renderInSession(<SettingsHub />, testBootstrap());
    const text = textOf(html);
    expect(text).toContain("Profile");
    expect(text).toContain("Reference data");
    expect(text).not.toContain("Company");
    expect(text).not.toContain("Audit log");
    expect(text).toContain("Crown Decor (Demo)");

    const full = textOf(renderInSession(<SettingsHub />, admin()));
    expect(full).toContain("Company");
    expect(full).toContain("Audit log");
    expect(full).toContain("Live");
    expect(workspaceModes(admin()).map((entry) => entry.mode)).toEqual(["demo", "demo", "live"]);
  });
});

describe("company settings", () => {
  it("shows Permission denied without an org. key and never fetches", () => {
    const html = renderWithQueries(<CompanySettings />, () => undefined, testBootstrap());
    expect(textOf(html)).toContain("You don't have access to Company settings");
  });

  it("renders a setting card with Yes/No values, the key in mono, Not configured and Edit when allowed", () => {
    const html = renderWithQueries(<SettingCard setting={quoteDefaults} />, (client) => client.setQueryData(queryKeys.org.settings(), [quoteDefaults]), admin());
    const text = textOf(html);
    expect(text).toContain("quote_defaults");
    expect(text).toContain("Default values");
    expect(text).toContain("Not configured");
    expect(text).toContain("Yes");
    expect(text).toContain("Edit");
    expect(text).toContain("History");
    expect(nestedInteractive(html)).toEqual([]);
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);
    expect(settingItems(quoteDefaults).map((item) => item.term)).toEqual(["Currency", "Incoterm", "Validity (days)", "Brand", "Price type", "A duplicated quote is assigned to whoever duplicates it"]);
  });

  it("offers no Edit when the server does not allow it", () => {
    const readOnly = { ...quoteDefaults, capabilities: { update: { allowed: false, reason_code: "permission_denied" } } };
    expect(textOf(renderWithQueries(<SettingCard setting={readOnly} />, () => undefined, admin()))).not.toContain("Edit");
  });
});

describe("area overviews", () => {
  it("say what is planned, with slice badges and links to Today and the Inbox, and show no figures", () => {
    const html = renderInSession(<AreaOverview area="operations" />);
    const text = textOf(html);
    expect(text).toContain("the rest of Operations arrives in Slice 4");
    expect(text).toContain("Available");
    expect(text).toContain("Planned · Slice 4");
    expect(html).toContain('href="/today"');
    expect(html).toContain('href="/inbox"');
    expect(text).not.toMatch(/\b\d+ (open|items|invoices|orders)\b/);

    const finance = textOf(renderInSession(<AreaOverview area="finance" />));
    expect(finance).toContain("Finance is planned for Slice 5");
    expect(finance).toContain("Receipts and allocations");
  });
});
