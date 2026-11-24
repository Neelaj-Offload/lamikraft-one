"use client";

/**
 * Data helpers for the "Sales: deals" screens (quotations, orders, custom products).
 *
 * The API calls, parsers, list state and command hooks come from the old app's non-visual modules
 * (`@/features/sales/*`, `@/features/orders/*`, `@/features/custom-products/api`). This file holds
 * only what lived inside old *view* files and so could not be imported: the create-quotation body,
 * the custom-product form model, duplicate / restore / convert commands, and the status vocabulary.
 * Endpoints, bodies, idempotency keys and cache keys are the same as before.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { useState } from "react";
import type { CustomProductDetail } from "@/features/custom-products/api";
import { convertQuote, fetchOrderForQuote } from "@/features/orders/api";
import { duplicateQuote, restoreRevision } from "@/features/sales/api";
import type { PartyOption } from "@/features/sales/pickers";
import type { PriceType, QuoteCreateRequest, QuoteDetail } from "@/features/sales/types";
import { problemDescription } from "@/features/sales/use-quote-command";
import { createIdempotencyKey } from "@/lib/api/client";
import { commandSignature, createCommandKeys } from "@/lib/api/command-keys";
import { queryKeys } from "@/lib/api/query-keys";
import { useOnline } from "@/lib/hooks";
import { canAccessRoute, matchRoute } from "@/lib/routes";
import { useSession } from "@/lib/session/context";
import { toast, type Tone } from "~/ui";

// ---------------------------------------------------------------------------------------------
// Vocabulary: one word and one tone per status, shared by lists and records

export interface StatusLook {
  label: string;
  tone: Tone;
}

const QUOTATION_STATUS: Record<string, StatusLook> = {
  draft: { label: "Draft", tone: "neutral" },
  internal_review: { label: "Awaiting approval", tone: "amber" },
  sent: { label: "Sent", tone: "cobalt" },
  revised: { label: "Being revised", tone: "cobalt" },
  won: { label: "Won", tone: "leaf" },
  lost: { label: "Lost", tone: "ember" },
  cancelled: { label: "Cancelled", tone: "neutral" },
  archived: { label: "Archived", tone: "neutral" },
  deleted: { label: "Deleted", tone: "neutral" },
};

const ORDER_STATUS: Record<string, StatusLook> = {
  draft: { label: "To confirm", tone: "amber" },
  confirmed: { label: "Confirmed", tone: "cobalt" },
  on_hold: { label: "On hold", tone: "amber" },
  completed: { label: "Completed", tone: "leaf" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

const CUSTOM_STATUS: Record<string, StatusLook> = {
  inquiry: { label: "Enquiry", tone: "neutral" },
  under_development: { label: "In development", tone: "cobalt" },
  sample_stage: { label: "Sample stage", tone: "cobalt" },
  quoted: { label: "Quoted", tone: "cobalt" },
  approved: { label: "Approved", tone: "leaf" },
  rejected: { label: "Rejected", tone: "ember" },
  dormant: { label: "Dormant", tone: "neutral" },
  converted_to_standard: { label: "In the catalogue", tone: "leaf" },
};

export function humanise(code: string): string {
  const text = code.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const look = (table: Record<string, StatusLook>, status: string): StatusLook => table[status] ?? { label: humanise(status), tone: "neutral" };

export const quotationStatus = (status: string) => look(QUOTATION_STATUS, status);
export const orderStatus = (status: string) => look(ORDER_STATUS, status);
export const customProductStatus = (status: string) => look(CUSTOM_STATUS, status);

export const FULFILMENT_LABEL: Record<string, string> = { none: "Nothing delivered", partial: "Partly delivered", complete: "Delivered" };
export const PRICE_TYPE_LABEL: Record<string, string> = { export: "Export", domestic: "Domestic", sample: "Sample", distributor: "Distributor" };
export const CUSTOM_TYPE_LABEL: Record<string, string> = {
  modified_catalog: "Changed catalogue product",
  fully_new: "Entirely new",
  quote_only: "Quotation only",
};

/** `router.push` and `Link` want typed routes; API paths and built URLs are plain strings. */
export const asRoute = (path: string) => path as Route;

/** Whether this person may open an in-app path (checked against the shared route manifest), so links never lead to a refusal. */
export function useCanOpen(): (path: string) => boolean {
  const { permissionKeys } = useSession();
  return (path) => {
    const route = matchRoute(path);
    return route !== null && canAccessRoute(route, permissionKeys);
  };
}

// ---------------------------------------------------------------------------------------------
// Start a quotation (the body the old create form sent)

export interface QuotationDraftForm {
  party: PartyOption | null;
  brand: string;
  currency: string | null;
  price_type: PriceType;
  incoterm: string | null;
  incoterm_place: string;
  validity_days: string;
  customer_reference: string;
  remarks: string;
  apply_minimum_surcharge: boolean;
}

export const EMPTY_QUOTATION_DRAFT: QuotationDraftForm = {
  party: null,
  brand: "LK",
  currency: null,
  price_type: "export",
  incoterm: "FOB",
  incoterm_place: "",
  validity_days: "30",
  customer_reference: "",
  remarks: "",
  apply_minimum_surcharge: false,
};

/** The `QuoteCreate` body: only filled fields; the currency defaults to the customer's. */
export function quotationCreateBody(form: QuotationDraftForm, enquiryId: string | null = null): QuoteCreateRequest | null {
  if (!form.party) return null;
  const body: QuoteCreateRequest = {
    party_id: form.party.id,
    ...(enquiryId ? { enquiry_id: enquiryId } : {}),
    brand: form.brand,
    price_type: form.price_type,
    incoterm: form.incoterm,
    apply_minimum_surcharge: form.apply_minimum_surcharge,
  };
  const currency = form.currency ?? form.party.default_currency;
  if (currency) body.currency = currency;
  if (/^\d+$/.test(form.validity_days)) body.validity_days = Number.parseInt(form.validity_days, 10);
  if (form.incoterm_place.trim()) body.incoterm_place = form.incoterm_place.trim();
  if (form.customer_reference.trim()) body.customer_reference = form.customer_reference.trim();
  if (form.remarks.trim()) body.remarks = form.remarks.trim();
  return body;
}

// ---------------------------------------------------------------------------------------------
// Quotation commands that are not transitions

/** Copy a quotation into a new draft, keeping its prices or taking today's list prices. */
export function useDuplicateQuotation(quote: Pick<QuoteDetail, "id" | "version">) {
  const router = useRouter();
  const online = useOnline();
  const [keys] = useState(() => createCommandKeys());
  const [pending, setPending] = useState(false);

  const duplicate = async (priceMode: "keep" | "refresh") => {
    if (!online || pending) return;
    const body = { price_mode: priceMode };
    const signature = commandSignature(quote.id, "duplicate", quote.version, priceMode);
    const attempt = keys.attempt(signature, () => body);
    setPending(true);
    try {
      const copy = await duplicateQuote(quote.id, attempt.payload, attempt.key);
      keys.settle(signature);
      toast.success(`Copied as ${copy.quote_number}`, { description: priceMode === "refresh" ? "Lines carry today's list prices." : "Lines keep the prices of the original." });
      router.push(asRoute(copy.path));
    } catch (error) {
      keys.settle(signature, error);
      toast.error("The quotation was not duplicated", { description: problemDescription(error) });
    } finally {
      setPending(false);
    }
  };
  return { duplicate, pending };
}

/** Bring an issued revision back into the working copy (the issued revisions stay as they are). */
export function useRestoreRevision(quote: Pick<QuoteDetail, "id" | "version">) {
  const queryClient = useQueryClient();
  const [keys] = useState(() => createCommandKeys());
  const [pending, setPending] = useState(false);

  const restore = async (revisionNo: number, reason: string | null): Promise<boolean> => {
    const signature = commandSignature(quote.id, "restore", quote.version, revisionNo);
    const attempt = keys.attempt(signature, () => null);
    setPending(true);
    try {
      const fresh = await restoreRevision(quote, revisionNo, reason, attempt.key);
      keys.settle(signature);
      if (fresh) queryClient.setQueryData(queryKeys.sales.quote(quote.id), fresh);
      await queryClient.invalidateQueries({ queryKey: queryKeys.sales.all() });
      toast.success(`Revision ${revisionNo} is back in the working copy`);
      return true;
    } catch (error) {
      keys.settle(signature, error);
      toast.error(`Revision ${revisionNo} was not restored`, { description: problemDescription(error) });
      return false;
    } finally {
      setPending(false);
    }
  };
  return { restore, pending };
}

/**
 * The order behind a won quotation: the one that exists, or the command that creates it.
 * Conversion is idempotent on the server (one order per quotation), so a retry lands on the same order.
 */
export function useQuotationOrder(quoteId: string, status: string) {
  const { permissionKeys } = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();
  const online = useOnline();
  const [key] = useState(() => createIdempotencyKey());
  const [pending, setPending] = useState(false);
  const won = status === "won";
  const existing = useQuery({
    queryKey: queryKeys.orders.forQuote(quoteId),
    queryFn: ({ signal }) => fetchOrderForQuote(quoteId, signal),
    enabled: won && permissionKeys.has("orders.sales_order.read"),
  });

  const convert = async () => {
    if (pending) return;
    setPending(true);
    try {
      const result = await convertQuote(quoteId, key);
      toast.success(result.created ? `Order ${result.order.order_number} created` : `Order ${result.order.order_number} already exists for this quotation`);
      await queryClient.invalidateQueries({ queryKey: queryKeys.orders.all() });
      router.push(asRoute(result.order.path));
    } catch (error) {
      toast.error("The quotation was not converted", { description: problemDescription(error) });
    } finally {
      setPending(false);
    }
  };

  return {
    order: won ? (existing.data ?? null) : null,
    canConvert: won && !existing.isPending && !existing.data && permissionKeys.has("orders.sales_order.create"),
    convert,
    pending,
    offline: !online,
  };
}

// ---------------------------------------------------------------------------------------------
// Custom product form model (every editable field as form text; decimals stay strings)

export interface CustomForm {
  custom_type: string;
  party: { id: string; label: string } | null;
  base_product: { id: string; label: string } | null;
  customer_specific_flag: boolean;
  legacy_customer_name: string;
  inquiry_reference: string;
  product_name: string;
  description: string;
  dimensions_text: string;
  length_mm: string;
  width_mm: string;
  height_mm: string;
  thickness_mm: string;
  thickness_text: string;
  decor_no: string;
  decor_name: string;
  finish: string;
  shape: string;
  groove_count: string;
  bowl_count: string;
  handle_type: string;
  packaging_notes: string;
  carton_qty: string;
  inner_qty: string;
  packing_type: string;
  unit_weight_g: string;
  cbm: string;
  quoted_price: string;
  quoted_currency: string | null;
  unit_code: string;
  remarks: string;
}

export const EMPTY_CUSTOM: CustomForm = {
  custom_type: "fully_new",
  party: null,
  base_product: null,
  customer_specific_flag: false,
  legacy_customer_name: "",
  inquiry_reference: "",
  product_name: "",
  description: "",
  dimensions_text: "",
  length_mm: "",
  width_mm: "",
  height_mm: "",
  thickness_mm: "",
  thickness_text: "",
  decor_no: "",
  decor_name: "",
  finish: "",
  shape: "",
  groove_count: "",
  bowl_count: "",
  handle_type: "",
  packaging_notes: "",
  carton_qty: "",
  inner_qty: "",
  packing_type: "",
  unit_weight_g: "",
  cbm: "",
  quoted_price: "",
  quoted_currency: null,
  unit_code: "pcs",
  remarks: "",
};

const text = (value: string | null | undefined) => value ?? "";
const count = (value: number | null | undefined) => (value == null ? "" : String(value));

export function customFormOf(p: CustomProductDetail): CustomForm {
  const pack = p.packaging ?? {};
  return {
    custom_type: p.custom_type,
    party: p.party ? { id: p.party.id, label: p.party.display_name } : null,
    base_product: p.base_product_id ? { id: p.base_product_id, label: p.base_product_key ?? p.base_product_id } : null,
    customer_specific_flag: p.customer_specific_flag,
    legacy_customer_name: text(p.legacy_customer_name),
    inquiry_reference: text(p.inquiry_reference),
    product_name: p.product_name,
    description: text(p.description),
    dimensions_text: text(p.dimensions_text),
    length_mm: text(p.length_mm),
    width_mm: text(p.width_mm),
    height_mm: text(p.height_mm),
    thickness_mm: text(p.thickness_mm),
    thickness_text: text(p.thickness_text),
    decor_no: text(p.decor_no),
    decor_name: text(p.decor_name),
    finish: text(p.finish),
    shape: text(p.shape),
    groove_count: count(p.groove_count),
    bowl_count: count(p.bowl_count),
    handle_type: text(p.handle_type),
    packaging_notes: text(p.packaging_notes),
    carton_qty: count(pack.carton_qty),
    inner_qty: count(pack.inner_qty),
    packing_type: text(pack.packing_type),
    unit_weight_g: text(pack.unit_weight_g),
    cbm: text(pack.cbm),
    quoted_price: text(p.quoted_price?.amount),
    quoted_currency: p.quoted_price?.currency ?? null,
    unit_code: p.unit_code,
    remarks: text(p.remarks),
  };
}

const TEXT_FIELDS = [
  "legacy_customer_name",
  "inquiry_reference",
  "product_name",
  "description",
  "dimensions_text",
  "thickness_text",
  "decor_no",
  "decor_name",
  "finish",
  "shape",
  "handle_type",
  "packaging_notes",
  "remarks",
] as const;
const DECIMAL_FIELDS = ["length_mm", "width_mm", "height_mm", "thickness_mm", "quoted_price"] as const;
const COUNT_FIELDS = ["groove_count", "bowl_count"] as const;

function packagingOf(form: CustomForm): Record<string, unknown> | null {
  const out: Record<string, unknown> = {};
  if (form.carton_qty) out.carton_qty = Number.parseInt(form.carton_qty, 10);
  if (form.inner_qty) out.inner_qty = Number.parseInt(form.inner_qty, 10);
  if (form.packing_type.trim()) out.packing_type = form.packing_type.trim();
  if (form.unit_weight_g) out.unit_weight_g = form.unit_weight_g;
  if (form.cbm) out.cbm = form.cbm;
  return Object.keys(out).length ? out : null;
}

/** The request body: on create every filled field, on update only what changed relative to `base` (nulls clear). */
export function customBody(form: CustomForm, base: CustomForm | null): Record<string, unknown> {
  const all: Record<string, unknown> = {
    custom_type: form.custom_type,
    party_id: form.party?.id ?? null,
    base_product_id: form.base_product?.id ?? null,
    customer_specific_flag: form.customer_specific_flag,
    unit_code: form.unit_code || "pcs",
    quoted_currency: form.quoted_price ? form.quoted_currency : null,
    packaging: packagingOf(form),
  };
  for (const field of TEXT_FIELDS) all[field] = form[field].trim() || null;
  for (const field of DECIMAL_FIELDS) all[field] = form[field] || null;
  for (const field of COUNT_FIELDS) all[field] = form[field] ? Number.parseInt(form[field], 10) : null;
  if (base === null) return Object.fromEntries(Object.entries(all).filter(([, value]) => value !== null && value !== ""));
  const before = customBody(base, null);
  const changed: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(all)) {
    if (JSON.stringify(value ?? null) !== JSON.stringify(before[key] ?? null)) changed[key] = value;
  }
  if ("quoted_price" in changed || "quoted_currency" in changed) {
    changed.quoted_price = all.quoted_price;
    changed.quoted_currency = all.quoted_currency;
  }
  return changed;
}
