"use client";

/**
 * Data hooks for the Products area (catalogue, product record, completeness, taxonomy, price
 * lists). Every call goes through the old app's API modules and reuses its query keys, so the
 * caches of both apps stay interchangeable. Money and quantities stay decimal strings.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import {
  deleteMedia,
  fetchCategories,
  fetchHistory,
  fetchMedia,
  fetchProduct as fetchProductRecord,
  fetchReferences,
  mediaCommand,
  reorderTaxonomy,
  setArchived,
  uploadMedia,
} from "@/features/catalogue/api";
import type { CategoryRead, MediaRead, ProductDetail as ProductRecord, SubcategoryRead } from "@/features/catalogue/types";
import { fetchPriceListItems, fetchPriceLists, fetchProductCosts, fetchProductPrices } from "@/features/price-lists/api";
import { priceListItemsParams, priceListListParams, type PriceListItemsState, type PriceListListState } from "@/features/price-lists/list-state";
import { fetchItemHistory, fetchPriceList } from "@/features/pricing/api";
import { fetchCompleteness, fetchProductFacets, fetchProductStats, PRODUCTS_PATH } from "@/features/products/api";
import { productFilterParams, productListParams, type ProductListState } from "@/features/products/list-state";
import { isObject, pageOf, parseProductDetail, parseProductSummary, str } from "@/features/products/parse";
import type { Page, ProductDetail, ProductSummary } from "@/features/products/types";
import { api, requestUntyped } from "@/lib/api/client";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";

export type { CategoryRead, MediaRead, ProductRecord, SubcategoryRead };

export const PRODUCTS_READ = "catalogue.product.read";
export const PRODUCTS_CREATE = "catalogue.product.create";
export const PRODUCTS_EXPORT = "catalogue.product.export";
export const TAXONOMY_MANAGE = "catalogue.taxonomy.manage";
export const PRICES_READ = "pricing.price.read";
export const COST_READ = "pricing.cost.read";
export const PRICE_LIST_MANAGE = "pricing.price_list.manage";

/** A catalogue row with the product's own photo when it has one. */
export interface CatalogueProduct extends ProductSummary {
  primary_image: { url: string; alt_text: string | null } | null;
}

/** Only same-origin API paths are shown as images; anything else is ignored. */
function thumbOf(raw: unknown): CatalogueProduct["primary_image"] {
  if (!isObject(raw) || !isObject(raw.primary_image)) return null;
  const url = str(raw.primary_image.url);
  return url && url.startsWith("/api/") ? { url, alt_text: str(raw.primary_image.alt_text) } : null;
}

async function fetchCatalogue(state: ProductListState, signal?: AbortSignal): Promise<Page<CatalogueProduct>> {
  const raw = await requestUntyped<unknown>(api, "get", PRODUCTS_PATH, { params: { query: productListParams(state) }, signal });
  return pageOf(raw, (value) => {
    const summary = parseProductSummary(value);
    return summary ? { ...summary, primary_image: thumbOf(value) } : null;
  });
}

export function useCatalogue(state: ProductListState, enabled = true) {
  return useQuery({
    queryKey: queryKeys.catalogue.products(productListParams(state)),
    queryFn: ({ signal }) => fetchCatalogue(state, signal),
    enabled,
    placeholderData: (previous) => previous,
  });
}

export function useCatalogueFacets(state: ProductListState, enabled = true) {
  return useQuery({
    queryKey: queryKeys.catalogue.facets(productFilterParams(state)),
    queryFn: ({ signal }) => fetchProductFacets(state, signal),
    enabled,
    placeholderData: (previous) => previous,
  });
}

export function useCatalogueStats(enabled = true) {
  return useQuery({ queryKey: queryKeys.catalogue.stats(), queryFn: ({ signal }) => fetchProductStats(signal), enabled });
}

export function useCompleteness(enabled = true) {
  return useQuery({ queryKey: queryKeys.catalogue.completeness(), queryFn: ({ signal }) => fetchCompleteness(signal), enabled });
}

export interface LoadedProduct {
  /** The record exactly as the server sent it: the editors round-trip every field from this. */
  raw: ProductRecord;
  /** The parsed record the views read. */
  product: ProductDetail;
}

function selectRecord(raw: ProductRecord): LoadedProduct {
  return { raw, product: parseProductDetail(raw) };
}

export function useProduct(productId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.catalogue.product(productId),
    queryFn: ({ signal }) => fetchProductRecord(productId, signal),
    select: selectRecord,
    enabled,
  });
}

/** Refreshes everything a catalogue write can touch; pass the saved record to show it at once. */
export function useCatalogueRefresh() {
  const queryClient = useQueryClient();
  return useCallback(
    (next?: ProductRecord) => {
      if (next) queryClient.setQueryData(queryKeys.catalogue.product(next.id), next);
      for (const key of invalidationMap["catalogue.changed"]) void queryClient.invalidateQueries({ queryKey: key });
    },
    [queryClient],
  );
}

export function useArchiveProduct(product: Pick<ProductDetail, "id" | "version">) {
  const refresh = useCatalogueRefresh();
  return useMutation({
    mutationFn: ({ archived, reason }: { archived: boolean; reason: string | null }) => setArchived(product.id, archived, product.version, reason),
    onSuccess: (next) => refresh(next),
  });
}

export function useCategories(includeInactive: boolean, enabled = true) {
  return useQuery({
    queryKey: queryKeys.catalogue.categories(includeInactive),
    queryFn: ({ signal }) => fetchCategories(includeInactive, signal),
    enabled,
  });
}

export function useTaxonomyReferences(kind: "category" | "subcategory", id: string) {
  return useQuery({ queryKey: queryKeys.catalogue.references(kind, id), queryFn: () => fetchReferences(kind, id) });
}

export function useReorderTaxonomy() {
  const refresh = useCatalogueRefresh();
  return useMutation({
    mutationFn: ({ ids, parent }: { ids: string[]; parent: string | null }) => reorderTaxonomy(ids, parent),
    onSuccess: () => refresh(),
  });
}

export function useProductMedia(productId: string, includeDeleted: boolean) {
  return useQuery({
    queryKey: queryKeys.catalogue.media(productId, includeDeleted),
    queryFn: ({ signal }) => fetchMedia(productId, includeDeleted, signal),
  });
}

export function useUploadMedia(productId: string) {
  const refresh = useCatalogueRefresh();
  return useMutation({
    mutationFn: ({ files, mediaType }: { files: File[]; mediaType: MediaRead["media_type"] }) =>
      Promise.all(files.map((file) => uploadMedia(productId, file, mediaType))),
    onSuccess: () => refresh(),
  });
}

export function useMediaCommand() {
  const refresh = useCatalogueRefresh();
  return useMutation({
    mutationFn: ({ item, action, reason }: { item: MediaRead; action: "make-primary" | "restore" | "delete"; reason?: string }) =>
      action === "delete" ? deleteMedia(item, reason ?? "") : mediaCommand(item, action),
    onSuccess: () => refresh(),
  });
}

export function useProductHistory(productId: string) {
  return useQuery({ queryKey: queryKeys.catalogue.history(productId), queryFn: ({ signal }) => fetchHistory(productId, signal) });
}

export function useProductPrices(productId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.pricing.productPrices(productId),
    queryFn: ({ signal }) => fetchProductPrices(productId, signal),
    enabled,
  });
}

/** Cost history. The server audits every read, so ask only for people who hold `pricing.cost.read`. */
export function useProductCosts(productId: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.pricing.productCosts(productId),
    queryFn: ({ signal }) => fetchProductCosts(productId, signal),
    enabled,
  });
}

export function usePriceLists(state: PriceListListState, enabled = true) {
  return useQuery({
    queryKey: queryKeys.pricing.priceLists(priceListListParams(state)),
    queryFn: ({ signal }) => fetchPriceLists(state, signal),
    enabled,
    placeholderData: (previous) => previous,
  });
}

/** The price list as the server sends it, with `capabilities` and `allowed_transitions`. */
export function usePriceList(priceListId: string) {
  return useQuery({ queryKey: queryKeys.pricing.priceList(priceListId), queryFn: ({ signal }) => fetchPriceList(priceListId, signal) });
}

export function usePriceListItems(priceListId: string, state: PriceListItemsState) {
  return useQuery({
    queryKey: queryKeys.pricing.priceListItems(priceListId, priceListItemsParams(state)),
    queryFn: ({ signal }) => fetchPriceListItems(priceListId, state, signal),
    placeholderData: (previous) => previous,
  });
}

export function usePriceItemHistory(itemId: string) {
  return useQuery({ queryKey: queryKeys.pricing.itemHistory(itemId), queryFn: ({ signal }) => fetchItemHistory(itemId, signal) });
}
