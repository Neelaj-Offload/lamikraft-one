import { describe, expect, it, vi } from "vitest";
import { createApiClient } from "@/lib/api/client";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { controlsWithoutVisibleFocus, renderWithQueries, seedQueryError, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { supersedePriceItem, type FxPolicy, type FxRate, type PriceListDetail } from "./api";
import { FxRates } from "./fx-rates";
import { PriceListView, PriceLists, priceListHref, priceListStateFrom } from "./price-lists";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/products/price-lists",
  useSearchParams: () => new URLSearchParams(),
}));

const LIST = "0192a000-0000-7000-8000-0000000000e1";
const perms = (...keys: string[]) => testBootstrap({ permissions: keys.map((key) => ({ key, scope: "company" })) });

function list(overrides: Partial<PriceListDetail> = {}): PriceListDetail {
  return {
    id: LIST,
    code: "EXP-EUR-2026",
    name: "Export EUR 2026",
    price_type: "export",
    scope_kind: "standard",
    party: null,
    customer_type: null,
    currency: "EUR",
    valid_from: "2026-01-01",
    valid_to: "2026-12-31",
    status: "active",
    priority: null,
    item_count: 1,
    path: `/products/price-lists/${LIST}`,
    notes: null,
    version: 2,
    activated_at: "2026-06-19T04:30:00Z",
    retired_at: null,
    capabilities: {
      update: { allowed: true },
      add_item: { allowed: false, reason_code: "price_list_not_draft" },
      edit_item: { allowed: false, reason_code: "price_list_not_draft" },
      supersede_item: { allowed: true },
      retire_item: { allowed: true },
      duplicate: { allowed: true },
    },
    allowed_transitions: [{ action: "retire", to_status: "retired", requires_reason: true }],
    ...overrides,
  };
}

const ITEMS = {
  items: [
    {
      id: "i1", product_id: "p1", product_key: "LK-OT-0450", display_sku: "OT-0450", unit_code: "pcs", unit_price: { amount: "24.0000", currency: "EUR" },
      moq: null, notes: null, valid_from: "2026-01-01", valid_to: "2026-12-31", status: "active", superseded_by_item_id: null, version: 1,
    },
  ],
  total: 1,
  limit: 50,
  offset: 0,
};

function renderList(detail: PriceListDetail, bootstrap = perms("pricing.price.read", "pricing.price_list.manage")) {
  return renderWithQueries(
    <PriceListView priceListId={LIST} />,
    (client) => {
      client.setQueryData(queryKeys.pricing.priceList(LIST), detail);
      client.setQueryData(queryKeys.pricing.priceListItems(LIST, { offset: 0, history: false }), ITEMS);
    },
    bootstrap,
  );
}

describe("price lists", () => {
  it("keeps the list filters in the URL", () => {
    expect(priceListStateFrom({ status: "active", offset: "60" })).toEqual({ q: "", status: "active", offset: 50 });
    expect(priceListStateFrom({ status: "nope" }).status).toBeNull();
    expect(priceListHref({ q: "exp", status: "draft" })).toBe("/products/price-lists?q=exp&status=draft");
  });

  it("an active list offers change-from-a-date and retire, never draft edits", () => {
    const html = renderList(list());
    const text = textOf(html);
    expect(text).toContain("Active: prices are immutable");
    expect(text).toContain("Change from a date");
    expect(text).toContain("Retire price");
    expect(text).toContain("Retire list");
    expect(text).toContain("Duplicate as a new draft");
    expect(text).not.toContain("Add a price");
    expect(text).not.toContain("Activate");
    expect(text).toContain("€24.00");
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);
  });

  it("a draft list offers activation, adding and editing prices", () => {
    const text = textOf(
      renderList(
        list({
          status: "draft",
          capabilities: { add_item: { allowed: true }, edit_item: { allowed: true }, supersede_item: { allowed: false }, retire_item: { allowed: true }, duplicate: { allowed: true } },
          allowed_transitions: [
            { action: "activate", to_status: "active", requires_reason: false },
            { action: "retire", to_status: "retired", requires_reason: true },
          ],
        }),
      ),
    );
    expect(text).toContain("Draft: prices can be edited");
    expect(text).toContain("Activate");
    expect(text).toContain("Add a price");
    expect(text).toContain("Edit");
    expect(text).not.toContain("Change from a date");
  });

  it("read-only for people who only read prices; forbidden without pricing access", () => {
    const text = textOf(
      renderList(
        list({ capabilities: { update: { allowed: false, reason_code: "permission_denied" }, supersede_item: { allowed: false, reason_code: "permission_denied" } }, allowed_transitions: [] }),
        perms("pricing.price.read"),
      ),
    );
    expect(text).not.toContain("Change from a date");
    expect(text).not.toContain("Retire list");
    const state = { q: "", status: null, offset: 0 };
    expect(textOf(renderWithQueries(<PriceLists state={state} />, () => undefined, perms("sales.quote.read")))).toContain("You don't have access to Price lists");
    const failed = new ProblemError({ type: "about:blank", title: "Error", status: 500, code: "internal_error", detail: "boom", request_id: "req-p" });
    const errored = renderWithQueries(<PriceLists state={state} />, (c) => seedQueryError(c, queryKeys.pricing.priceLists({ q: null, status: null, offset: 0 }), failed), perms("pricing.price.read"));
    expect(textOf(errored)).toContain("req-p");
  });

  it("supersede sends the new price, its date and the version the person saw", async () => {
    const seen: Request[] = [];
    const client = createApiClient({
      baseUrl: "http://127.0.0.1:3060",
      getCsrfToken: () => "csrf",
      fetch: async (request) => {
        seen.push(request.clone());
        return Response.json({ ...ITEMS.items[0], id: "i2", unit_price: { amount: "26.0000", currency: "EUR" }, valid_from: "2026-11-01" });
      },
    });
    const next = await supersedePriceItem({ id: "i1", version: 1 }, { unit_price: "26", valid_from: "2026-11-01", reason: "Veneer cost" }, client);
    expect(await seen[0]!.json()).toEqual({ unit_price: "26", valid_from: "2026-11-01", reason: "Veneer cost", expected_version: 1 });
    expect(new URL(seen[0]!.url).pathname).toBe("/api/v1/pricing/price-list-items/i1/supersede");
    expect(next.id).toBe("i2");
  });
});

describe("FX rates", () => {
  const rate = (overrides: Partial<FxRate> = {}): FxRate => ({
    id: "fx1", base_currency: "EUR", quote_currency: "USD", rate: "1.085", rate_date: "2026-10-09", source_kind: "bank",
    source_reference: "Demo rate", status: "proposed", proposed_by_name: "Sahil Mehta", proposed_at: "2026-10-12T03:00:00Z",
    decided_by_name: null, decided_at: null, decision_reason: null, is_demo: false, version: 1,
    capabilities: { decide: { allowed: true }, withdraw: { allowed: false, reason_code: "not_requester" } },
    ...overrides,
  });
  const policy: FxPolicy = { conversion_enabled: true, conversion_source_currency: "EUR", max_rate_age_days: 7, version: 0, capabilities: { manage: { allowed: false, reason_code: "permission_denied" } } };

  function render(rates: FxRate[], bootstrap = perms("pricing.fx_rate.read", "pricing.fx_rate.approve")) {
    return textOf(
      renderWithQueries(
        <FxRates />,
        (client) => {
          client.setQueryData(queryKeys.pricing.fxRates({}), { items: rates, total: rates.length, limit: 50, offset: 0 });
          client.setQueryData(queryKeys.pricing.fxPolicy(), policy);
        },
        bootstrap,
      ),
    );
  }

  it("offers approve and reject only to an eligible second person", () => {
    const text = render([rate()]);
    expect(text).toContain("1 EUR = 1.085 USD");
    expect(text).toContain("Approve");
    expect(text).toContain("Reject");
    expect(text).not.toContain("Propose a rate");
    const own = render([rate({ capabilities: { decide: { allowed: false, reason_code: "separation_of_duties" }, withdraw: { allowed: true } } })], perms("pricing.fx_rate.read", "pricing.fx_rate.create"));
    expect(own).toContain("Withdraw");
    expect(own).not.toMatch(/Approve(?!d)/);
    expect(own).toContain("Propose a rate");
  });

  it("shows the policy read-only without manage rights, and empty and forbidden states", () => {
    const text = render([]);
    expect(text).toContain("No FX rates yet.");
    expect(text).toContain("Conversion policy");
    expect(text).not.toMatch(/\bSave\b/);
    expect(textOf(renderWithQueries(<FxRates />, () => undefined, perms("sales.quote.read")))).toContain("You don't have access to FX rates");
  });
});
