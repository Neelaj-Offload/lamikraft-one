import { describe, expect, it, vi } from "vitest";
import { queryKeys } from "@/lib/api/query-keys";
import { renderWithQueries, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import type { Sample, SampleLineage } from "./api";
import { lineageRows } from "./lineage";
import { SampleView } from "./samples";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/sales/samples",
  useSearchParams: () => new URLSearchParams(),
}));

const ID = "0192a000-0000-7000-8000-0000000000f1";
const perms = (...keys: string[]) => testBootstrap({ permissions: keys.map((key) => ({ key, scope: "own" })) });

const sample = (overrides: Partial<Sample> = {}): Sample => ({
  id: ID, sample_number: "SMP-2026-0001", party: { id: "p1", party_number: "P-00001", display_name: "Nordhaus Interiors GmbH", country_code: "DE" },
  owner: { id: "u1", display_name: "Meera Iyer" }, quote_id: "q1", quote_number: "LK-QT-2026-0009", custom_product_id: "cp1", custom_code: "CP-0001",
  product_id: null, description: "Walnut tray variant", quantity: "2.000000", unit_code: "pcs", status: "requested", requested_on: "2026-10-12",
  dispatched_at: null, dispatch_reference: null, challan_id: null, delivered_at: null, delivery_evidence_kind: null, feedback: null,
  feedback_outcome: null, feedback_at: null, closed_at: null, close_reason: null, notes: null, updated_at: "2026-10-12T03:00:00Z", version: 1,
  path: `/sales/samples/${ID}`,
  capabilities: { update: { allowed: true }, transition: { allowed: true }, link_challan: { allowed: true } },
  allowed_transitions: [],
  ...overrides,
});

const lineage = (overrides: Partial<SampleLineage> = {}): SampleLineage => ({
  sample_id: ID, sample_number: "SMP-2026-0001", status: "requested",
  custom_product: { kind: "custom_product", state: "linked", id: "cp1", label: "CP-0001", title: "Walnut tray variant", status: "sampling", path: "/sales/custom-products/cp1", facts: {} },
  spec_revision: null,
  quote: { kind: "quote", state: "linked", id: "q1", label: "LK-QT-2026-0009", title: null, status: "issued", path: "/sales/quotes/q1", facts: {} },
  challan: { kind: "challan", state: "not_visible", id: null, label: null, title: null, status: null, path: null, facts: {} },
  product: null,
  related_samples: [{ kind: "sample", state: "linked", id: "s2", label: "SMP-2026-0002", title: "Second finish", status: "requested", path: "/sales/samples/s2", facts: {} }],
  timeline: [
    { at: "2026-10-10T04:00:00Z", on: "2026-10-10", kind: "custom_product_created", label: "CP-0001 created", ref_kind: "custom_product" },
    { at: "2026-10-12T03:00:00Z", on: "2026-10-12", kind: "sample_requested", label: "SMP-2026-0001 requested", ref_kind: "sample" },
  ],
  missing: [],
  ...overrides,
});

describe("sample lineage", () => {
  it("orders the links and keeps missing ones visible", () => {
    const rows = lineageRows(lineage({ challan: null, missing: ["challan"] }));
    expect(rows.map((r) => [r.kind, r.missing])).toEqual([["custom_product", false], ["quote", false], ["challan", true]]);
  });

  it("shows each link through its own scope, siblings and the timeline; link only with the capability", () => {
    const seed = (s: Sample, view: SampleLineage) => (c: Parameters<Parameters<typeof renderWithQueries>[1]>[0]) => {
      c.setQueryData(queryKeys.sales.sample(ID), s);
      c.setQueryData(queryKeys.sales.sampleLineage(ID), view);
    };
    const text = textOf(renderWithQueries(<SampleView sampleId={ID} />, seed(sample(), lineage()), perms("sales.sample.read", "challans.challan.read")));
    expect(text).toContain("Lineage");
    expect(text).toContain("CP-0001");
    expect(text).toContain("LK-QT-2026-0009");
    expect(text).toContain("Linked, but outside what you can see");
    expect(text).toContain("SMP-2026-0002");
    expect(text).toContain("CP-0001 created");
    expect(text).toContain("Link a delivery challan");
    const dispatched = sample({ status: "dispatched", challan_id: "c1", capabilities: { update: { allowed: true }, transition: { allowed: true }, link_challan: { allowed: false, reason_code: "sample_not_requested" } } });
    const linked = lineage({ challan: { kind: "challan", state: "linked", id: "c1", label: "DC-2026-0004", title: null, status: "issued", path: "/operations/challans/c1", facts: { challan_type: "sample" } } });
    const after = textOf(renderWithQueries(<SampleView sampleId={ID} />, seed(dispatched, linked), perms("sales.sample.read")));
    expect(after).toContain("DC-2026-0004");
    expect(after).not.toContain("Link a delivery challan");
    expect(after).not.toContain("Change the challan");
  });
});
