import { describe, expect, it, vi } from "vitest";
import { queryKeys } from "@/lib/api/query-keys";
import { renderWithQueries, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { partyListHref, partyListStateFrom, partyPatch, type PartyDetail } from "./api";
import { CustomerTypesManager, PartyDetailView, PartyList } from "./parties";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/sales/parties",
  useSearchParams: () => new URLSearchParams(),
}));

const PARTY = "0192a000-0000-7000-8000-0000000000c9";
const sales = () =>
  testBootstrap({ permissions: ["parties.party.read", "parties.party.create", "parties.party.update"].map((key) => ({ key, scope: "own" })) });
const admin = () =>
  testBootstrap({ permissions: ["parties.party.read", "parties.customer_type.manage"].map((key) => ({ key, scope: "company" })) });

const TYPES = [
  { id: "t1", code: "standard", label: "Standard", description: null, display_order: 10, is_active: true, is_system: true, party_count: 3, version: 1, capabilities: { update: { allowed: true, reason_code: null } } },
  { id: "t2", code: "dealer", label: "Dealer", description: null, display_order: 20, is_active: false, is_system: true, party_count: 1, version: 2, capabilities: { update: { allowed: true, reason_code: null } } },
];

function party(overrides: Partial<PartyDetail> = {}): PartyDetail {
  return {
    id: PARTY,
    party_number: "P-00001",
    legal_name: "Nordhaus Interiors GmbH",
    display_name: "Nordhaus Interiors",
    country_code: "DE",
    default_currency: "EUR",
    customer_type: "dealer",
    roles: ["customer"],
    status: "active",
    owner: { id: "u1", display_name: "Meera Iyer" },
    primary_contact: "Lena Brandt",
    updated_at: "2026-10-12T03:25:00Z",
    path: `/sales/parties/${PARTY}`,
    contacts: [{ id: "c1", name: "Lena Brandt", job_title: null, email: "lena@example.test", phone: null, is_primary: true }],
    addresses: [{ id: "a1", kind: "billing", line1: "Hafenstrasse 1", line2: null, city: "Hamburg", region: null, postal_code: "20457", country_code: "DE", is_default: true }],
    tax_identifiers: [],
    version: 4,
    created_at: "2026-06-01T03:25:00Z",
    archived_at: null,
    capabilities: { update: { allowed: true, reason_code: null }, archive: { allowed: false, reason_code: "permission_denied" }, restore: { allowed: false, reason_code: "not_archived" } },
    ...overrides,
  };
}

describe("party list state and edit body", () => {
  it("keeps filters in the URL and ignores unknown values", () => {
    const state = partyListStateFrom({ q: "nord", role: "vendor", type: "Bad Type", offset: "30" });
    expect(state).toEqual({ q: "nord", role: "vendor", customerType: null, archived: false, offset: 25 });
    expect(partyListHref({ ...state, customerType: "dealer" })).toBe("/sales/parties?q=nord&role=vendor&type=dealer&offset=25");
  });

  it("sends changed header fields, the version and the full child lists", () => {
    const p = party();
    const body = partyPatch(
      p,
      { display_name: "Nordhaus", legal_name: p.legal_name, country_code: "de", default_currency: "EUR", customer_type: "", status: "active" },
      [...p.contacts, { name: "  ", job_title: null, email: null, phone: null, is_primary: false }],
      p.addresses,
    );
    expect(body).toMatchObject({ expected_version: 4, display_name: "Nordhaus", customer_type: null });
    expect(body).not.toHaveProperty("country_code");
    expect((body.contacts as unknown[]).length).toBe(1); // blank rows are dropped
  });
});

describe("party screens", () => {
  it("list shows rows with customer-type labels; New party only with create", () => {
    const state = partyListStateFrom({});
    const seed = (c: import("@tanstack/react-query").QueryClient) => {
      c.setQueryData(queryKeys.parties.list({ q: "", role: null, type: null, archived: false, offset: 0 }), { items: [party()], total: 1, limit: 25, offset: 0 });
      c.setQueryData(queryKeys.parties.customerTypes(), TYPES);
    };
    const text = textOf(renderWithQueries(<PartyList state={state} />, seed, sales()));
    expect(text).toContain("P-00001");
    expect(text).toContain("Dealer");
    expect(text).toContain("New party");
    expect(textOf(renderWithQueries(<PartyList state={state} />, seed, admin()))).not.toContain("New party");
  });

  it("detail shows contacts and addresses; archive only when the server allows it", () => {
    const html = renderWithQueries(
      <PartyDetailView partyId={PARTY} />,
      (c) => {
        c.setQueryData(queryKeys.parties.party(PARTY), party());
        c.setQueryData(queryKeys.parties.customerTypes(), TYPES);
      },
      sales(),
    );
    const text = textOf(html);
    expect(text).toContain("Lena Brandt (primary)");
    expect(text).toContain("Hafenstrasse 1, 20457 Hamburg, DE");
    expect(text).toContain("Edit");
    expect(text).not.toContain("Archive");
  });

  it("customer types: manage controls only with the manage key", () => {
    const seed = (c: import("@tanstack/react-query").QueryClient) => c.setQueryData(queryKeys.parties.customerTypes(), TYPES);
    const managed = textOf(renderWithQueries(<CustomerTypesManager />, seed, admin()));
    expect(managed).toContain("Built in");
    expect(managed).toContain("Activate"); // dealer is inactive
    expect(managed).toContain("Add type");
    const readOnly = textOf(renderWithQueries(<CustomerTypesManager />, seed, sales()));
    expect(readOnly).not.toContain("Add type");
    expect(readOnly).not.toContain("Deactivate");
  });
});
