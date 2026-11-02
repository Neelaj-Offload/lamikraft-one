/**
 * Pure helpers behind the customer forms (tested without React): the Edit drawer's dirty-field
 * diff and three-way merge after a 409, client-side rules the server also enforces, the New
 * customer body, and the mapping of 422 `errors[{loc,msg}]` onto form fields.
 */

import { ProblemError } from "@/lib/api/errors";
import { CURRENCIES } from "@/lib/format/money";
import { partiesMessages as m } from "@/messages/parties";
import type {
  Address,
  AddressRequest,
  Contact,
  ContactRequest,
  CustomerType,
  PartyCreateRequest,
  PartyDetail,
  PartyHeaderFields,
  PartyRole,
  PartyStatus,
} from "./types";

export const HEADER_FIELDS = ["legal_name", "display_name", "country_code", "default_currency", "customer_type", "status", "roles"] as const satisfies readonly (keyof PartyHeaderFields)[];
export type HeaderField = (typeof HEADER_FIELDS)[number];

export const COUNTRY_PATTERN = /^[A-Z]{2}$/;

/** Country codes are two upper-case letters; the server upper-cases too, the field does it on blur. */
export function normaliseCountry(value: string): string {
  return value.trim().toUpperCase();
}

// ---- the Edit drawer -------------------------------------------------------------------------

export function headerFormOf(party: PartyDetail): PartyHeaderFields {
  return {
    legal_name: party.legal_name,
    display_name: party.display_name,
    country_code: party.country_code,
    default_currency: party.default_currency,
    customer_type: party.customer_type,
    status: party.status,
    roles: [...party.roles],
  };
}

/** The value as the server would store it: trimmed, country upper-cased, roles as a set. */
function normalised(field: HeaderField, form: PartyHeaderFields): string {
  if (field === "roles") return [...form.roles].sort().join(",");
  if (field === "country_code") return normaliseCountry(form.country_code);
  return (form[field] ?? "").trim();
}

function sameValue(field: HeaderField, a: PartyHeaderFields, b: PartyHeaderFields): boolean {
  return normalised(field, a) === normalised(field, b);
}

export function dirtyHeaderFields(base: PartyHeaderFields, form: PartyHeaderFields): HeaderField[] {
  return HEADER_FIELDS.filter((field) => !sameValue(field, base, form));
}

/** The `PartyUpdate` body without `expected_version`: only the dirty fields, trimmed. */
export function headerChanges(base: PartyHeaderFields, form: PartyHeaderFields): Partial<PartyHeaderFields> {
  const changes: Partial<PartyHeaderFields> = {};
  for (const field of dirtyHeaderFields(base, form)) {
    switch (field) {
      case "legal_name":
        changes.legal_name = form.legal_name.trim();
        break;
      case "display_name":
        changes.display_name = form.display_name.trim();
        break;
      case "country_code":
        changes.country_code = normaliseCountry(form.country_code);
        break;
      case "default_currency":
        changes.default_currency = form.default_currency;
        break;
      case "customer_type":
        changes.customer_type = form.customer_type;
        break;
      case "status":
        changes.status = form.status;
        break;
      case "roles":
        changes.roles = [...form.roles];
        break;
    }
  }
  return changes;
}

/** Client-side rules the server enforces too (so a 422 is the exception, not the flow). */
export function validateHeader(form: PartyHeaderFields): Partial<Record<HeaderField, string>> {
  const errors: Partial<Record<HeaderField, string>> = {};
  if (!form.legal_name.trim()) errors.legal_name = m.edit.legalNameRequired;
  if (!COUNTRY_PATTERN.test(normaliseCountry(form.country_code))) errors.country_code = m.edit.countryInvalid;
  if (!CURRENCIES.some((code) => code === form.default_currency)) errors.default_currency = m.edit.currencyRequired;
  if (form.roles.length === 0) errors.roles = m.edit.rolesRequired;
  return errors;
}

export interface HeaderMerge {
  base: PartyHeaderFields;
  form: PartyHeaderFields;
  /** Fields taken over from the latest version because this person had not changed them. */
  adopted: HeaderField[];
}

/**
 * Three-way merge after a 409: fields this person did not touch take the latest version;
 * fields they changed keep their value (the server's version becomes the new base, so the
 * next save carries the latest `expected_version`).
 */
export function mergeHeaderConflict(base: PartyHeaderFields, form: PartyHeaderFields, latest: PartyHeaderFields): HeaderMerge {
  const dirty = new Set(dirtyHeaderFields(base, form));
  const pick = <K extends HeaderField>(field: K): PartyHeaderFields[K] => (dirty.has(field) ? form[field] : latest[field]);
  const merged: PartyHeaderFields = {
    legal_name: pick("legal_name"),
    display_name: pick("display_name"),
    country_code: pick("country_code"),
    default_currency: pick("default_currency"),
    customer_type: pick("customer_type"),
    status: pick("status"),
    roles: [...pick("roles")],
  };
  const adopted = HEADER_FIELDS.filter((field) => !dirty.has(field) && !sameValue(field, base, latest));
  return { base: { ...latest, roles: [...latest.roles] }, form: merged, adopted };
}

// ---- contacts ---------------------------------------------------------------------------------

/** `PartyUpdate.contacts` replaces the set: the existing rows (by id) plus the new one. */
export function contactsWith(existing: readonly Contact[], added: ContactRequest): ContactRequest[] {
  const current = existing.map<ContactRequest>((contact) => ({
    id: contact.id,
    name: contact.name,
    job_title: contact.job_title,
    email: contact.email,
    phone: contact.phone,
    is_primary: added.is_primary ? false : contact.is_primary,
  }));
  return [...current, added];
}

export interface ContactForm {
  name: string;
  job_title: string;
  email: string;
  phone: string;
  is_primary: boolean;
}

export const EMPTY_CONTACT: ContactForm = { name: "", job_title: "", email: "", phone: "", is_primary: false };

export function contactRequestOf(form: ContactForm): ContactRequest | null {
  const name = form.name.trim();
  if (!name) return null;
  return {
    name,
    job_title: form.job_title.trim() || null,
    email: form.email.trim() || null,
    phone: form.phone.trim() || null,
    is_primary: form.is_primary,
  };
}

// ---- addresses --------------------------------------------------------------------------------

/** The lines of a postal address block, empty parts dropped. */
export function addressLines(address: Pick<Address, "line1" | "line2" | "city" | "region" | "postal_code" | "country_code">): string[] {
  const locality = [address.city, address.region, address.postal_code].filter((part): part is string => Boolean(part && part.trim())).join(", ");
  return [address.line1, address.line2 ?? "", locality, address.country_code].filter((line) => line.trim() !== "");
}

// ---- the New customer form --------------------------------------------------------------------

export interface CreateForm {
  legal_name: string;
  display_name: string;
  country_code: string;
  default_currency: string | null;
  customer_type: CustomerType | null;
  roles: PartyRole[];
  status: PartyStatus;
  contact: { name: string; email: string; phone: string };
  address: { line1: string; line2: string; city: string; region: string; postal_code: string; country_code: string };
}

export const EMPTY_CREATE: CreateForm = {
  legal_name: "",
  display_name: "",
  country_code: "",
  default_currency: null,
  customer_type: null,
  roles: ["customer"],
  status: "active",
  contact: { name: "", email: "", phone: "" },
  address: { line1: "", line2: "", city: "", region: "", postal_code: "", country_code: "" },
};

const contactFilled = (contact: CreateForm["contact"]) => Object.values(contact).some((value) => value.trim() !== "");
const addressFilled = (address: CreateForm["address"]) => Object.values(address).some((value) => value.trim() !== "");

/** Client-side rules; keys match `fieldLabels` in the copy and the 422 mapping below. */
export function validateCreate(form: CreateForm): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!form.legal_name.trim()) errors.legal_name = m.edit.legalNameRequired;
  if (!COUNTRY_PATTERN.test(normaliseCountry(form.country_code))) errors.country_code = m.edit.countryInvalid;
  if (!form.default_currency || !CURRENCIES.some((code) => code === form.default_currency)) errors.default_currency = m.edit.currencyRequired;
  if (form.roles.length === 0) errors.roles = m.edit.rolesRequired;
  if (contactFilled(form.contact) && !form.contact.name.trim()) errors["contact.name"] = m.create.contactNameRequired;
  if (addressFilled(form.address)) {
    if (!form.address.line1.trim()) errors["address.line1"] = m.create.line1Required;
    const country = normaliseCountry(form.address.country_code || form.country_code);
    if (!COUNTRY_PATTERN.test(country)) errors["address.country_code"] = m.edit.countryInvalid;
  }
  return errors;
}

/** The `PartyCreate` body, or null while the form is invalid. The address country defaults to the party's. */
export function createBodyOf(form: CreateForm): PartyCreateRequest | null {
  if (Object.keys(validateCreate(form)).length > 0 || !form.default_currency) return null;
  const body: PartyCreateRequest = {
    legal_name: form.legal_name.trim(),
    country_code: normaliseCountry(form.country_code),
    default_currency: form.default_currency,
    roles: [...form.roles],
    status: form.status,
  };
  if (form.display_name.trim()) body.display_name = form.display_name.trim();
  if (form.customer_type) body.customer_type = form.customer_type;
  if (contactFilled(form.contact)) {
    body.contacts = [
      {
        name: form.contact.name.trim(),
        email: form.contact.email.trim() || null,
        phone: form.contact.phone.trim() || null,
        is_primary: true,
      },
    ];
  }
  if (addressFilled(form.address)) {
    const address: AddressRequest = {
      kind: "billing",
      line1: form.address.line1.trim(),
      line2: form.address.line2.trim() || null,
      city: form.address.city.trim() || null,
      region: form.address.region.trim() || null,
      postal_code: form.address.postal_code.trim() || null,
      country_code: normaliseCountry(form.address.country_code || form.country_code),
      is_default: true,
    };
    body.addresses = [address];
  }
  return body;
}

/**
 * 422 `errors[{loc, msg}]` → form fields. `["body","contacts",0,"email"]` becomes `contact.email`,
 * `["body","addresses",0,"line1"]` becomes `address.line1`, anything else keeps its last segment.
 */
export function fieldErrorsFrom(error: unknown): Record<string, string> {
  if (!(error instanceof ProblemError) || error.status !== 422) return {};
  const errors: Record<string, string> = {};
  for (const issue of error.validationIssues) {
    const parts = issue.loc.filter((part) => part !== "body").map(String);
    const last = parts.at(-1);
    if (!last) continue;
    const key = parts[0] === "contacts" && parts.length > 1 ? `contact.${last}` : parts[0] === "addresses" && parts.length > 1 ? `address.${last}` : last;
    if (!errors[key]) errors[key] = issue.msg;
  }
  return errors;
}

/** A readable list of the fields in error, for the alert summary. */
export function errorSummary(errors: Record<string, string>, labels: Record<string, string>): { label: string; message: string }[] {
  return Object.entries(errors).map(([key, message]) => ({ label: labels[key] ?? key, message }));
}
