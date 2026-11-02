/**
 * Runtime readers for the parties API (see types.ts). Required fields are checked; links must
 * stay inside the app; unknown enum values fall back to a safe default rather than being
 * forwarded raw.
 */

import { capabilities, pageOf, transitions } from "@/features/sales/parse";
import type { Page, UserRef } from "@/features/sales/types";
import { safeAppPath } from "@/lib/safe-path";
import {
  ADDRESS_KINDS,
  CUSTOMER_TYPES,
  PARTY_ROLES,
  PARTY_STATUSES,
  TAX_SCHEMES,
  type Address,
  type Contact,
  type PartyDetail,
  type PartyRole,
  type PartySummary,
  type TaxIdentifier,
} from "./types";

export class PartiesShapeError extends Error {
  override readonly name = "PartiesShapeError";
}

type Json = Record<string, unknown>;
const isObject = (value: unknown): value is Json => value !== null && typeof value === "object" && !Array.isArray(value);
const str = (value: unknown): string | null => (typeof value === "string" && value !== "" ? value : null);
const arr = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const int = (value: unknown): number | null => (typeof value === "number" && Number.isInteger(value) ? value : null);

function user(value: unknown): UserRef {
  return isObject(value) && str(value.id) ? { id: str(value.id)!, display_name: str(value.display_name) } : { id: "", display_name: null };
}

function roles(value: unknown): PartyRole[] {
  return arr(value).filter((role): role is PartyRole => PARTY_ROLES.some((known) => known === role));
}

export function parsePartySummary(raw: unknown): PartySummary | null {
  if (!isObject(raw) || !str(raw.id) || !str(raw.party_number)) return null;
  const id = str(raw.id)!;
  const displayName = str(raw.display_name) ?? str(raw.legal_name) ?? str(raw.party_number)!;
  return {
    id,
    party_number: str(raw.party_number)!,
    legal_name: str(raw.legal_name) ?? displayName,
    display_name: displayName,
    country_code: str(raw.country_code) ?? "",
    default_currency: str(raw.default_currency) ?? "",
    customer_type: CUSTOMER_TYPES.find((type) => type === raw.customer_type) ?? null,
    roles: roles(raw.roles),
    status: PARTY_STATUSES.find((status) => status === raw.status) ?? "active",
    owner: user(raw.owner),
    branch_id: str(raw.branch_id),
    primary_contact: str(raw.primary_contact),
    updated_at: str(raw.updated_at) ?? "",
    path: safeAppPath(raw.path) ?? `/sales/parties/${encodeURIComponent(id)}`,
  };
}

export function parseContact(raw: unknown): Contact | null {
  if (!isObject(raw) || !str(raw.id) || !str(raw.name)) return null;
  return {
    id: str(raw.id)!,
    name: str(raw.name)!,
    job_title: str(raw.job_title),
    email: str(raw.email),
    phone: str(raw.phone),
    is_primary: raw.is_primary === true,
  };
}

export function parseAddress(raw: unknown): Address | null {
  if (!isObject(raw) || !str(raw.id) || !str(raw.line1)) return null;
  return {
    id: str(raw.id)!,
    kind: ADDRESS_KINDS.find((kind) => kind === raw.kind) ?? "billing",
    line1: str(raw.line1)!,
    line2: str(raw.line2),
    city: str(raw.city),
    region: str(raw.region),
    postal_code: str(raw.postal_code),
    country_code: str(raw.country_code) ?? "",
    is_default: raw.is_default === true,
  };
}

export function parseTaxIdentifier(raw: unknown): TaxIdentifier | null {
  if (!isObject(raw) || !str(raw.id) || !str(raw.value)) return null;
  return {
    id: str(raw.id)!,
    scheme: TAX_SCHEMES.find((scheme) => scheme === raw.scheme) ?? "other",
    value: str(raw.value)!,
    country_code: str(raw.country_code),
    verification_status: "unverified",
  };
}

export function parsePartyDetail(raw: unknown): PartyDetail {
  const summary = parsePartySummary(raw);
  if (!summary || !isObject(raw) || int(raw.version) === null) throw new PartiesShapeError("The customer could not be read.");
  return {
    ...summary,
    contacts: arr(raw.contacts)
      .map(parseContact)
      .filter((contact): contact is Contact => contact !== null),
    addresses: arr(raw.addresses)
      .map(parseAddress)
      .filter((address): address is Address => address !== null),
    tax_identifiers: arr(raw.tax_identifiers)
      .map(parseTaxIdentifier)
      .filter((identifier): identifier is TaxIdentifier => identifier !== null),
    version: int(raw.version)!,
    created_at: str(raw.created_at) ?? "",
    archived_at: str(raw.archived_at),
    capabilities: capabilities(raw.capabilities),
    allowed_transitions: transitions(raw.allowed_transitions),
  };
}

export function parsePartyPage(raw: unknown): Page<PartySummary> {
  return pageOf(raw, parsePartySummary);
}
