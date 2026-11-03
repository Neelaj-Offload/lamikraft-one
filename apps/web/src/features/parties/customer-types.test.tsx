import { describe, expect, it, vi } from "vitest";
import { queryKeys } from "@/lib/api/query-keys";
import { renderWithQueries, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { CustomerTypesManager } from "./customer-types";
import { parsePartyDetail } from "./parse";
import { PartyDetail } from "./party-detail";
import { TEST_PARTY_ID, testPartyWire } from "./test-support";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/settings/customer-types",
  useSearchParams: () => new URLSearchParams(),
}));

const sales = () =>
  testBootstrap({ permissions: ["parties.party.read", "parties.party.create", "parties.party.update"].map((key) => ({ key, scope: "own" })) });
const admin = () =>
  testBootstrap({ permissions: ["parties.party.read", "parties.customer_type.manage", "parties.party.archive"].map((key) => ({ key, scope: "company" })) });

const TYPES = [
  { id: "t1", code: "standard", label: "Standard", description: null, display_order: 10, is_active: true, is_system: true, party_count: 3, version: 1, capabilities: { update: { allowed: true, reason_code: null } } },
  { id: "t2", code: "dealer", label: "Dealer", description: null, display_order: 20, is_active: false, is_system: true, party_count: 1, version: 2, capabilities: { update: { allowed: true, reason_code: null } } },
];

describe("customer types and party archive (catalogue lane, merged)", () => {
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

  it("the customer record offers Archive or Restore only when the server allows it", () => {
    const allowed = parsePartyDetail(testPartyWire({ capabilities: { update: { allowed: true, reason_code: null }, archive: { allowed: true, reason_code: null }, restore: { allowed: false, reason_code: "not_archived" } } }));
    const seedWith = (party: ReturnType<typeof parsePartyDetail>) => (c: import("@tanstack/react-query").QueryClient) => c.setQueryData(queryKeys.parties.party(TEST_PARTY_ID), party);
    const text = textOf(renderWithQueries(<PartyDetail partyId={TEST_PARTY_ID} />, seedWith(allowed), admin()));
    expect(text).toContain("Archive");
    expect(text).not.toContain("Restore");
    const denied = parsePartyDetail(testPartyWire({ capabilities: { update: { allowed: false, reason_code: "permission_denied" }, archive: { allowed: false, reason_code: "permission_denied" } } }));
    const plain = textOf(renderWithQueries(<PartyDetail partyId={TEST_PARTY_ID} />, seedWith(denied), sales()));
    expect(plain).not.toMatch(/\bArchive\b(?!d)/);
  });
});
