/**
 * The plan editor's state as plain functions: the form from a plan, client checks, the dirty-field request
 * (only what changed, plus expected_version in api.ts), and server 422 errors mapped back to rows and fields.
 * Every value stays a DecimalStr string; nothing here does arithmetic on dimensions or quantities.
 */

import type { ValidationIssue } from "@/lib/api/errors";
import { compareDecimalStr, isDecimalStr, trimDecimalStr } from "@/lib/format/decimal";
import type { CuttingProduct, GrainRule, Mode, PlanDetail, PlanItemRequest, PlanSettingsRequest } from "./types";

export const BLANK_ROWS = 3;

export interface EditorRow {
  key: string;
  product_id: string | null;
  sku: string;
  decor: string;
  thickness_mm: string | null;
  length_mm: string | null;
  width_mm: string | null;
  quantity: string | null;
  grain_rule: GrainRule;
}

export interface EditorSettings {
  board_length_mm: string | null;
  board_width_mm: string | null;
  margin_mm: string | null;
  gap_mm: string | null;
  oversize_enabled: boolean;
  mode: Mode;
  overproduction_enabled: boolean;
  max_extra_qty: string | null;
  max_extra_pct: string | null;
}

export interface EditorForm {
  name: string;
  rows: EditorRow[];
  settings: EditorSettings;
}

export type RowField = "sku" | "decor" | "thickness_mm" | "length_mm" | "width_mm" | "quantity";
export interface FormErrors {
  name?: string;
  rows: Record<string, Partial<Record<RowField | "product_id" | "grain_rule", string>>>;
  settings: Partial<Record<keyof EditorSettings, string>>;
  general: string[];
}

let rowCounter = 0;
export function newRowKey(): string {
  rowCounter += 1;
  return `row-${rowCounter}`;
}

export function blankRow(key: string = newRowKey()): EditorRow {
  return { key, product_id: null, sku: "", decor: "", thickness_mm: null, length_mm: null, width_mm: null, quantity: null, grain_rule: "inherit" };
}

export const DEFAULT_SETTINGS: EditorSettings = {
  board_length_mm: "2440",
  board_width_mm: "1220",
  margin_mm: "5",
  gap_mm: "6",
  oversize_enabled: false,
  mode: "nested",
  overproduction_enabled: false,
  max_extra_qty: "0",
  max_extra_pct: "0",
};

export function settingsOf(plan: PlanDetail): EditorSettings {
  const s = plan.settings;
  return {
    board_length_mm: trimDecimalStr(s.board_length_mm),
    board_width_mm: trimDecimalStr(s.board_width_mm),
    margin_mm: trimDecimalStr(s.margin_mm),
    gap_mm: trimDecimalStr(s.gap_mm),
    oversize_enabled: s.oversize_enabled,
    mode: s.mode,
    overproduction_enabled: s.overproduction_enabled,
    max_extra_qty: String(s.max_extra_qty),
    max_extra_pct: trimDecimalStr(s.max_extra_pct),
  };
}

/** The form for a saved plan (its rows, stable keys from the item ids) or a new one (three blank rows, as before). */
export function formOf(plan: PlanDetail | null): EditorForm {
  if (!plan) return { name: "", rows: Array.from({ length: BLANK_ROWS }, () => blankRow()), settings: { ...DEFAULT_SETTINGS } };
  return {
    name: plan.name,
    rows: plan.items.map((item) => ({
      key: item.id ?? `line-${item.line_no}`,
      product_id: item.product_id,
      sku: item.sku,
      decor: item.decor ?? "",
      thickness_mm: trimDecimalStr(item.thickness_mm),
      length_mm: trimDecimalStr(item.length_mm),
      width_mm: trimDecimalStr(item.width_mm),
      quantity: String(item.quantity),
      grain_rule: item.grain_rule,
    })),
    settings: settingsOf(plan),
  };
}

export function isBlankRow(row: EditorRow): boolean {
  return !row.sku.trim() && !row.decor.trim() && !row.thickness_mm && !row.length_mm && !row.width_mm && !row.quantity && !row.product_id;
}

/** A catalogue product fills the row's SKU, decor, thickness and size (whatever the catalogue knows). */
export function applyProduct(row: EditorRow, product: CuttingProduct): EditorRow {
  return {
    ...row,
    product_id: product.product_id,
    sku: product.product_key,
    decor: product.decor ?? row.decor,
    thickness_mm: product.thickness_mm ? trimDecimalStr(product.thickness_mm) : row.thickness_mm,
    length_mm: product.length_mm ? trimDecimalStr(product.length_mm) : row.length_mm,
    width_mm: product.width_mm ? trimDecimalStr(product.width_mm) : row.width_mm,
    quantity: row.quantity ?? "1",
  };
}

const ONE_PLACE = /^\d{1,5}(\.\d)?$/;
const WHOLE = /^\d{1,4}$/;

function positiveMm(value: string | null): boolean {
  return value !== null && ONE_PLACE.test(value) && compareDecimalStr(value, "0") > 0;
}

export function rowsToRequest(rows: readonly EditorRow[]): PlanItemRequest[] {
  return rows
    .filter((row) => !isBlankRow(row))
    .map((row) => ({
      product_id: row.product_id,
      sku: row.sku.trim(),
      decor: row.decor.trim() || null,
      thickness_mm: row.thickness_mm ?? "",
      length_mm: row.length_mm ?? "",
      width_mm: row.width_mm ?? "",
      quantity: row.quantity ?? "",
      grain_rule: row.grain_rule,
    }));
}

const MESSAGES: Record<string, string> = {
  required: "Required",
  mm: "Millimetres above 0, at most one decimal place",
  qty: "Whole number from 1 to 5000",
  pct: "0 to 100",
  usable: "The margins leave no usable area",
};

/** Client checks before a save; the server re-validates and its 422 lands in the same shape. */
export function validateForm(form: EditorForm): FormErrors {
  const errors: FormErrors = { rows: {}, settings: {}, general: [] };
  if (!form.name.trim()) errors.name = "Give the plan a name.";
  for (const row of form.rows) {
    if (isBlankRow(row)) continue;
    const e: FormErrors["rows"][string] = {};
    if (!row.sku.trim()) e.sku = MESSAGES.required;
    if (!row.thickness_mm || !isDecimalStr(row.thickness_mm) || compareDecimalStr(row.thickness_mm, "0") <= 0) e.thickness_mm = MESSAGES.required;
    if (!positiveMm(row.length_mm)) e.length_mm = MESSAGES.mm;
    if (!positiveMm(row.width_mm)) e.width_mm = MESSAGES.mm;
    if (!row.quantity || !WHOLE.test(row.quantity) || compareDecimalStr(row.quantity, "0") <= 0 || compareDecimalStr(row.quantity, "5000") > 0) e.quantity = MESSAGES.qty;
    if (Object.keys(e).length) errors.rows[row.key] = e;
  }
  const s = form.settings;
  for (const field of ["board_length_mm", "board_width_mm"] as const) {
    if (!positiveMm(s[field])) errors.settings[field] = MESSAGES.mm;
  }
  for (const field of ["margin_mm", "gap_mm"] as const) {
    const value = s[field];
    if (value === null || !ONE_PLACE.test(value)) errors.settings[field] = "Millimetres, at most one decimal place";
  }
  if (s.overproduction_enabled) {
    if (!s.max_extra_qty || !WHOLE.test(s.max_extra_qty)) errors.settings.max_extra_qty = "Whole number";
    if (!s.max_extra_pct || !isDecimalStr(s.max_extra_pct) || compareDecimalStr(s.max_extra_pct, "100") > 0) errors.settings.max_extra_pct = MESSAGES.pct;
  }
  return errors;
}

export function hasErrors(errors: FormErrors): boolean {
  return Boolean(errors.name) || Object.keys(errors.rows).length > 0 || Object.keys(errors.settings).length > 0 || errors.general.length > 0;
}

/** Only the settings that differ from ``base`` (all of them for a new plan). */
export function settingsChanges(base: EditorSettings | null, form: EditorSettings): PlanSettingsRequest {
  const out: PlanSettingsRequest = {};
  const keys = ["board_length_mm", "board_width_mm", "margin_mm", "gap_mm", "oversize_enabled", "mode", "overproduction_enabled", "max_extra_qty", "max_extra_pct"] as const;
  for (const key of keys) {
    if (base && base[key] === form[key]) continue;
    const value = form[key];
    if (value === null) continue;
    (out as Record<string, unknown>)[key] = value;
  }
  return out;
}

export function itemsChanged(base: EditorForm, form: EditorForm): boolean {
  return JSON.stringify(rowsToRequest(base.rows)) !== JSON.stringify(rowsToRequest(form.rows));
}

export function dirtyParts(base: EditorForm, form: EditorForm): ("name" | "items" | "settings")[] {
  const out: ("name" | "items" | "settings")[] = [];
  if (base.name.trim() !== form.name.trim()) out.push("name");
  if (itemsChanged(base, form)) out.push("items");
  if (Object.keys(settingsChanges(base.settings, form.settings)).length) out.push("settings");
  return out;
}

/** The PATCH body (without expected_version): name, the whole cut list and changed settings, only when dirty. */
export function planChanges(base: EditorForm, form: EditorForm): { name?: string; items?: PlanItemRequest[]; settings?: PlanSettingsRequest } {
  const parts = dirtyParts(base, form);
  return {
    ...(parts.includes("name") ? { name: form.name.trim() } : {}),
    ...(parts.includes("items") ? { items: rowsToRequest(form.rows) } : {}),
    ...(parts.includes("settings") ? { settings: settingsChanges(base.settings, form.settings) } : {}),
  };
}

/**
 * A 422's `loc` back onto the form: ["body", "items", i, field] names the i-th non-blank row (the request
 * skips blank rows), ["body", "settings", field] a setting, ["body", "name"] the name; anything else is general.
 */
export function serverErrors(issues: readonly ValidationIssue[], rows: readonly EditorRow[]): FormErrors {
  const sent = rows.filter((row) => !isBlankRow(row));
  const errors: FormErrors = { rows: {}, settings: {}, general: [] };
  for (const issue of issues) {
    const loc = issue.loc[0] === "body" ? issue.loc.slice(1) : issue.loc;
    if (loc[0] === "items" && typeof loc[1] === "number" && typeof loc[2] === "string" && sent[loc[1]]) {
      const key = sent[loc[1]]!.key;
      errors.rows[key] = { ...errors.rows[key], [loc[2]]: issue.msg };
    } else if (loc[0] === "settings" && typeof loc[1] === "string") {
      (errors.settings as Record<string, string>)[loc[1]] = issue.msg;
    } else if (loc[0] === "name") {
      errors.name = issue.msg;
    } else {
      errors.general.push(issue.msg);
    }
  }
  return errors;
}
