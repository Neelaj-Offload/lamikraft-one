/**
 * Catalogue API adapter (INTERIM(api-generate): untyped calls until the generated schema has the Slice-2 routes).
 * Paths and operationIds follow `backend/app/modules/catalogue/router.py`.
 */

import { api, idempotencyHeaders, requestUntyped, type ApiClient } from "@/lib/api/client";
import { ProblemError } from "@/lib/api/errors";
import { productFilterQuery, productListQuery, type ProductListState } from "./list-state";
import type {
  CategoryRead,
  CompletenessSummary,
  HistoryEntry,
  LookupRead,
  MediaGroups,
  MediaRead,
  Page,
  ProductDetail,
  ProductFacets,
  ProductStats,
  ProductSummary,
  ProductWriteResult,
  TaxonomyReferences,
} from "./types";

export const CATALOGUE = "/api/v1/catalogue";
const product = (id: string): `/api/v1/${string}` => `${CATALOGUE}/products/${encodeURIComponent(id)}`;

export function fetchProducts(state: ProductListState, signal?: AbortSignal, client: ApiClient = api): Promise<Page<ProductSummary>> {
  return requestUntyped(client, "get", `${CATALOGUE}/products`, { params: { query: productListQuery(state) }, signal });
}

export function fetchFacets(state: ProductListState, signal?: AbortSignal, client: ApiClient = api): Promise<ProductFacets> {
  return requestUntyped(client, "get", `${CATALOGUE}/products/facets`, { params: { query: productFilterQuery(state) }, signal });
}

export function fetchStats(signal?: AbortSignal, client: ApiClient = api): Promise<ProductStats> {
  return requestUntyped(client, "get", `${CATALOGUE}/products/stats`, { signal });
}

export function fetchProduct(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<ProductDetail> {
  return requestUntyped(client, "get", product(id), { signal });
}

export function fetchProductByKey(key: string, signal?: AbortSignal, client: ApiClient = api): Promise<ProductDetail> {
  return requestUntyped(client, "get", `${CATALOGUE}/products/lookup`, { params: { query: { key } }, signal });
}

export function fetchCategories(includeInactive: boolean, signal?: AbortSignal, client: ApiClient = api): Promise<CategoryRead[]> {
  return requestUntyped(client, "get", `${CATALOGUE}/categories`, { params: { query: { include_inactive: includeInactive } }, signal });
}

export function fetchCompleteness(signal?: AbortSignal, client: ApiClient = api): Promise<CompletenessSummary> {
  return requestUntyped(client, "get", `${CATALOGUE}/completeness`, { signal });
}

export function fetchHistory(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<Page<HistoryEntry>> {
  return requestUntyped(client, "get", `${product(id)}/history`, { signal });
}

export function fetchMedia(id: string, includeDeleted: boolean, signal?: AbortSignal, client: ApiClient = api): Promise<MediaGroups> {
  return requestUntyped(client, "get", `${product(id)}/media`, { params: { query: { include_deleted: includeDeleted } }, signal });
}

/** Product export link (a plain same-origin download; the server writes the CSV). */
export function productExportHref(state: ProductListState): string {
  const query = new URLSearchParams(Object.entries(productFilterQuery(state)).map(([k, v]) => [k, String(v)]));
  const search = query.toString();
  return `${CATALOGUE}/products/export.csv${search ? `?${search}` : ""}`;
}

// ---- writes ---------------------------------------------------------------------------------------------------------
export function createProduct(body: Record<string, unknown>, idempotencyKey: string, client: ApiClient = api): Promise<ProductWriteResult> {
  return requestUntyped(client, "post", `${CATALOGUE}/products`, { body, headers: idempotencyHeaders(idempotencyKey) });
}

export function updateProduct(id: string, body: Record<string, unknown>, client: ApiClient = api): Promise<ProductWriteResult> {
  return requestUntyped(client, "patch", product(id), { body });
}

export function putSection(
  id: string,
  section: "specification" | "packaging",
  version: number,
  values: Record<string, unknown>,
  client: ApiClient = api,
): Promise<ProductWriteResult> {
  return requestUntyped(client, "put", `${product(id)}/${section}`, { body: { expected_version: version, [section]: values } });
}

export function setArchived(id: string, archived: boolean, version: number, reason: string | null, client: ApiClient = api): Promise<ProductDetail> {
  return requestUntyped(client, "post", `${product(id)}/${archived ? "archive" : "restore"}`, {
    body: { expected_version: version, ...(reason ? { reason } : {}) },
  });
}

/** Upload through the platform files endpoint, then attach to the product. */
export async function uploadMedia(
  productId: string,
  file: File,
  mediaType: MediaRead["media_type"],
  client: ApiClient = api,
): Promise<MediaRead> {
  const form = new FormData();
  form.append("file", file);
  const purpose = mediaType === "document" ? "document" : "image";
  const stored = await requestUntyped<{ id: string }>(client, "post", "/api/v1/files", { params: { query: { purpose } }, body: form });
  return requestUntyped(client, "post", `${product(productId)}/media`, { body: { file_id: stored.id, media_type: mediaType } });
}

export function mediaCommand(
  media: Pick<MediaRead, "id" | "version">,
  command: "make-primary" | "restore",
  client: ApiClient = api,
): Promise<MediaRead> {
  return requestUntyped(client, "post", `${CATALOGUE}/media/${encodeURIComponent(media.id)}/${command}`, {
    body: { expected_version: media.version },
  });
}

export function deleteMedia(media: Pick<MediaRead, "id" | "version">, reason: string, client: ApiClient = api): Promise<MediaRead> {
  return requestUntyped(client, "delete", `${CATALOGUE}/media/${encodeURIComponent(media.id)}`, {
    params: { query: { expected_version: media.version, reason } },
  });
}

// ---- taxonomy -------------------------------------------------------------------------------------------------------
export function createCategory(body: Record<string, unknown>, parentId: string | null, client: ApiClient = api): Promise<CategoryRead> {
  const path: `/api/v1/${string}` = parentId ? `${CATALOGUE}/categories/${encodeURIComponent(parentId)}/subcategories` : `${CATALOGUE}/categories`;
  return requestUntyped(client, "post", path, { body });
}

export function updateTaxonomy(
  kind: "category" | "subcategory",
  id: string,
  body: Record<string, unknown>,
  client: ApiClient = api,
): Promise<CategoryRead> {
  const base = kind === "category" ? "categories" : "subcategories";
  return requestUntyped(client, "patch", `${CATALOGUE}/${base}/${encodeURIComponent(id)}`, { body });
}

export function fetchReferences(kind: "category" | "subcategory", id: string, client: ApiClient = api): Promise<TaxonomyReferences> {
  const base = kind === "category" ? "categories" : "subcategories";
  return requestUntyped(client, "get", `${CATALOGUE}/${base}/${encodeURIComponent(id)}/references`);
}

export function deleteTaxonomy(
  kind: "category" | "subcategory",
  id: string,
  body: Record<string, unknown>,
  client: ApiClient = api,
): Promise<{ deleted_id: string; reassigned: Record<string, number> }> {
  const base = kind === "category" ? "categories" : "subcategories";
  return requestUntyped(client, "post", `${CATALOGUE}/${base}/${encodeURIComponent(id)}/delete`, { body });
}

export function reorderTaxonomy(orderedIds: string[], categoryId: string | null, client: ApiClient = api): Promise<CategoryRead[]> {
  return requestUntyped(client, "post", `${CATALOGUE}/categories/reorder`, {
    body: { ordered_ids: orderedIds, ...(categoryId ? { category_id: categoryId } : {}) },
  });
}

// ---- lookups --------------------------------------------------------------------------------------------------------
export function fetchLookups(
  params: { lookupType: string | null; q: string; offset: number },
  signal?: AbortSignal,
  client: ApiClient = api,
): Promise<Page<LookupRead>> {
  return requestUntyped(client, "get", `${CATALOGUE}/lookups`, {
    params: { query: { lookup_type: params.lookupType, q: params.q.trim() || undefined, offset: params.offset, limit: 50 } },
    signal,
  });
}

export function fetchLookupTypes(signal?: AbortSignal, client: ApiClient = api): Promise<{ lookup_type: string; count: number }[]> {
  return requestUntyped(client, "get", `${CATALOGUE}/lookups/types`, { signal });
}

export function lookupExportHref(lookupType: string | null, q: string): string {
  const query = new URLSearchParams();
  if (lookupType) query.set("lookup_type", lookupType);
  if (q.trim()) query.set("q", q.trim());
  const search = query.toString();
  return `${CATALOGUE}/lookups/export.csv${search ? `?${search}` : ""}`;
}

// ---- errors ---------------------------------------------------------------------------------------------------------
/**
 * Server field errors keyed by the dotted field path without the `body` prefix (`packaging.carton_qty`,
 * `product_name`), so each form input shows its own message (422 mapped to fields).
 */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ProblemError)) return {};
  const out: Record<string, string> = {};
  for (const issue of error.validationIssues) {
    const path = issue.loc.filter((part, index) => !(index === 0 && part === "body")).join(".");
    if (path && !out[path]) out[path] = issue.msg;
  }
  return out;
}
