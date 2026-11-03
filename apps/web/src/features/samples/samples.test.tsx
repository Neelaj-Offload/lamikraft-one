import { describe, expect, it, vi } from "vitest";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { renderWithQueries, seedQueryError, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { sampleTransitionBody, type Sample } from "./api";
import { SampleList, sampleListHref, sampleListStateFrom, SampleView } from "./samples";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/sales/samples",
  useSearchParams: () => new URLSearchParams(),
}));

const ID = "0192a000-0000-7000-8000-0000000000f1";
const perms = (...keys: string[]) => testBootstrap({ permissions: keys.map((key) => ({ key, scope: "own" })) });

const sample = (overrides: Partial<Sample> = {}): Sample => ({
  id: ID,
  sample_number: "SMP-2026-0001",
  party: { id: "p1", party_number: "P-00001", display_name: "Nordhaus Interiors GmbH", country_code: "DE" },
  owner: { id: "u1", display_name: "Meera Iyer" },
  quote_id: "q1",
  quote_number: "LK-QT-2026-0009",
  custom_product_id: null,
  custom_code: null,
  product_id: null,
  description: "Oak tray finish chips",
  quantity: "2.000000",
  unit_code: "pcs",
  status: "requested",
  requested_on: "2026-10-12",
  dispatched_at: null,
  dispatch_reference: null,
  challan_id: null,
  delivered_at: null,
  delivery_evidence_kind: null,
  feedback: null,
  feedback_outcome: null,
  feedback_at: null,
  closed_at: null,
  close_reason: null,
  notes: null,
  updated_at: "2026-10-12T03:00:00Z",
  version: 1,
  path: `/sales/samples/${ID}`,
  capabilities: { update: { allowed: true }, transition: { allowed: true } },
  allowed_transitions: [
    { action: "dispatch", to_status: "dispatched", requires_reason: false },
    { action: "cancel", to_status: "cancelled", requires_reason: true },
  ],
  ...overrides,
});

describe("samples", () => {
  it("keeps the list filters in the URL", () => {
    expect(sampleListStateFrom({ status: "delivered", q: "dhl" })).toEqual({ q: "dhl", status: "delivered", offset: 0 });
    expect(sampleListHref({ status: "closed" })).toBe("/sales/samples?status=closed");
  });

  it("lists samples with their lineage; New only with create; empty, error and forbidden states", () => {
    const state = { q: "", status: null, offset: 0 };
    const key = queryKeys.sales.samples({ q: null, status: null, offset: 0 });
    const text = textOf(renderWithQueries(<SampleList state={state} />, (c) => c.setQueryData(key, { items: [sample()], total: 1, limit: 25, offset: 0 }), perms("sales.sample.read", "sales.sample.create")));
    expect(text).toContain("SMP-2026-0001");
    expect(text).toContain("LK-QT-2026-0009");
    expect(text).toContain("New sample");
    expect(textOf(renderWithQueries(<SampleList state={state} />, (c) => c.setQueryData(key, { items: [], total: 0, limit: 25, offset: 0 }), perms("sales.sample.read")))).not.toContain("New sample");
    const failed = new ProblemError({ type: "about:blank", title: "Error", status: 500, code: "internal_error", detail: "boom", request_id: "req-s" });
    expect(textOf(renderWithQueries(<SampleList state={state} />, (c) => seedQueryError(c, key, failed), perms("sales.sample.read")))).toContain("req-s");
    expect(textOf(renderWithQueries(<SampleList state={state} />, () => undefined, perms("sales.quote.read")))).toContain("You don't have access to Samples");
  });

  it("offers only the server's next steps and records what each needs", () => {
    const text = textOf(renderWithQueries(<SampleView sampleId={ID} />, (c) => c.setQueryData(queryKeys.sales.sample(ID), sample()), perms("sales.sample.read")));
    expect(text).toContain("Mark dispatched");
    expect(text).toContain("Cancel sample");
    expect(text).not.toContain("Mark delivered");
    const closed = textOf(renderWithQueries(<SampleView sampleId={ID} />, (c) => c.setQueryData(queryKeys.sales.sample(ID), sample({ status: "closed", allowed_transitions: [] })), perms("sales.sample.read")));
    expect(closed).toContain("Nothing more to record for this sample.");
    expect(sampleTransitionBody({ version: 4 }, { action: "dispatch", dispatch_reference: "  DHL 7781 ", reason: " " })).toEqual({
      action: "dispatch",
      expected_version: 4,
      dispatch_reference: "DHL 7781",
    });
  });
});
