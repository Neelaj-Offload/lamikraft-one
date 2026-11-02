/**
 * Parties (customers) as the web uses them.
 *
 * The shapes mirror backend/app/modules/parties/schemas.py (`PartySummary`, `PartyDetail`,
 * `ContactRead`, `AddressRead`, `TaxIdentifierRead`, `PartyCreate`, `PartyUpdate`, `ContactIn`,
 * `AddressIn`). INTERIM(api-generate): replace with `components["schemas"][...]`; `api.ts` and
 * `parse.ts` are the only places that touch the wire.
 */

import type { Capability, TransitionOption, UserRef } from "@/features/sales/types";

export const PARTY_ROLES = ["customer", "vendor", "fabricator", "job_worker"] as const;
export type PartyRole = (typeof PARTY_ROLES)[number];

export const PARTY_STATUSES = ["prospect", "active", "inactive", "blocked"] as const;
export type PartyStatus = (typeof PARTY_STATUSES)[number];

export const CUSTOMER_TYPES = ["standard", "dealer", "distributor"] as const;
export type CustomerType = (typeof CUSTOMER_TYPES)[number];

export const ADDRESS_KINDS = ["billing", "shipping"] as const;
export type AddressKind = (typeof ADDRESS_KINDS)[number];

export const TAX_SCHEMES = ["gstin", "vat", "eori", "pan", "iec", "other"] as const;
export type TaxScheme = (typeof TAX_SCHEMES)[number];

export interface PartySummary {
  id: string;
  party_number: string;
  legal_name: string;
  display_name: string;
  country_code: string;
  default_currency: string;
  customer_type: CustomerType | null;
  roles: PartyRole[];
  status: PartyStatus;
  owner: UserRef;
  branch_id: string | null;
  primary_contact: string | null;
  updated_at: string;
  path: string;
}

export interface Contact {
  id: string;
  name: string;
  job_title: string | null;
  email: string | null;
  phone: string | null;
  is_primary: boolean;
}

export interface Address {
  id: string;
  kind: AddressKind;
  line1: string;
  line2: string | null;
  city: string | null;
  region: string | null;
  postal_code: string | null;
  country_code: string;
  is_default: boolean;
}

export interface TaxIdentifier {
  id: string;
  scheme: TaxScheme;
  value: string;
  country_code: string | null;
  verification_status: "unverified";
}

export interface PartyDetail extends PartySummary {
  contacts: Contact[];
  addresses: Address[];
  tax_identifiers: TaxIdentifier[];
  version: number;
  created_at: string;
  archived_at: string | null;
  capabilities: Readonly<Record<string, Capability>>;
  allowed_transitions: TransitionOption[];
}

// ---------------------------------------------------------------------------------------------
// Requests

export interface ContactRequest {
  id?: string;
  name: string;
  job_title?: string | null;
  email?: string | null;
  phone?: string | null;
  is_primary?: boolean;
}

export interface AddressRequest {
  id?: string;
  kind: AddressKind;
  line1: string;
  line2?: string | null;
  city?: string | null;
  region?: string | null;
  postal_code?: string | null;
  country_code: string;
  is_default?: boolean;
}

export interface PartyCreateRequest {
  legal_name: string;
  display_name?: string;
  country_code: string;
  default_currency: string;
  customer_type?: CustomerType | null;
  roles: PartyRole[];
  status?: PartyStatus;
  contacts?: ContactRequest[];
  addresses?: AddressRequest[];
}

/** The editable header fields of a party (the Edit drawer). */
export interface PartyHeaderFields {
  legal_name: string;
  display_name: string;
  country_code: string;
  default_currency: string;
  customer_type: CustomerType | null;
  status: PartyStatus;
  roles: PartyRole[];
}

/** Dirty fields plus `expected_version`; child lists, when sent, replace the current set. */
export interface PartyUpdateRequest extends Partial<PartyHeaderFields> {
  expected_version: number;
  contacts?: ContactRequest[];
  addresses?: AddressRequest[];
}
