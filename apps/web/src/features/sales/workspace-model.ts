/**
 * Pure rules of the quote workspace: which commands to offer (only what the server allows),
 * the header form and its dirty fields, the three-way merge after a 409, line edits and the
 * live-totals preview request. Nothing here computes money: prices and totals are the server's
 * DecimalStr strings, compared (never added) with `compareDecimalStr`.
 */

import { compareDecimalStr, isDecimalStr } from "@/lib/format/decimal";
import { threeWayMerge, type MergeResult } from "@/lib/merge";
import { salesMessages as m } from "@/messages/sales";
import {
  PRICE_TYPES,
  type LineUpdateRequest,
  type PreviewLineRequest,
  type PriceType,
  type QuoteDetail,
  type QuoteHeaderFields,
  type QuoteLine,
} from "./types";

// ---------------------------------------------------------------------------------------------
// Commands

export interface CommandButton {
  /** A transition action (`submit_review` …) or `delete` (from `capabilities.delete`). */
  action: string;
  label: string;
  requiresReason: boolean;
  variant: "primary" | "secondary" | "danger";
}

const FORWARD = new Set(["submit_review", "mark_sent", "mark_won"]);
const DESTRUCTIVE = new Set(["cancel", "mark_lost", "delete", "discard_revision"]);

/** Draft (never issued) and revised (a working copy of a sent quote) are the editable statuses. */
export function isEditable(quote: Pick<QuoteDetail, "status" | "capabilities">): boolean {
  return (quote.status === "draft" || quote.status === "revised") && quote.capabilities.update?.allowed === true;
}

function humanise(action: string): string {
  const text = action.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * The quote's commands, rendered **only** from `allowed_transitions` (plus Delete when the
 * server grants `capabilities.delete` on a draft). One forward action is primary; destructive
 * ones are danger buttons; the order is the server's.
 */
export function commandButtons(quote: Pick<QuoteDetail, "allowed_transitions" | "capabilities" | "status">): CommandButton[] {
  let primaryTaken = false;
  const out: CommandButton[] = [];
  const seen = new Set<string>();
  for (const transition of quote.allowed_transitions) {
    if (seen.has(transition.action)) continue;
    seen.add(transition.action);
    let variant: CommandButton["variant"] = "secondary";
    if (DESTRUCTIVE.has(transition.action)) variant = "danger";
    else if (FORWARD.has(transition.action) && !primaryTaken) {
      variant = "primary";
      primaryTaken = true;
    }
    out.push({
      action: transition.action,
      label: m.workspace.transitions[transition.action] ?? humanise(transition.action),
      requiresReason: transition.requires_reason,
      variant,
    });
  }
  if (quote.status === "draft" && quote.capabilities.delete?.allowed && !seen.has("delete")) {
    out.push({ action: "delete", label: m.workspace.transitions.delete!, requiresReason: false, variant: "danger" });
  }
  return out;
}

// ---------------------------------------------------------------------------------------------
// Header form

export interface HeaderForm {
  price_type: PriceType;
  incoterm: string | null;
  incoterm_place: string;
  payment_terms: string;
  validity_days: string | null;
  customer_reference: string;
  remarks: string;
  apply_minimum_surcharge: boolean;
}

export const HEADER_FIELDS = [
  "price_type",
  "incoterm",
  "incoterm_place",
  "payment_terms",
  "validity_days",
  "customer_reference",
  "remarks",
  "apply_minimum_surcharge",
] as const satisfies readonly (keyof HeaderForm)[];

export function headerFormOf(quote: Pick<QuoteDetail, keyof QuoteHeaderFields>): HeaderForm {
  return {
    price_type: quote.price_type,
    incoterm: quote.incoterm,
    incoterm_place: quote.incoterm_place ?? "",
    payment_terms: quote.payment_terms ?? "",
    validity_days: String(quote.validity_days),
    customer_reference: quote.customer_reference ?? "",
    remarks: quote.remarks ?? "",
    apply_minimum_surcharge: quote.apply_minimum_surcharge,
  };
}

/** Fields the person changed (relative to the version they started from). */
export function dirtyHeaderFields(base: HeaderForm, form: HeaderForm): (keyof HeaderForm)[] {
  return HEADER_FIELDS.filter((field) => form[field] !== base[field]);
}

/** The PATCH body for the dirty fields only; empty text becomes null; invalid days are dropped. */
export function headerChanges(base: HeaderForm, form: HeaderForm): Partial<QuoteHeaderFields> {
  const out: Partial<QuoteHeaderFields> = {};
  for (const field of dirtyHeaderFields(base, form)) {
    switch (field) {
      case "price_type":
        out.price_type = PRICE_TYPES.find((type) => type === form.price_type) ?? base.price_type;
        break;
      case "incoterm":
        out.incoterm = form.incoterm || null;
        break;
      case "validity_days":
        if (form.validity_days && /^\d+$/.test(form.validity_days)) out.validity_days = Number.parseInt(form.validity_days, 10);
        break;
      case "apply_minimum_surcharge":
        out.apply_minimum_surcharge = form.apply_minimum_surcharge;
        break;
      default:
        out[field] = form[field].trim() || null;
    }
  }
  return out;
}

export interface HeaderConflictState {
  /** The fresh server version the next save is sent against. */
  version: number;
  changedBy: string | null;
  changedAt: string | null;
  /** The form after the merge: their changes adopted, my edits kept. */
  form: HeaderForm;
  /** The new base (their values): dirty fields are computed against it from now on. */
  base: HeaderForm;
  /** Fields both of us changed to different values (my value stays in the form). */
  conflicts: (keyof HeaderForm)[];
  /** Fields only they changed (adopted into the form). */
  adopted: (keyof HeaderForm)[];
}

/**
 * Three-way merge after a 409 `version_conflict` on the header: `base` is what the person
 * started from, `mine` their form, `theirs` the server's current quote. No edit is lost; no
 * change of theirs is overwritten unless the person saves again.
 */
export function mergeHeaderConflict(
  base: HeaderForm,
  mine: HeaderForm,
  theirs: Pick<QuoteDetail, keyof QuoteHeaderFields | "version">,
  who: { changedBy: string | null; changedAt: string | null } = { changedBy: null, changedAt: null },
): HeaderConflictState {
  const theirForm = headerFormOf(theirs);
  const dirty = Object.fromEntries(dirtyHeaderFields(base, mine).map((field) => [field, mine[field]]));
  const result: MergeResult = threeWayMerge({ ...base }, dirty, { ...theirForm });
  return {
    version: theirs.version,
    changedBy: who.changedBy,
    changedAt: who.changedAt,
    form: { ...theirForm, ...(result.merged as Partial<HeaderForm>) },
    base: theirForm,
    conflicts: result.conflicts.map((conflict) => conflict.field as keyof HeaderForm),
    adopted: result.adopted as (keyof HeaderForm)[],
  };
}

// ---------------------------------------------------------------------------------------------
// Lines

export interface LineEdit {
  quantity: string | null;
  unit_price: string | null;
  override_reason: string;
}

export function lineEditOf(line: Pick<QuoteLine, "quantity" | "unit_price" | "override_reason">): LineEdit {
  return { quantity: line.quantity, unit_price: line.unit_price, override_reason: line.override_reason ?? "" };
}

/** A catalog line's price differs from the list price (the override reason field appears). */
export function priceDiffersFromList(line: Pick<QuoteLine, "line_type" | "default_unit_price">, unitPrice: string | null): boolean {
  if (line.line_type !== "catalog" || !unitPrice || !isDecimalStr(unitPrice) || !line.default_unit_price) return false;
  return compareDecimalStr(unitPrice, line.default_unit_price) !== 0;
}

export function lineEditIsDirty(line: QuoteLine, edit: LineEdit): boolean {
  const same = (a: string | null, b: string | null) => (a && b && isDecimalStr(a) && isDecimalStr(b) ? compareDecimalStr(a, b) === 0 : a === b);
  return !same(edit.quantity, line.quantity) || !same(edit.unit_price, line.unit_price) || (edit.override_reason.trim() || null) !== (line.override_reason ?? null);
}

export type LineUpdatePlan = { ok: true; body: LineUpdateRequest } | { ok: false; error: "quantity" | "price" | "reason" };

/**
 * The PATCH for a line edit. A catalog price that differs from the list needs a reason; going
 * back to the list price clears the override instead of sending the price.
 */
export function lineUpdatePlan(line: QuoteLine, edit: LineEdit): LineUpdatePlan {
  if (!edit.quantity || !isDecimalStr(edit.quantity) || compareDecimalStr(edit.quantity, "0") <= 0) return { ok: false, error: "quantity" };
  const body: LineUpdateRequest = {};
  if (compareDecimalStr(edit.quantity, line.quantity) !== 0) body.quantity = edit.quantity;
  const priceChanged = edit.unit_price !== null && (line.unit_price === null || !isDecimalStr(edit.unit_price) || compareDecimalStr(edit.unit_price, line.unit_price) !== 0);
  if (edit.unit_price !== null && !isDecimalStr(edit.unit_price)) return { ok: false, error: "price" };
  if (line.line_type === "catalog") {
    const differs = priceDiffersFromList(line, edit.unit_price);
    if (differs) {
      const reason = edit.override_reason.trim();
      if (!reason) return { ok: false, error: "reason" };
      if (priceChanged) body.unit_price = edit.unit_price!;
      if (priceChanged || reason !== (line.override_reason ?? "")) body.override_reason = reason;
    } else if (line.is_overridden && edit.unit_price !== null) {
      body.clear_override = true;
    }
  } else if (priceChanged) {
    if (edit.unit_price === null) return { ok: false, error: "price" };
    body.unit_price = edit.unit_price;
  }
  return { ok: true, body };
}

/**
 * The `POST /sales/quotes/calculate` body for the quote with the person's unsaved line edits,
 * or null when it cannot be previewed (custom lines, an invalid number, nothing edited).
 */
export function previewRequest(
  quote: Pick<QuoteDetail, "currency" | "party" | "price_type" | "apply_minimum_surcharge" | "lines">,
  edits: Readonly<Record<string, LineEdit>>,
): { currency: string; party_id: string; price_type: string; surcharge_requested: boolean; lines: PreviewLineRequest[] } | null {
  const edited = quote.lines.filter((line) => edits[line.id] && lineEditIsDirty(line, edits[line.id]!));
  if (edited.length === 0) return null;
  const lines: PreviewLineRequest[] = [];
  for (const line of quote.lines) {
    const edit = edits[line.id] ?? lineEditOf(line);
    if (line.line_type === "custom") return null;
    if (!edit.quantity || !isDecimalStr(edit.quantity) || compareDecimalStr(edit.quantity, "0") <= 0) return null;
    if (edit.unit_price !== null && !isDecimalStr(edit.unit_price)) return null;
    const entry: PreviewLineRequest = { line_key: line.line_key, line_type: line.line_type, quantity: edit.quantity, unit_code: line.unit_code || undefined };
    if (line.line_type === "catalog") {
      if (!line.product_id) return null;
      entry.product_id = line.product_id;
      if (edit.unit_price !== null && priceDiffersFromList(line, edit.unit_price)) entry.unit_price = edit.unit_price;
    } else {
      if (edit.unit_price === null) return null;
      entry.unit_price = edit.unit_price;
    }
    if (line.discount_pct) entry.discount_pct = line.discount_pct;
    lines.push(entry);
  }
  return {
    currency: quote.currency,
    party_id: quote.party.id,
    price_type: quote.price_type,
    surcharge_requested: quote.apply_minimum_surcharge,
    lines,
  };
}

/** The review the quote needs before sending, in words ("price override, discount"). */
export function reviewReasonsText(reasons: readonly string[]): string {
  return reasons.map((reason) => m.workspace.reviewReasons[reason] ?? reason.replace(/_/g, " ")).join(", ");
}
