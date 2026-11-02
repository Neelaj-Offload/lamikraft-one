import { describe, expect, it } from "vitest";
import { parseAuditPage, parseCalendar, parseIntegrations, parseMe, parseSetting, parseSettings, parseUoms, SettingsShapeError } from "./parse";
import { draftFrom, fieldPathFromLoc, flattenValue, formFor, inferForm, valueFrom, visibleForm } from "./setting-model";

const bankDetails = {
  key: "bank_details",
  description: "Company bank accounts printed on documents (account numbers are restricted)",
  scope: "company",
  branch_id: null,
  value: {
    accounts: [
      { label: "Main", account_name: null, bank_name: "HDFC", branch_name: "Andheri", account_number: null, account_number_last4: "4421", ifsc: "HDFC0000123", swift_bic: null, currency: "INR", is_default: true },
    ],
  },
  version: 3,
  configured: true,
  not_configured_fields: ["accounts[].account_name"],
  redacted_fields: ["accounts[].account_number"],
  updated_at: "2026-10-01T04:00:00Z",
  updated_by: "0192a000-0000-7000-8000-00000000000a",
  capabilities: { update: { allowed: false, reason_code: "permission_denied" } },
};

describe("settings parsing", () => {
  it("reads a SettingRead and keeps its capability reasons", () => {
    const setting = parseSetting(bankDetails)!;
    expect(setting.key).toBe("bank_details");
    expect(setting.version).toBe(3);
    expect(setting.redacted_fields).toEqual(["accounts[].account_number"]);
    expect(setting.capabilities.update).toEqual({ allowed: false, reason_code: "permission_denied" });
  });

  it("drops rows without a key or version and refuses a non-list", () => {
    expect(parseSettings([bankDetails, { description: "no key" }, { key: "x" }])).toHaveLength(1);
    expect(() => parseSettings({ nope: true })).toThrow(SettingsShapeError);
  });

  it("reads units with their conversions as strings", () => {
    const [kg] = parseUoms([
      { code: "kg", name: "Kilogram", dimension: "mass", is_integer: false, max_decimal_places: 3, aliases: ["kgs"], conversions: [{ from_code: "kg", to_code: "g", factor: "1000", provenance: "si" }] },
    ]);
    expect(kg?.conversions[0]?.factor).toBe("1000");
    expect(kg?.max_decimal_places).toBe(3);
  });

  it("reads the work calendar and keeps only valid weekdays", () => {
    const calendar = parseCalendar({
      source: "company_default",
      time_zone: "Asia/Kolkata",
      work_date: "2026-10-12",
      day_type: "working",
      is_working_day: true,
      rollover_local: "04:00:00",
      workweek: [1, 2, 3, 4, 5, 6, 9],
      shift: { code: "DAY", name: "Day", start_local: "09:00:00", end_local: "18:00:00", starts_at: "2026-10-12T03:30:00Z", ends_at: "2026-10-12T12:30:00Z" },
      next_working_day: "2026-10-13",
      upcoming_holidays: [{ date: "2026-10-20", name: "Dussehra", kind: "public" }],
    });
    expect(calendar.workweek).toEqual([1, 2, 3, 4, 5, 6]);
    expect(calendar.upcoming_holidays[0]?.name).toBe("Dussehra");
    expect(() => parseCalendar({})).toThrow(SettingsShapeError);
  });

  it("reads MeRead with roles, manager, session and the preferences version", () => {
    const me = parseMe({
      user: { id: "u1", email: "meera@demo.test", display_name: "Meera Iyer", full_name: "Meera Iyer", locale: "en-IN", time_zone: null },
      membership: {
        id: "m1",
        status: "active",
        job_title: "Sales executive",
        company: { id: "c1", key: "crown", display_name: "Crown Decor (Demo)", legal_name: "Crown Decor Pvt. Ltd.", is_demo: true, base_currency: "INR" },
        roles: [{ key: "sales", name: "Sales" }],
        branches: [{ id: "b1", code: "HO", name: "Head office", is_head_office: true }],
        teams: [],
        manager: { membership_id: "m0", display_name: "Sahil Mehta" },
        joined_on: "2024-04-01",
      },
      memberships: [],
      permissions: [],
      overrides: [],
      preferences: { version: 4, ui: {}, locale: {}, briefing: {}, voice: {}, assistant: {} },
      session: { id: "s1", auth_method: "password", created_at: "2026-10-12T03:00:00Z", idle_expires_at: "2026-10-12T15:00:00Z", absolute_expires_at: "2026-10-19T03:00:00Z" },
      time_zone: "Asia/Kolkata",
      locale: "en-IN",
    });
    expect(me.membership.roles.map((role) => role.name)).toEqual(["Sales"]);
    expect(me.membership.manager?.display_name).toBe("Sahil Mehta");
    expect(me.preferences_version).toBe(4);
    expect(me.session?.auth_method).toBe("password");
    expect(me.time_zone).toBe("Asia/Kolkata");
  });

  it("reads integrations with a fallback label text", () => {
    const [whatsapp, ai] = parseIntegrations([
      { key: "whatsapp", label: "WhatsApp", mode: "demo", state: "not_connected", label_text: "Demo", verified_at: null, last_checked_at: null, last_error_code: null, details: null },
      { key: "ai", label: "Assistant", mode: "live", state: "error", verified_at: "2026-10-01T00:00:00Z", last_checked_at: "2026-10-12T00:00:00Z", last_error_code: "auth_failed" },
    ]);
    expect(whatsapp?.label_text).toBe("Demo");
    expect(ai?.state).toBe("error");
    expect(ai?.label_text).toBe("error");
  });

  it("reads an audit page and keeps unknown outcomes as text", () => {
    const page = parseAuditPage({
      items: [
        { id: "a1", occurred_at: "2026-10-12T03:25:00Z", actor_type: "user", actor_user_id: "u1", actor_name: "Meera Iyer", action: "sales.quote.create", resource_type: "sales.quote", resource_id: "q1", outcome: "success", request_id: "req-1" },
        { id: "a2", occurred_at: "2026-10-12T03:20:00Z", actor_type: "system", action: "briefings.generate", outcome: "skipped" },
        { occurred_at: "2026-10-12T03:00:00Z", action: "no id" },
      ],
      next_cursor: "abc",
      limit: 50,
    });
    expect(page.items.map((entry) => entry.id)).toEqual(["a1", "a2"]);
    expect(page.items[1]?.outcome).toBe("skipped");
    expect(page.next_cursor).toBe("abc");
    expect(() => parseAuditPage({ items: "nope" })).toThrow(SettingsShapeError);
  });
});

describe("setting values on screen", () => {
  it("flattens one level, numbers list items, joins arrays and hides redacted paths", () => {
    const flat = flattenValue(
      {
        legal_name: "Crown Decor Pvt. Ltd.",
        address_lines: ["Plot 7", "Andheri East"],
        gstin: null,
        contacts: { email: "sales@crown.test", phone: null },
        accounts: [{ label: "Main", account_number: null, account_number_last4: "4421", is_default: true }],
      },
      ["accounts[].account_number"],
    );
    expect(flat.map((row) => [row.term, row.value])).toEqual([
      ["Legal name", "Crown Decor Pvt. Ltd."],
      ["Address", "Plot 7, Andheri East"],
      ["GSTIN", null],
      ["Contacts · Email", "sales@crown.test"],
      ["Contacts · Phone", null],
      ["Account 1 · Label", "Main"],
      ["Account 1 · Account number (last 4)", "4421"],
      ["Account 1 · Default account", true],
    ]);
    expect(flat.find((row) => row.term === "GSTIN")?.mono).toBe(true);
  });

  it("round-trips a draft into a typed value, converting only integers and keeping untouched keys", () => {
    const form = formFor({ key: "quote_defaults", value: {} });
    const original = { currency: "EUR", incoterm: "FOB", validity_days: 30, brand: "LK", price_type: "export", duplicate_copies_assignee: true };
    const draft = draftFrom(form, original);
    expect(draft.fields.validity_days).toBe("30");
    draft.fields.validity_days = "45";
    draft.fields.currency = " usd ";
    draft.fields.duplicate_copies_assignee = false;
    const { value, errors } = valueFrom(form, draft, original);
    expect(errors).toEqual({});
    expect(value).toEqual({ currency: "USD", incoterm: "FOB", validity_days: 45, brand: "LK", price_type: "export", duplicate_copies_assignee: false });
  });

  it("reports client-side problems by draft path and keeps derived and redacted keys out of the way", () => {
    const setting = { key: "bank_details", value: bankDetails.value as Record<string, unknown> };
    const form = visibleForm(formFor(setting), ["accounts[].account_number"]);
    expect(form.lists[0]?.fields.some((field) => field.name === "account_number")).toBe(false);
    const draft = draftFrom(form, setting.value);
    draft.lists.accounts!.push({ label: "", bank_name: "Axis", is_default: false });
    const { value, errors } = valueFrom(form, draft, setting.value, ["accounts[].account_number"]);
    expect(errors).toEqual({ "accounts[1].label": "Enter a value." });
    const accounts = value.accounts as Record<string, unknown>[];
    expect(accounts[0]).toMatchObject({ label: "Main", account_number_last4: "4421", ifsc: "HDFC0000123" });
    expect("account_number" in accounts[0]!).toBe(false);
    expect(accounts[1]?.bank_name).toBe("Axis");
  });

  it("splits address lines and flags a non-integer validity", () => {
    const identity = formFor({ key: "company_identity", value: {} });
    const draft = draftFrom(identity, {});
    draft.fields.address_lines = "Plot 7\n\n Andheri East \n";
    draft.groups.contacts!.website = "https://crown.test";
    const { value } = valueFrom(identity, draft, {});
    expect(value.address_lines).toEqual(["Plot 7", "Andheri East"]);
    expect(value.contacts).toEqual({ email: null, phone: null, website: "https://crown.test" });

    const defaults = formFor({ key: "quote_defaults", value: {} });
    const bad = draftFrom(defaults, { currency: "EUR", incoterm: "FOB", validity_days: 30, brand: "LK", price_type: "export" });
    bad.fields.validity_days = "3.5";
    expect(valueFrom(defaults, bad, {}).errors).toEqual({ validity_days: "Enter a whole number." });
  });

  it("infers a schema for settings it does not know and maps 422 locations to draft paths", () => {
    const form = inferForm({ enabled: true, limit: 5, note: "x", tags: ["a"], owner: { name: "n" }, rows: [{ code: "A", qty: 1 }] });
    expect(form.fields.map((field) => [field.name, field.kind])).toEqual([
      ["enabled", "switch"],
      ["limit", "integer"],
      ["note", "text"],
      ["tags", "csv"],
    ]);
    expect(form.groups[0]?.name).toBe("owner");
    expect(form.lists[0]?.fields.map((field) => field.kind)).toEqual(["text", "integer"]);
    expect(fieldPathFromLoc(["body", "value", "accounts", 1, "label"])).toBe("accounts[1].label");
    expect(fieldPathFromLoc(["body", "value", "brand"])).toBe("brand");
    expect(fieldPathFromLoc(["body", "change_reason"])).toBe("body.change_reason");
  });
});
