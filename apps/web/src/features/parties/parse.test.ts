import { describe, expect, it } from "vitest";
import { parseStatusCounts } from "@/features/sales/parse";
import { parsePartyDetail, parsePartyPage, parsePartySummary, PartiesShapeError } from "./parse";
import { testPartyWire } from "./test-support";

describe("parsePartySummary", () => {
  it("reads a PartySummary and keeps the server's in-app path", () => {
    const party = parsePartySummary(testPartyWire())!;
    expect(party.party_number).toBe("P-00001");
    expect(party.display_name).toBe("Nordhaus Interiors");
    expect(party.legal_name).toBe("Nordhaus Interiors GmbH");
    expect(party.roles).toEqual(["customer"]);
    expect(party.status).toBe("active");
    expect(party.customer_type).toBe("standard");
    expect(party.owner.display_name).toBe("Meera Iyer");
    expect(party.primary_contact).toBe("Lena Brandt");
    expect(party.path).toBe("/sales/parties/0192a000-0000-7000-8000-0000000000p1");
  });

  it("never follows a path that leaves the app and drops unknown enum values", () => {
    const party = parsePartySummary(testPartyWire({ path: "https://evil.example/x", roles: ["customer", "pirate"], status: "weird", customer_type: "vip" }))!;
    expect(party.path).toBe("/sales/parties/0192a000-0000-7000-8000-0000000000p1");
    expect(party.roles).toEqual(["customer"]);
    expect(party.status).toBe("active");
    expect(party.customer_type).toBeNull();
  });

  it("rejects rows without an id or number", () => {
    expect(parsePartySummary({ id: "x" })).toBeNull();
    expect(parsePartySummary(null)).toBeNull();
  });
});

describe("parsePartyDetail", () => {
  it("reads contacts, addresses, tax identifiers, version and capabilities", () => {
    const party = parsePartyDetail(testPartyWire());
    expect(party.version).toBe(3);
    expect(party.contacts.map((contact) => [contact.name, contact.is_primary])).toEqual([
      ["Lena Brandt", true],
      ["Jonas Weber", false],
    ]);
    expect(party.addresses.map((address) => [address.kind, address.city, address.is_default])).toEqual([
      ["billing", "Hamburg", true],
      ["shipping", "Bremen", true],
    ]);
    expect(party.tax_identifiers[0]).toMatchObject({ scheme: "vat", value: "DE123456789", country_code: "DE", verification_status: "unverified" });
    expect(party.capabilities.update?.allowed).toBe(true);
    expect(party.created_at).toBe("2026-10-01T08:00:00Z");
  });

  it("throws when the version is missing (a summary is not a detail)", () => {
    const wire = testPartyWire();
    delete wire.version;
    expect(() => parsePartyDetail(wire)).toThrow(PartiesShapeError);
  });
});

describe("parsePartyPage", () => {
  it("reads Page[PartySummary] and skips unreadable rows", () => {
    const page = parsePartyPage({ items: [testPartyWire(), { id: "broken" }], total: 2, limit: 25, offset: 0 });
    expect(page.items).toHaveLength(1);
    expect(page.total).toBe(2);
  });
});

describe("parseStatusCounts", () => {
  it("keeps only known statuses with integer counts", () => {
    expect(parseStatusCounts({ draft: 3, internal_review: 1, sent: 0, won: 2, bogus: 9, lost: "x" })).toEqual({ draft: 3, internal_review: 1, sent: 0, won: 2 });
  });

  it("rejects a non-object answer", () => {
    expect(() => parseStatusCounts([1, 2])).toThrow();
  });
});
