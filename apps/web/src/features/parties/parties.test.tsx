import { describe, expect, it, vi } from "vitest";
import { createApiClient } from "@/lib/api/client";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { controlsWithoutVisibleFocus, renderWithQueries, seedQueryError, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { SalesHub } from "@/features/sales/sales-hub";
import { updateParty } from "./api";
import {
  addressLines,
  contactsWith,
  createBodyOf,
  dirtyHeaderFields,
  fieldErrorsFrom,
  headerChanges,
  headerFormOf,
  mergeHeaderConflict,
  EMPTY_CREATE,
  validateCreate,
} from "./form-model";
import { partyListStateFrom } from "./list-state";
import { parsePartyDetail, parsePartyPage } from "./parse";
import { PartyCreate } from "./party-create";
import { PartyDetail } from "./party-detail";
import { PartyList, partyListQueryKey } from "./party-list";
import { TEST_PARTY_ID, testPartyWire } from "./test-support";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/sales/parties",
  useSearchParams: () => new URLSearchParams(),
}));

const partiesBootstrap = (extra: { key: string; scope: string }[] = []) =>
  testBootstrap({
    permissions: [
      { key: "parties.party.read", scope: "company" },
      { key: "sales.quote.read", scope: "own" },
      ...extra,
    ],
  });

const problem = (status: number, code: string, extra: Record<string, unknown> = {}) =>
  new ProblemError({ type: "about:blank", title: "Problem", status, code, detail: "Changed by someone else", request_id: "req-7", ...extra });

describe("the customers list", () => {
  const state = partyListStateFrom({});

  it("renders the rows with number links, roles, status text and the New customer action only with the permission", () => {
    const page = parsePartyPage({ items: [testPartyWire()], total: 1, limit: 25, offset: 0 });
    const html = renderWithQueries(
      <PartyList state={state} />,
      (client) => client.setQueryData(partyListQueryKey(state), page),
      partiesBootstrap([{ key: "parties.party.create", scope: "company" }]),
    );
    expect(html).toContain(`href="/sales/parties/${TEST_PARTY_ID}"`);
    expect(textOf(html)).toContain("P-00001");
    expect(textOf(html)).toContain("Nordhaus Interiors GmbH");
    expect(textOf(html)).toContain("Active");
    expect(textOf(html)).toContain("Lena Brandt");
    expect(html).toContain('href="/sales/parties/new"');
    expect(html).toContain('<h1');
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);

    const readOnly = renderWithQueries(<PartyList state={state} />, (client) => client.setQueryData(partyListQueryKey(state), page), partiesBootstrap());
    expect(readOnly).not.toContain('href="/sales/parties/new"');
  });

  it("shows the empty state and the error state honestly", () => {
    const empty = renderWithQueries(<PartyList state={state} />, (client) => client.setQueryData(partyListQueryKey(state), { items: [], total: 0, limit: 25, offset: 0 }), partiesBootstrap());
    expect(textOf(empty)).toContain("No customers match these filters.");
    const failed = renderWithQueries(<PartyList state={state} />, (client) => seedQueryError(client, partyListQueryKey(state), problem(500, "server_error")), partiesBootstrap());
    expect(textOf(failed)).toContain("couldn't be loaded");
    expect(textOf(failed)).toContain("req-7");
  });
});

describe("the customer record", () => {
  it("renders header facts, contacts with mailto/tel links, grouped addresses, tax identifiers and Edit only when allowed", () => {
    const party = parsePartyDetail(testPartyWire());
    const html = renderWithQueries(<PartyDetail partyId={TEST_PARTY_ID} />, (client) => client.setQueryData(queryKeys.parties.party(TEST_PARTY_ID), party), partiesBootstrap());
    const text = textOf(html);
    expect(text).toContain("P-00001");
    expect(text).toContain("Nordhaus Interiors");
    expect(html).toContain('href="mailto:lena@nordhaus.example"');
    expect(html).toContain('href="tel:+4940123456"');
    expect(text).toContain("Primary");
    expect(text).toContain("Billing");
    expect(text).toContain("Shipping");
    expect(text).toContain("Hamburg, 20457");
    expect(text).toContain("DE123456789");
    expect(text).toContain("Unverified");
    expect(text).toContain("Edit");
    expect(text).toContain("Add contact");
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);

    const readOnly = parsePartyDetail(testPartyWire({ capabilities: { update: { allowed: false, reason_code: "permission_denied" } } }));
    const readOnlyHtml = renderWithQueries(<PartyDetail partyId={TEST_PARTY_ID} />, (client) => client.setQueryData(queryKeys.parties.party(TEST_PARTY_ID), readOnly), partiesBootstrap());
    expect(textOf(readOnlyHtml)).not.toContain("Edit");
    expect(textOf(readOnlyHtml)).not.toContain("Add contact");
  });

  it("shows Not available for a 404 and the error state otherwise", () => {
    const missing = renderWithQueries(<PartyDetail partyId={TEST_PARTY_ID} />, (client) => seedQueryError(client, queryKeys.parties.party(TEST_PARTY_ID), problem(404, "not_found")), partiesBootstrap());
    expect(textOf(missing)).toContain("Not found or not available to you");
    const failed = renderWithQueries(<PartyDetail partyId={TEST_PARTY_ID} />, (client) => seedQueryError(client, queryKeys.parties.party(TEST_PARTY_ID), problem(503, "service_unavailable")), partiesBootstrap());
    expect(textOf(failed)).toContain("couldn't be loaded");
  });
});

describe("the New customer form", () => {
  it("renders Permission denied without parties.party.create and the form with it", () => {
    const denied = renderWithQueries(<PartyCreate />, () => undefined, partiesBootstrap());
    expect(textOf(denied)).toContain("You don't have access to customers");
    expect(denied).not.toContain("<form");
    const allowed = renderWithQueries(<PartyCreate />, () => undefined, partiesBootstrap([{ key: "parties.party.create", scope: "company" }]));
    expect(allowed).toContain("<form");
    expect(textOf(allowed)).toContain("Legal name");
    expect(textOf(allowed)).toContain("Default currency");
    expect(textOf(allowed)).toContain("Billing address (optional)");
    expect(controlsWithoutVisibleFocus(allowed)).toEqual([]);
  });

  it("builds a PartyCreate body only when valid, with the address country defaulting to the party's", () => {
    expect(createBodyOf(EMPTY_CREATE)).toBeNull();
    expect(validateCreate(EMPTY_CREATE)).toMatchObject({ legal_name: expect.any(String), country_code: expect.any(String), default_currency: expect.any(String) });
    const form = {
      ...EMPTY_CREATE,
      legal_name: " Nordhaus Interiors GmbH ",
      country_code: "de",
      default_currency: "EUR",
      contact: { name: "Lena Brandt", email: "lena@nordhaus.example", phone: "" },
      address: { line1: "Hafenstrasse 12", line2: "", city: "Hamburg", region: "", postal_code: "20457", country_code: "" },
    };
    expect(createBodyOf(form)).toEqual({
      legal_name: "Nordhaus Interiors GmbH",
      country_code: "DE",
      default_currency: "EUR",
      roles: ["customer"],
      status: "active",
      contacts: [{ name: "Lena Brandt", email: "lena@nordhaus.example", phone: null, is_primary: true }],
      addresses: [{ kind: "billing", line1: "Hafenstrasse 12", line2: null, city: "Hamburg", region: null, postal_code: "20457", country_code: "DE", is_default: true }],
    });
    expect(validateCreate({ ...form, contact: { name: "", email: "x@y.z", phone: "" } })).toHaveProperty("contact.name");
    expect(validateCreate({ ...form, roles: [] })).toHaveProperty("roles");
  });

  it("maps 422 errors onto form fields, including nested contacts and addresses", () => {
    const error = problem(422, "validation_failed", {
      errors: [
        { loc: ["body", "legal_name"], msg: "too short", code: "string_too_short" },
        { loc: ["body", "contacts", 0, "email"], msg: "not an email", code: "string_pattern_mismatch" },
        { loc: ["body", "addresses", 0, "line1"], msg: "required", code: "missing" },
      ],
    });
    expect(fieldErrorsFrom(error)).toEqual({ legal_name: "too short", "contact.email": "not an email", "address.line1": "required" });
    expect(fieldErrorsFrom(new Error("x"))).toEqual({});
  });
});

describe("the Edit drawer model", () => {
  const party = parsePartyDetail(testPartyWire());
  const base = headerFormOf(party);

  it("sends only the dirty fields, trimmed and upper-cased", () => {
    const form = { ...base, legal_name: " Nordhaus Interiors GmbH ", country_code: "at", roles: ["customer", "vendor"] as const };
    expect(dirtyHeaderFields(base, { ...form, roles: [...form.roles] })).toEqual(["country_code", "roles"]);
    expect(headerChanges(base, { ...form, roles: [...form.roles] })).toEqual({ country_code: "AT", roles: ["customer", "vendor"] });
  });

  it("merges a conflict three ways: theirs where I made no change, mine where I did", () => {
    const mine = { ...base, display_name: "Nordhaus" };
    const theirs = { ...base, display_name: "Nordhaus Interiors AG", status: "inactive" as const };
    const merge = mergeHeaderConflict(base, mine, theirs);
    expect(merge.form.display_name).toBe("Nordhaus");
    expect(merge.form.status).toBe("inactive");
    expect(merge.adopted).toEqual(["status"]);
    expect(merge.base).toEqual(theirs);
  });

  it("replaces the contact set with the existing rows plus the new one, moving Primary when asked", () => {
    const contacts = contactsWith(party.contacts, { name: "Mia Roth", email: "mia@nordhaus.example", is_primary: true });
    expect(contacts.map((contact) => [contact.id ?? null, contact.name, contact.is_primary])).toEqual([
      ["c1", "Lena Brandt", false],
      ["c2", "Jonas Weber", false],
      [null, "Mia Roth", true],
    ]);
  });

  it("formats an address block without empty lines", () => {
    expect(addressLines(party.addresses[1]!)).toEqual(["Lagerweg 3", "Halle 2", "Bremen, 28195", "DE"]);
  });

  it("PATCHes with expected_version, the Idempotency-Key and only the dirty fields", async () => {
    const seen: Request[] = [];
    const client = createApiClient({
      baseUrl: "http://127.0.0.1:3050",
      getCsrfToken: () => "csrf",
      fetch: async (request) => {
        seen.push(request.clone());
        return new Response(JSON.stringify(testPartyWire({ version: 4, status: "inactive" })), { status: 200, headers: { "content-type": "application/json" } });
      },
    });
    const updated = await updateParty(TEST_PARTY_ID, { expected_version: 3, status: "inactive" }, "0192a000-0000-7000-8000-0000000000k1", client);
    expect(updated.version).toBe(4);
    const request = seen[0]!;
    expect(request.method).toBe("PATCH");
    expect(new URL(request.url).pathname).toBe(`/api/v1/parties/parties/${TEST_PARTY_ID}`);
    expect(request.headers.get("Idempotency-Key")).toBe("0192a000-0000-7000-8000-0000000000k1");
    expect(await request.json()).toEqual({ expected_version: 3, status: "inactive" });
  });
});

describe("the Sales hub", () => {
  const hubBootstrap = testBootstrap({
    permissions: [
      { key: "sales.quote.read", scope: "own" },
      { key: "sales.quote.create", scope: "own" },
      { key: "sales.enquiry.read", scope: "own" },
      { key: "sales.customer_message.read", scope: "own" },
      { key: "parties.party.read", scope: "company" },
    ],
  });

  it("shows real counts as a fact strip linking to the filtered lists, each Needs-you list and every readable area", () => {
    const html = renderWithQueries(
      <SalesHub />,
      (client) => {
        client.setQueryData(queryKeys.sales.statusCounts(), { draft: 2, internal_review: 1, sent: 0, won: 4, lost: 1 });
        client.setQueryData(queryKeys.sales.quotes({ status: "internal_review", scope: "mine", offset: 0 }), { items: [], total: 0, limit: 25, offset: 0 });
        client.setQueryData(queryKeys.sales.messages({ status: "received", offset: 0 }), { items: [], total: 0, limit: 25, offset: 0 });
        client.setQueryData(queryKeys.sales.enquiries({ status: "received", offset: 0 }), { items: [], total: 0, limit: 25, offset: 0 });
        seedQueryError(client, queryKeys.sales.enquiries({ status: "assigned", offset: 0 }), problem(500, "server_error"));
      },
      hubBootstrap,
    );
    const text = textOf(html);
    expect(html).toContain('href="/sales/quotes?status=draft"');
    expect(html).toContain('href="/sales/quotes?status=internal_review"');
    expect(html).toContain('href="/sales/quotes?status=won"');
    expect(text).toContain("Draft 2");
    expect(text).toContain("In review 1");
    expect(text).toContain("Sent 0");
    expect(text).toContain("Won 4");
    expect(text).not.toContain("Lost");
    expect(text).toContain("No quotes are waiting for a review.");
    expect(text).toContain("Every customer message has a reply.");
    // A failed query shows its own error without hiding the rest.
    expect(text).toContain("couldn't be loaded");
    expect(html).toContain('href="/sales/parties"');
    expect(html).toContain('href="/sales/quotes/new"');
    expect(html).not.toContain("KPI");
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);
  });

  it("hides what the role cannot read and never invents a number", () => {
    const html = renderWithQueries(<SalesHub />, () => undefined, testBootstrap({ permissions: [{ key: "sales.enquiry.read", scope: "own" }] }));
    const text = textOf(html);
    // The area cards follow the exact permission keys (the AreaNav tabs follow the route manifest's prefixes).
    expect(text).not.toContain("Drafts, quotes in review");
    expect(html).not.toContain('href="/sales/parties"');
    expect(html).not.toContain('href="/sales/quotes/new"');
    expect(text).not.toContain("My quotes by status");
    expect(text).not.toContain("Quotes in review");
    expect(text).toContain("Open enquiries");
    expect(text).toContain("Loading");
  });
});
