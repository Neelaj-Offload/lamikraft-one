/**
 * Stock by category and factory work in progress (module 4, spec 2026-11-25-products-stock-design.md):
 * - GET  /api/v1/inventory/stock-by-category          per product and warehouse: inventory, sample, exhibition, on order
 * - GET  /api/v1/inventory/stock-by-category/totals   company totals per category
 * - POST /api/v1/inventory/relocations                move stock between categories (internal -> internal)
 * - POST /api/v1/inventory/opening-batches (+ /submit) opening stock into a category, approved by a second person
 * - GET  /api/v1/procurement/factory-orders           open purchase-order lines for finished products
 * - POST /api/v1/catalogue/products/variants          the design builder (decors x sizes)
 */

import { useQuery } from "@tanstack/react-query";
import { api, idempotencyHeaders, requestUntyped, type ApiClient } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import type { components } from "@/lib/api/schema";

type S = components["schemas"];
export type CategoryRow = S["CategoryRow"];
export type FactoryOrderLine = S["FactoryOrderLine"];
export type StockCategory = "inventory" | "sample" | "exhibition";
export type Market = "domestic" | "export";
export type VariantBuildResult = S["VariantBuildResult"];
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export const CATEGORY_PAGE_SIZE = 50;
export const CATEGORY_INVALIDATE = [queryKeys.inventory.all(), ["stock-categories"] as const, ["factory-orders"] as const] as const;

export interface CategoryQuery {
  q?: string;
  warehouse_id?: string | null;
  market?: Market | null;
  category?: StockCategory | null;
  design?: string | null;
  offset?: number;
}

function categoryParams(q: CategoryQuery): Record<string, string | number | undefined> {
  return {
    q: q.q?.trim() || undefined,
    warehouse_id: q.warehouse_id || undefined,
    market: q.market || undefined,
    category: q.category || undefined,
    design: q.design?.trim() || undefined,
    offset: q.offset ?? 0,
    limit: CATEGORY_PAGE_SIZE,
  };
}

export function useStockByCategory(q: CategoryQuery) {
  const params = categoryParams(q);
  return useQuery({
    queryKey: ["stock-categories", "rows", params] as const,
    queryFn: ({ signal }) => requestUntyped<Page<CategoryRow>>(api, "get", "/api/v1/inventory/stock-by-category", { params: { query: params }, signal }),
  });
}

export function useCategoryTotals(q: CategoryQuery) {
  const params = { warehouse_id: q.warehouse_id || undefined, market: q.market || undefined, design: q.design?.trim() || undefined };
  return useQuery({
    queryKey: ["stock-categories", "totals", params] as const,
    queryFn: ({ signal }) =>
      requestUntyped<Record<StockCategory, string>>(api, "get", "/api/v1/inventory/stock-by-category/totals", { params: { query: params }, signal }),
  });
}

export function useFactoryOrders(offset = 0, enabled = true) {
  return useQuery({
    queryKey: ["factory-orders", { offset }] as const,
    queryFn: ({ signal }) =>
      requestUntyped<Page<FactoryOrderLine>>(api, "get", "/api/v1/procurement/factory-orders", { params: { query: { offset, limit: 50 } }, signal }),
    enabled,
  });
}

export function relocateStock(
  body: { product_id: string; from_location_id: string; to_location_id: string; quantity: string; unit: string },
  key: string,
  client: ApiClient = api,
): Promise<unknown> {
  return requestUntyped<unknown>(client, "post", "/api/v1/inventory/relocations", { body, headers: idempotencyHeaders(key) });
}

export interface OpeningLine {
  product_id: string;
  quantity: string;
  location_id: string;
  lot_code?: string | null;
  late_opening?: boolean;
}

/** Create an opening batch and submit it for a second person's approval; returns the batch id. */
export async function createAndSubmitOpening(
  body: { warehouse_id: string; notes?: string | null; lines: OpeningLine[] },
  key: string,
  client: ApiClient = api,
): Promise<{ id: string; path?: string }> {
  const batch = await requestUntyped<{ id: string; version: number; path?: string }>(client, "post", "/api/v1/inventory/opening-batches", {
    body,
    headers: idempotencyHeaders(key),
  });
  await requestUntyped<unknown>(client, "post", `/api/v1/inventory/opening-batches/${encodeURIComponent(batch.id)}/submit` as `/api/v1/${string}`, {
    body: { expected_version: batch.version },
    headers: idempotencyHeaders(`${key}:submit`),
  });
  return batch;
}

export interface DesignInput {
  design_no: string;
  design_name: string;
  category_id: string;
  subcategory_id?: string | null;
  product_type?: string | null;
  decors: { decor_no: string; decor_name?: string | null }[];
  sizes: { code: string; label: string; length_mm?: string | null; width_mm?: string | null }[];
  dry_run?: boolean;
}

export function buildVariants(body: DesignInput, client: ApiClient = api): Promise<VariantBuildResult> {
  return requestUntyped<VariantBuildResult>(client, "post", "/api/v1/catalogue/products/variants", { body });
}
