/**
 * Runtime readers for the challans API (see types.ts). Required fields are checked; links must stay inside the
 * app; unknown enum values fall back to a safe default rather than being forwarded raw; quantities must be
 * DecimalStr strings (never coerced from numbers).
 */

import { isDecimalStr } from "@/lib/format/decimal";
import { safeAppPath } from "@/lib/safe-path";
import {
  CHALLAN_STATUSES,
  CHALLAN_TYPES,
  DESTINATION_TYPES,
  LINE_TYPES,
  RETURN_TYPES,
  type BranchLink,
  type Capability,
  type ChallanDetail,
  type ChallanLine,
  type ChallanLink,
  type ChallanPrint,
  type ChallanStatus,
  type ChallanSummary,
  type ChallanSummaryRow,
  type CountBucket,
  type HistoryEntry,
  type InternalNote,
  type Page,
  type PartyLink,
  type PrintLine,
  type PrintParty,
  type QuantityByUnit,
  type ReturnLink,
  type TransitionOption,
  type UserRef,
} from "./types";

export class ChallansShapeError extends Error {
  override readonly name = "ChallansShapeError";
}

type Json = Record<string, unknown>;
const isObject = (value: unknown): value is Json => value !== null && typeof value === "object" && !Array.isArray(value);
const str = (value: unknown): string | null => (typeof value === "string" && value !== "" ? value : null);
const arr = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const int = (value: unknown, fallback = 0): number => (typeof value === "number" && Number.isInteger(value) ? value : fallback);
const dec = (value: unknown): string => (typeof value === "string" && isDecimalStr(value) ? value : "0");
const strings = (value: unknown): string[] => arr(value).filter((entry): entry is string => typeof entry === "string");

function oneOf<T extends string>(values: readonly T[], value: unknown, fallback: T): T {
  return values.find((candidate) => candidate === value) ?? fallback;
}

function need(raw: unknown, ...fields: string[]): Json {
  if (!isObject(raw)) throw new ChallansShapeError("expected an object");
  for (const field of fields) if (raw[field] === undefined || raw[field] === null) throw new ChallansShapeError(`missing ${field}`);
  return raw;
}

const challanPath = (id: string) => `/operations/challans/${encodeURIComponent(id)}`;

function user(value: unknown): UserRef | null {
  return isObject(value) && str(value.id) ? { id: str(value.id)!, display_name: str(value.display_name) } : null;
}

function party(value: unknown): PartyLink | null {
  return isObject(value) && str(value.id) ? { id: str(value.id)!, party_number: str(value.party_number), display_name: str(value.display_name) } : null;
}

function branch(value: unknown): BranchLink | null {
  return isObject(value) && str(value.id) ? { id: str(value.id)!, branch_code: str(value.branch_code) ?? "", name: str(value.name) ?? "" } : null;
}

function link(value: unknown): ChallanLink | null {
  if (!isObject(value) || !str(value.id) || !str(value.challan_number)) return null;
  const id = str(value.id)!;
  return { id, challan_number: str(value.challan_number)!, status: oneOf(CHALLAN_STATUSES, value.status, "draft"), path: safeAppPath(value.path) ?? challanPath(id) };
}

export function quantities(value: unknown): QuantityByUnit {
  if (!isObject(value)) return {};
  const out: QuantityByUnit = {};
  for (const [unit, quantity] of Object.entries(value)) if (typeof quantity === "string" && isDecimalStr(quantity)) out[unit] = quantity;
  return out;
}

export function capabilitiesOf(value: unknown): Record<string, Capability> {
  if (!isObject(value)) return {};
  const out: Record<string, Capability> = {};
  for (const [key, cap] of Object.entries(value)) {
    if (isObject(cap)) out[key] = { allowed: cap.allowed === true, reason_code: str(cap.reason_code) };
  }
  return out;
}

function transitionsOf(value: unknown): TransitionOption[] {
  return arr(value).flatMap((entry) =>
    isObject(entry) && str(entry.action) ? [{ action: str(entry.action)!, to_status: str(entry.to_status) ?? "", requires_reason: entry.requires_reason === true }] : [],
  );
}

export function parseChallanRow(raw: unknown): ChallanSummaryRow {
  const r = need(raw, "id", "challan_number", "challan_date", "status", "version");
  const id = str(r.id)!;
  return {
    id,
    challan_number: str(r.challan_number)!,
    revision_no: int(r.revision_no),
    challan_date: str(r.challan_date)!,
    challan_type: oneOf(CHALLAN_TYPES, r.challan_type, "outward"),
    return_type: oneOf(RETURN_TYPES, r.return_type, "non_returnable"),
    destination_type: oneOf(DESTINATION_TYPES, r.destination_type, "customer"),
    destination_party: str(r.destination_party) ?? "",
    party: party(r.party),
    reference_no: str(r.reference_no),
    status: oneOf<ChallanStatus>(CHALLAN_STATUSES, r.status, "draft"),
    line_count: int(r.line_count),
    quantity_by_unit: quantities(r.quantity_by_unit),
    outstanding_by_unit: quantities(r.outstanding_by_unit),
    expected_return_date: str(r.expected_return_date),
    owner: user(r.owner) ?? { id: "", display_name: null },
    updated_at: str(r.updated_at) ?? "",
    deleted_at: str(r.deleted_at),
    version: int(r.version),
    path: safeAppPath(r.path) ?? challanPath(id),
  };
}

export function parseChallanPage(raw: unknown): Page<ChallanSummaryRow> {
  const r = need(raw, "items");
  return { items: arr(r.items).map(parseChallanRow), total: int(r.total), limit: int(r.limit), offset: int(r.offset) };
}

function parseLine(raw: unknown): ChallanLine {
  const r = need(raw, "id", "line_no", "item_name", "quantity", "unit");
  return {
    id: str(r.id)!,
    line_no: int(r.line_no),
    line_type: oneOf(LINE_TYPES, r.line_type, "manual"),
    product_id: str(r.product_id),
    custom_product_id: str(r.custom_product_id),
    item_code: str(r.item_code),
    item_name: str(r.item_name) ?? "",
    hsn_sac: str(r.hsn_sac),
    quantity: dec(r.quantity),
    unit: str(r.unit) ?? "pcs",
    remarks: str(r.remarks),
    original_line_id: str(r.original_line_id),
    returned_quantity: dec(r.returned_quantity),
    outstanding_quantity: dec(r.outstanding_quantity),
  };
}

function parseReturnLink(raw: unknown): ReturnLink | null {
  if (!isObject(raw) || !str(raw.id)) return null;
  const ret = link(raw.return_challan);
  const orig = link(raw.original_challan);
  if (!ret || !orig) return null;
  return {
    id: str(raw.id)!,
    return_challan: ret,
    original_challan: orig,
    return_line_id: str(raw.return_line_id) ?? "",
    original_line_id: str(raw.original_line_id) ?? "",
    quantity: dec(raw.quantity),
    created_at: str(raw.created_at) ?? "",
    reversed_at: str(raw.reversed_at),
  };
}

function parseHistory(raw: unknown): HistoryEntry | null {
  if (!isObject(raw) || !str(raw.action)) return null;
  return {
    action: str(raw.action)!,
    from_status: str(raw.from_status) ?? "",
    to_status: str(raw.to_status) ?? "",
    actor: user(raw.actor),
    reason_code: str(raw.reason_code),
    reason: str(raw.reason),
    occurred_at: str(raw.occurred_at) ?? "",
  };
}

export function parseChallanDetail(raw: unknown): ChallanDetail {
  const r = need(raw, "id", "challan_number", "lines", "capabilities", "allowed_transitions");
  return {
    ...parseChallanRow(r),
    source_location: str(r.source_location) ?? "",
    source_branch: branch(r.source_branch),
    consignee_party: party(r.consignee_party),
    office_branch: branch(r.office_branch),
    shipping_name: str(r.shipping_name),
    gstin: str(r.gstin),
    phone: str(r.phone),
    email: str(r.email),
    address: str(r.address),
    remarks: str(r.remarks),
    direction: r.direction === "inward" ? "inward" : "outward",
    inventory_effect: r.inventory_effect === "posting" ? "posting" : "none",
    original_challan: link(r.original_challan),
    duplicated_from: link(r.duplicated_from),
    issued_at: str(r.issued_at),
    issued_by: user(r.issued_by),
    closed_at: str(r.closed_at),
    close_reason: str(r.close_reason),
    cancelled_at: str(r.cancelled_at),
    cancel_reason_code: str(r.cancel_reason_code),
    cancel_reason: str(r.cancel_reason),
    created_at: str(r.created_at) ?? "",
    origin: str(r.origin) ?? "user",
    lines: arr(r.lines).map(parseLine),
    return_links: arr(r.return_links).flatMap((entry) => parseReturnLink(entry) ?? []),
    history: arr(r.history).flatMap((entry) => parseHistory(entry) ?? []),
    capabilities: capabilitiesOf(r.capabilities),
    allowed_transitions: transitionsOf(r.allowed_transitions),
  };
}

/** A command's answer as the challan, or null when it is not one (the caller refetches). */
export function challanOrNull(raw: unknown): ChallanDetail | null {
  try {
    return parseChallanDetail(raw);
  } catch (error) {
    if (error instanceof ChallansShapeError) return null;
    throw error;
  }
}

function buckets(value: unknown): CountBucket[] {
  return arr(value).flatMap((entry) => (isObject(entry) && str(entry.key) ? [{ key: str(entry.key)!, label: str(entry.label) ?? str(entry.key)!, count: int(entry.count) }] : []));
}

export function parseChallanSummary(raw: unknown): ChallanSummary {
  const r = need(raw, "total", "this_week", "this_month", "pending_returnable");
  return {
    total: int(r.total),
    this_week: int(r.this_week),
    this_month: int(r.this_month),
    pending_returnable: int(r.pending_returnable),
    pending_returnable_quantity: quantities(r.pending_returnable_quantity),
    issued: int(r.issued),
    by_type: buckets(r.by_type),
    by_destination: buckets(r.by_destination),
    by_status: buckets(r.by_status),
    today: str(r.today) ?? "",
  };
}

function printParty(value: unknown): PrintParty {
  return isObject(value) ? { title: str(value.title) ?? "", lines: strings(value.lines) } : { title: "", lines: [] };
}

function printLine(raw: unknown): PrintLine | null {
  if (!isObject(raw) || !str(raw.item_name)) return null;
  return {
    line_no: int(raw.line_no),
    item_code: str(raw.item_code),
    item_name: str(raw.item_name)!,
    hsn_sac: str(raw.hsn_sac),
    quantity: dec(raw.quantity),
    unit: str(raw.unit) ?? "",
    remarks: str(raw.remarks),
  };
}

export function parseChallanPrint(raw: unknown): ChallanPrint {
  const r = need(raw, "challan_id", "challan_number", "lines", "from_block", "to_block");
  return {
    challan_id: str(r.challan_id)!,
    challan_number: str(r.challan_number)!,
    challan_date: str(r.challan_date) ?? "",
    status: oneOf(CHALLAN_STATUSES, r.status, "draft"),
    type_label: str(r.type_label) ?? "",
    return_label: str(r.return_label) ?? "",
    destination_label: str(r.destination_label) ?? "",
    reference_no: str(r.reference_no),
    expected_return_date: str(r.expected_return_date),
    company_name: str(r.company_name) ?? "",
    company_lines: strings(r.company_lines),
    not_configured: strings(r.not_configured),
    from_block: printParty(r.from_block),
    to_block: printParty(r.to_block),
    lines: arr(r.lines).flatMap((entry) => printLine(entry) ?? []),
    total_quantity: quantities(r.total_quantity),
    remarks: str(r.remarks),
    terms: strings(r.terms),
    terms_are_demo: r.terms_are_demo === true,
    signatures: strings(r.signatures),
    watermark: str(r.watermark),
  };
}

export function parseNote(raw: unknown): InternalNote {
  const r = need(raw, "version");
  const caps = capabilitiesOf(r.capabilities);
  const updatedBy = str(r.updated_by);
  return {
    body: typeof r.body === "string" ? r.body : "",
    version: int(r.version),
    updated_at: str(r.updated_at),
    updated_by: updatedBy ? { id: updatedBy, display_name: str(r.updated_by_name) } : null,
    canUpdate: caps.update?.allowed === true,
  };
}
