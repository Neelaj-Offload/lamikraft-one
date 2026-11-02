/** Test-only party payloads shaped like parties/schemas.py `PartyDetail` (Nordhaus Interiors, P-00001). */

export const TEST_PARTY_ID = "0192a000-0000-7000-8000-0000000000p1";

export function testPartyWire(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: TEST_PARTY_ID,
    party_number: "P-00001",
    legal_name: "Nordhaus Interiors GmbH",
    display_name: "Nordhaus Interiors",
    country_code: "DE",
    default_currency: "EUR",
    customer_type: "standard",
    roles: ["customer"],
    status: "active",
    owner: { id: "0192a000-0000-7000-8000-00000000000a", display_name: "Meera Iyer" },
    branch_id: null,
    primary_contact: "Lena Brandt",
    updated_at: "2026-10-12T03:00:00Z",
    path: `/sales/parties/${TEST_PARTY_ID}`,
    contacts: [
      { id: "c1", name: "Lena Brandt", job_title: "Purchasing", email: "lena@nordhaus.example", phone: "+49 40 123456", is_primary: true },
      { id: "c2", name: "Jonas Weber", job_title: null, email: null, phone: null, is_primary: false },
    ],
    addresses: [
      { id: "a1", kind: "billing", line1: "Hafenstrasse 12", line2: null, city: "Hamburg", region: null, postal_code: "20457", country_code: "DE", is_default: true },
      { id: "a2", kind: "shipping", line1: "Lagerweg 3", line2: "Halle 2", city: "Bremen", region: null, postal_code: "28195", country_code: "DE", is_default: true },
    ],
    tax_identifiers: [{ id: "t1", scheme: "vat", value: "DE123456789", country_code: "DE", verification_status: "unverified" }],
    version: 3,
    created_at: "2026-10-01T08:00:00Z",
    archived_at: null,
    capabilities: { update: { allowed: true, reason_code: null } },
    allowed_transitions: [],
    ...overrides,
  };
}
