/**
 * Pricing as the web uses it. Shapes mirror backend/app/modules/pricing/schemas.py
 * (`PriceListSummary`, `PriceListDetail`, `PriceListItemRead`, `ProductPriceRead`,
 * `ProductPrices`, `ProductCostRead`). Guarded fields (the base/add-on breakdown and
 * provenance behind `pricing.price_list.read`, cost behind `pricing.cost.read`) are absent
 * and named in `redacted_fields`; the web shows nothing for them, never a mask.
 */

import type { Capability, Money, Quantity } from "@/features/products/types";

export { type Page } from "@/features/products/types";

export const PRICE_LIST_STATUSES = ["draft", "active", "retired"] as const;
export type PriceListStatus = (typeof PRICE_LIST_STATUSES)[number];

export const PRICE_TYPES = ["domestic", "export", "sample", "distributor"] as const;
export type PriceType = (typeof PRICE_TYPES)[number];

export const PRICE_SCOPES = ["standard", "customer_type", "customer"] as const;
export type PriceScope = (typeof PRICE_SCOPES)[number];

export interface PartyMini {
  id: string;
  party_number: string;
  display_name: string;
}

export interface PriceListSummary {
  id: string;
  code: string;
  name: string;
  price_type: PriceType;
  scope_kind: PriceScope;
  party: PartyMini | null;
  customer_type: string | null;
  currency: string;
  default_unit_code: string | null;
  valid_from: string;
  valid_to: string | null;
  status: PriceListStatus;
  priority: number | null;
  item_count: number;
  path: string;
}

export interface PriceListDetail extends PriceListSummary {
  price_basis: string | null;
  notes: string | null;
  source_kind: string | null;
  source_ref: string | null;
  activated_at: string | null;
  retired_at: string | null;
  version: number;
  capabilities: Readonly<Record<string, Capability>>;
  redacted_fields: string[];
}

export interface PriceListItem {
  id: string;
  price_list_id: string;
  price_list_code: string;
  product_id: string;
  product_key: string;
  display_sku: string | null;
  unit_code: string;
  unit_price: Money;
  final_price: Money | null;
  base_price: Money | null;
  base_price_label: string | null;
  addon_price: Money | null;
  addon_price_label: string | null;
  price_basis: string | null;
  yield_qty_per_board: string | null;
  thickness_mm: string | null;
  source_kind: string | null;
  source_ref: string | null;
  moq: Quantity | null;
  notes: string | null;
  valid_from: string;
  valid_to: string | null;
  status: "active" | "retired";
  superseded_by_item_id: string | null;
  version: number;
  redacted_fields: string[];
}

export interface ProductPrice extends PriceListItem {
  price_list_name: string;
  price_type: PriceType;
  scope_kind: PriceScope;
  party: PartyMini | null;
  customer_type: string | null;
}

export interface ProductCost {
  id: string;
  product_id: string;
  cost_version: number;
  unit_cost: Money | null;
  unit_code: string;
  cost_components: { label: string; amount: string }[] | null;
  source_kind: string;
  effective_from: string;
  recorded_at: string;
  redacted_fields: string[];
}

export interface ProductPrices {
  product_id: string;
  product_key: string;
  on_date: string;
  prices: ProductPrice[];
  /** Only with `pricing.cost.read`; null when absent. */
  current_cost: ProductCost | null;
  redacted_fields: string[];
}
