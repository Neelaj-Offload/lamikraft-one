/**
 * Company settings as the screen sees them: a `SettingRead.value` flattened one level for the
 * read-only grid, and a per-key form schema (from backend/app/platform/org/settings.py) that
 * generates the editor and turns its draft back into the typed value the server validates.
 * Decimals stay strings; only declared integer fields are converted, with `Number.parseInt`.
 */

import type { Json, SettingRead } from "./types";

const isObject = (value: unknown): value is Json => value !== null && typeof value === "object" && !Array.isArray(value);

// ---- labels -----------------------------------------------------------------------------------

const LABELS: Record<string, string> = {
  legal_name: "Legal name",
  display_name: "Display name",
  address_lines: "Address",
  gstin: "GSTIN",
  pan: "PAN",
  iec: "IEC",
  contacts: "Contacts",
  email: "Email",
  phone: "Phone",
  website: "Website",
  logo_file_id: "Logo file",
  accounts: "Account",
  label: "Label",
  account_name: "Account name",
  bank_name: "Bank",
  branch_name: "Branch",
  account_number: "Account number",
  account_number_last4: "Account number (last 4)",
  ifsc: "IFSC",
  swift_bic: "SWIFT / BIC",
  currency: "Currency",
  is_default: "Default account",
  quote: "Quote terms",
  challan: "Challan terms",
  footer: "Document footer",
  brands: "Brand",
  token: "Token",
  name: "Name",
  incoterm: "Incoterm",
  validity_days: "Validity (days)",
  brand: "Brand",
  price_type: "Price type",
  duplicate_copies_assignee: "A duplicated quote is assigned to whoever duplicates it",
};

const MONO = new Set(["gstin", "pan", "iec", "ifsc", "swift_bic", "account_number", "account_number_last4", "token", "currency", "brand", "logo_file_id", "incoterm"]);

export function labelFor(name: string): string {
  const known = LABELS[name];
  if (known) return known;
  const words = name.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// ---- read-only flattening ---------------------------------------------------------------------

export interface FlatValue {
  /** Dotted path with list indexes, e.g. `accounts[0].ifsc`. */
  path: string;
  term: string;
  /** Null when absent (shown as "Not configured"). */
  value: string | boolean | null;
  mono: boolean;
}

/** `accounts[0].ifsc` → `accounts[].ifsc`, the form the server uses in `redacted_fields`. */
export function normalisePath(path: string): string {
  return path.replace(/\[\d+\]/g, "[]");
}

function scalarText(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return JSON.stringify(value);
}

/**
 * One row per leaf, nested objects as "Section · Field", list items numbered, scalar arrays
 * joined, booleans kept (the grid prints Yes/No). Redacted paths are left out entirely.
 */
export function flattenValue(value: Json, redacted: readonly string[] = []): FlatValue[] {
  const hidden = new Set(redacted.map(normalisePath));
  const out: FlatValue[] = [];
  const visit = (node: unknown, path: string, term: string, name: string) => {
    if (hidden.has(normalisePath(path))) return;
    if (isObject(node)) {
      for (const [key, child] of Object.entries(node)) visit(child, path ? `${path}.${key}` : key, term ? `${term} · ${labelFor(key)}` : labelFor(key), key);
      return;
    }
    if (Array.isArray(node)) {
      if (node.some(isObject)) {
        node.forEach((item, index) => visit(item, `${path}[${index}]`, `${labelFor(name)} ${index + 1}`, name));
        return;
      }
      const joined = node.map(scalarText).filter((text): text is string => text !== null);
      out.push({ path, term, value: joined.length ? joined.join(", ") : null, mono: MONO.has(name) });
      return;
    }
    out.push({ path, term, value: typeof node === "boolean" ? node : scalarText(node), mono: MONO.has(name) });
  };
  visit(value, "", "", "");
  return out;
}

// ---- editor schema ----------------------------------------------------------------------------

export type FieldKind = "text" | "textarea" | "code" | "switch" | "integer" | "decimal" | "select" | "lines" | "csv";

export interface FieldDef {
  name: string;
  label: string;
  kind: FieldKind;
  options?: readonly { id: string; label: string }[];
  description?: string;
  maxLength?: number;
  required?: boolean;
}

export interface GroupDef {
  name: string;
  label: string;
  fields: readonly FieldDef[];
}

export interface ListDef {
  name: string;
  label: string;
  /** Singular, for "Add account" / "Remove account". */
  itemLabel: string;
  fields: readonly FieldDef[];
  max?: number;
}

export interface SettingForm {
  fields: readonly FieldDef[];
  groups: readonly GroupDef[];
  lists: readonly ListDef[];
}

const INCOTERMS = ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"] as const;
const PRICE_TYPES = [
  { id: "export", label: "Export" },
  { id: "domestic", label: "Domestic" },
  { id: "sample", label: "Sample" },
  { id: "distributor", label: "Distributor" },
] as const;

const text = (name: string, extra: Partial<FieldDef> = {}): FieldDef => ({ name, label: labelFor(name), kind: "text", ...extra });
const code = (name: string, extra: Partial<FieldDef> = {}): FieldDef => ({ name, label: labelFor(name), kind: "code", ...extra });

/** Editor schemas for the built-in settings (settings.py `BUILTIN_SETTINGS`). */
export const SETTING_FORMS: Record<string, SettingForm> = {
  company_identity: {
    fields: [
      text("legal_name", { maxLength: 200 }),
      text("display_name", { maxLength: 120 }),
      { name: "address_lines", label: labelFor("address_lines"), kind: "lines", description: "One line per row; up to 6 lines." },
      code("gstin", { maxLength: 15 }),
      code("pan", { maxLength: 10 }),
      code("iec", { maxLength: 10 }),
    ],
    groups: [
      {
        name: "contacts",
        label: labelFor("contacts"),
        fields: [text("email", { maxLength: 254 }), text("phone", { maxLength: 25 }), text("website", { maxLength: 210, description: "Starts with http:// or https://." })],
      },
    ],
    lists: [],
  },
  bank_details: {
    fields: [],
    groups: [],
    lists: [
      {
        name: "accounts",
        label: "Bank accounts",
        itemLabel: "account",
        max: 10,
        fields: [
          text("label", { maxLength: 80, required: true }),
          text("account_name", { maxLength: 120 }),
          text("bank_name", { maxLength: 120, required: true }),
          text("branch_name", { maxLength: 120 }),
          code("account_number", { maxLength: 34 }),
          code("ifsc", { maxLength: 11 }),
          code("swift_bic", { maxLength: 11 }),
          code("currency", { maxLength: 3 }),
          { name: "is_default", label: labelFor("is_default"), kind: "switch" },
        ],
      },
    ],
  },
  document_terms: {
    fields: [
      { name: "quote", label: labelFor("quote"), kind: "textarea", maxLength: 8000 },
      { name: "challan", label: labelFor("challan"), kind: "textarea", maxLength: 8000 },
      { name: "footer", label: labelFor("footer"), kind: "textarea", maxLength: 1000 },
    ],
    groups: [],
    lists: [],
  },
  quote_defaults: {
    fields: [
      code("currency", { maxLength: 3, required: true }),
      { name: "incoterm", label: labelFor("incoterm"), kind: "select", options: INCOTERMS.map((term) => ({ id: term, label: term })), required: true },
      { name: "validity_days", label: labelFor("validity_days"), kind: "integer", description: "1 to 365.", required: true },
      code("brand", { maxLength: 4, required: true, description: "One of the configured brand tokens." }),
      { name: "price_type", label: labelFor("price_type"), kind: "select", options: PRICE_TYPES, required: true },
      { name: "duplicate_copies_assignee", label: labelFor("duplicate_copies_assignee"), kind: "switch" },
    ],
    groups: [],
    lists: [],
  },
  brands: {
    fields: [],
    groups: [],
    lists: [
      {
        name: "brands",
        label: "Brands",
        itemLabel: "brand",
        max: 20,
        fields: [code("token", { maxLength: 4, required: true, description: "2 to 4 capital letters; appears in document numbers." }), text("name", { maxLength: 80, required: true })],
      },
    ],
  },
};

/** A schema inferred from a value's shape, for settings other modules register later. */
export function inferForm(value: Json): SettingForm {
  const fieldFor = (name: string, sample: unknown): FieldDef => {
    const label = labelFor(name);
    if (typeof sample === "boolean") return { name, label, kind: "switch" };
    if (typeof sample === "number") return { name, label, kind: Number.isInteger(sample) ? "integer" : "decimal" };
    if (Array.isArray(sample)) return { name, label, kind: "csv" };
    return { name, label, kind: typeof sample === "string" && sample.length > 120 ? "textarea" : "text" };
  };
  const fields: FieldDef[] = [];
  const groups: GroupDef[] = [];
  const lists: ListDef[] = [];
  for (const [name, sample] of Object.entries(value)) {
    if (isObject(sample)) groups.push({ name, label: labelFor(name), fields: Object.entries(sample).map(([key, child]) => fieldFor(key, child)) });
    else if (Array.isArray(sample) && sample.some(isObject)) {
      const first = sample.find(isObject)!;
      lists.push({ name, label: labelFor(name), itemLabel: labelFor(name).toLowerCase(), fields: Object.entries(first).map(([key, child]) => fieldFor(key, child)) });
    } else fields.push(fieldFor(name, sample));
  }
  return { fields, groups, lists };
}

export function formFor(setting: Pick<SettingRead, "key" | "value">): SettingForm {
  return SETTING_FORMS[setting.key] ?? inferForm(setting.value);
}

/** The schema without fields this actor cannot see (they would be wiped on save). */
export function visibleForm(form: SettingForm, redacted: readonly string[]): SettingForm {
  const hidden = new Set(redacted.map(normalisePath));
  return {
    fields: form.fields.filter((field) => !hidden.has(field.name)),
    groups: form.groups.map((group) => ({ ...group, fields: group.fields.filter((field) => !hidden.has(`${group.name}.${field.name}`)) })),
    lists: form.lists.map((list) => ({ ...list, fields: list.fields.filter((field) => !hidden.has(`${list.name}[].${field.name}`)) })),
  };
}

// ---- draft <-> value --------------------------------------------------------------------------

export type DraftScalar = string | boolean;
export type DraftRecord = Record<string, DraftScalar>;

export interface SettingDraft {
  fields: DraftRecord;
  groups: Record<string, DraftRecord>;
  lists: Record<string, DraftRecord[]>;
}

function draftScalar(field: FieldDef, value: unknown): DraftScalar {
  switch (field.kind) {
    case "switch":
      return value === true;
    case "lines":
      return Array.isArray(value) ? value.filter((line): line is string => typeof line === "string").join("\n") : "";
    case "csv":
      return Array.isArray(value) ? value.filter((entry) => entry !== null && typeof entry !== "object").map(String).join(", ") : "";
    default:
      return value === null || value === undefined ? "" : typeof value === "string" ? value : String(value);
  }
}

function draftRecord(fields: readonly FieldDef[], source: unknown): DraftRecord {
  const node = isObject(source) ? source : {};
  return Object.fromEntries(fields.map((field) => [field.name, draftScalar(field, node[field.name])]));
}

export function emptyItem(list: ListDef): DraftRecord {
  return draftRecord(list.fields, {});
}

export function draftFrom(form: SettingForm, value: Json): SettingDraft {
  return {
    fields: draftRecord(form.fields, value),
    groups: Object.fromEntries(form.groups.map((group) => [group.name, draftRecord(group.fields, value[group.name])])),
    lists: Object.fromEntries(
      form.lists.map((list) => [list.name, (Array.isArray(value[list.name]) ? (value[list.name] as unknown[]) : []).map((item) => draftRecord(list.fields, item))]),
    ),
  };
}

export const FIELD_ERRORS = {
  required: "Enter a value.",
  integer: "Enter a whole number.",
} as const;

type Converted = { ok: true; value: unknown } | { ok: false; error: string };

function convert(field: FieldDef, draft: DraftScalar | undefined): Converted {
  if (field.kind === "switch") return { ok: true, value: draft === true };
  const raw = typeof draft === "string" ? draft.trim() : "";
  if (raw === "") return field.required ? { ok: false, error: FIELD_ERRORS.required } : { ok: true, value: null };
  switch (field.kind) {
    case "integer": {
      if (!/^-?\d{1,12}$/.test(raw)) return { ok: false, error: FIELD_ERRORS.integer };
      return { ok: true, value: Number.parseInt(raw, 10) };
    }
    case "code":
      return { ok: true, value: raw.toUpperCase().replace(/\s+/g, "") };
    case "lines":
      return { ok: true, value: raw.split(/\r?\n/).map((line) => line.trim()).filter(Boolean) };
    case "csv":
      return { ok: true, value: raw.split(",").map((entry) => entry.trim()).filter(Boolean) };
    default:
      return { ok: true, value: raw };
  }
}

export interface ValueResult {
  value: Json;
  /** Client-side problems keyed by draft path (`accounts[1].label`); empty when the value is ready. */
  errors: Record<string, string>;
}

const clone = <T>(value: T): T => (value === undefined ? value : (JSON.parse(JSON.stringify(value)) as T));

function applyRecord(fields: readonly FieldDef[], draft: DraftRecord, target: Json, prefix: string, errors: Record<string, string>): void {
  for (const field of fields) {
    const result = convert(field, draft[field.name]);
    if (result.ok) target[field.name] = result.value;
    else errors[`${prefix}${field.name}`] = result.error;
  }
}

/**
 * The value to send: the original (so keys the form does not edit, such as derived or
 * redacted ones, are kept as they were) overwritten with the draft's typed fields. Redacted
 * paths are removed so a null never overwrites a value this actor cannot see.
 */
export function valueFrom(form: SettingForm, draft: SettingDraft, original: Json, redacted: readonly string[] = []): ValueResult {
  const value = clone(original);
  const errors: Record<string, string> = {};
  applyRecord(form.fields, draft.fields, value, "", errors);
  for (const group of form.groups) {
    const target = isObject(value[group.name]) ? (value[group.name] as Json) : {};
    applyRecord(group.fields, draft.groups[group.name] ?? {}, target, `${group.name}.`, errors);
    value[group.name] = target;
  }
  for (const list of form.lists) {
    const originalItems = Array.isArray(original[list.name]) ? (original[list.name] as unknown[]) : [];
    value[list.name] = (draft.lists[list.name] ?? []).map((item, index) => {
      const target = isObject(originalItems[index]) ? clone(originalItems[index] as Json) : {};
      applyRecord(list.fields, item, target, `${list.name}[${index}].`, errors);
      return target;
    });
  }
  for (const path of redacted) {
    const [head, ...rest] = path.split(".");
    if (!head) continue;
    const listName = head.endsWith("[]") ? head.slice(0, -2) : null;
    if (listName && rest.length === 1 && Array.isArray(value[listName])) {
      for (const item of value[listName] as unknown[]) if (isObject(item)) delete item[rest[0]!];
    } else if (rest.length === 0) delete value[head];
    else if (rest.length === 1 && isObject(value[head])) delete (value[head] as Json)[rest[0]!];
  }
  return { value, errors };
}

/** `["body","value","accounts",1,"label"]` → `accounts[1].label`, the draft path a 422 points at. */
export function fieldPathFromLoc(loc: ReadonlyArray<string | number>): string {
  const start = loc.indexOf("value");
  const parts = start === -1 ? loc : loc.slice(start + 1);
  let out = "";
  for (const part of parts) {
    if (typeof part === "number") out += `[${part}]`;
    else out += out ? `.${part}` : part;
  }
  return out;
}
