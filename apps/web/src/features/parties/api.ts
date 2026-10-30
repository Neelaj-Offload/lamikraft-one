/**
 * Parties API adapter and wire types (INTERIM(api-generate): hand-written from `backend/app/modules/parties`).
 */

import { api, idempotencyHeaders, requestUntyped, type ApiClient } from "@/lib/api/client";

export const PARTIES = "/api/v1/parties";
const party = (id: string): `/api/v1/${string}` => `${PARTIES}/parties/${encodeURIComponent(id)}`;

export const PARTY_ROLES = ["customer", "vendor", "fabricator", "job_worker"] as const;
export const PARTY_STATUSES = ["prospect", "active", "inactive", "blocked"] as const;
export const CURRENCIES = ["INR", "EUR", "USD", "GBP"] as const;

export interface Capability {
  allowed: boolean;
  reason_code: string | null;
}

export interface PartySummary {
  id: string;
  party_number: string;
  legal_name: string;
  display_name: string;
  country_code: string;
  default_currency: string;
  customer_type: string | null;
  roles: string[];
  status: string;
  owner: { id: string; display_name: string | null };
  primary_contact: string | null;
  updated_at: string;
  path: string;
}

export interface ContactRead {
  id?: string;
  name: string;
  job_title: string | null;
  email: string | null;
  phone: string | null;
  is_primary: boolean;
}

export interface AddressRead {
  id?: string;
  kind: "billing" | "shipping";
  line1: string;
  line2: string | null;
  city: string | null;
  region: string | null;
  postal_code: string | null;
  country_code: string;
  is_default: boolean;
}

export interface PartyDetail extends PartySummary {
  contacts: ContactRead[];
  addresses: AddressRead[];
  tax_identifiers: { id: string; scheme: string; value: string; country_code: string | null }[];
  version: number;
  created_at: string;
  archived_at: string | null;
  capabilities: Record<string, Capability>;
}

export interface CustomerTypeRead {
  id: string;
  code: string;
  label: string;
  description: string | null;
  display_order: number;
  is_active: boolean;
  is_system: boolean;
  party_count: number;
  version: number;
  capabilities: Record<string, Capability>;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface PartyListState {
  q: string;
  role: string | null;
  customerType: string | null;
  archived: boolean;
  offset: number;
}

type Search = Record<string, string | string[] | undefined>;
const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

export function partyListStateFrom(search: Search): PartyListState {
  const raw = Number.parseInt(first(search.offset) ?? "0", 10);
  const role = first(search.role);
  const type = first(search.type) ?? "";
  return {
    q: (first(search.q) ?? "").slice(0, 200),
    role: PARTY_ROLES.find((r) => r === role) ?? null,
    customerType: /^[a-z][a-z0-9_]{1,19}$/.test(type) ? type : null,
    archived: first(search.archived) === "true",
    offset: Number.isFinite(raw) && raw > 0 ? raw - (raw % 25) : 0,
  };
}

export function partyListHref(state: Partial<PartyListState>): string {
  const query = new URLSearchParams();
  if (state.q?.trim()) query.set("q", state.q.trim());
  if (state.role) query.set("role", state.role);
  if (state.customerType) query.set("type", state.customerType);
  if (state.archived) query.set("archived", "true");
  if (state.offset) query.set("offset", String(state.offset));
  const search = query.toString();
  return search ? `/sales/parties?${search}` : "/sales/parties";
}

export const fetchParties = (state: PartyListState, signal?: AbortSignal, client: ApiClient = api): Promise<Page<PartySummary>> =>
  requestUntyped(client, "get", `${PARTIES}/parties`, {
    params: {
      query: {
        q: state.q.trim() || undefined,
        role: state.role,
        customer_type: state.customerType,
        include_archived: state.archived || undefined,
        offset: state.offset,
        limit: 25,
      },
    },
    signal,
  });

export const fetchParty = (id: string, signal?: AbortSignal, client: ApiClient = api): Promise<PartyDetail> =>
  requestUntyped(client, "get", party(id), { signal });

export const createParty = (body: Record<string, unknown>, key: string, client: ApiClient = api): Promise<PartyDetail> =>
  requestUntyped(client, "post", `${PARTIES}/parties`, { body, headers: idempotencyHeaders(key) });

export const updateParty = (id: string, body: Record<string, unknown>, client: ApiClient = api): Promise<PartyDetail> =>
  requestUntyped(client, "patch", party(id), { body });

export const setPartyArchived = (id: string, archived: boolean, version: number, client: ApiClient = api): Promise<PartyDetail> =>
  requestUntyped(client, "post", `${party(id)}/${archived ? "archive" : "restore"}`, { body: { expected_version: version } });

export const fetchCustomerTypes = (signal?: AbortSignal, client: ApiClient = api): Promise<CustomerTypeRead[]> =>
  requestUntyped(client, "get", `${PARTIES}/customer-types`, { signal });

export const createCustomerType = (body: Record<string, unknown>, client: ApiClient = api): Promise<CustomerTypeRead> =>
  requestUntyped(client, "post", `${PARTIES}/customer-types`, { body });

export const updateCustomerType = (id: string, body: Record<string, unknown>, client: ApiClient = api): Promise<CustomerTypeRead> =>
  requestUntyped(client, "patch", `${PARTIES}/customer-types/${encodeURIComponent(id)}`, { body });

/** The edit form's body: changed header fields plus the full contact and address lists (replace semantics). */
export function partyPatch(
  before: PartyDetail,
  form: { display_name: string; legal_name: string; country_code: string; default_currency: string; customer_type: string; status: string },
  contacts: ContactRead[],
  addresses: AddressRead[],
): Record<string, unknown> {
  const body: Record<string, unknown> = { expected_version: before.version };
  if (form.display_name.trim() !== before.display_name) body.display_name = form.display_name.trim();
  if (form.legal_name.trim() !== before.legal_name) body.legal_name = form.legal_name.trim();
  if (form.country_code.trim().toUpperCase() !== before.country_code) body.country_code = form.country_code.trim().toUpperCase();
  if (form.default_currency !== before.default_currency) body.default_currency = form.default_currency;
  if ((form.customer_type || null) !== before.customer_type) body.customer_type = form.customer_type || null;
  if (form.status !== before.status) body.status = form.status;
  const clean = (row: ContactRead | AddressRead) =>
    Object.fromEntries(Object.entries(row).map(([k, v]) => [k, typeof v === "string" && !v.trim() ? null : v]));
  body.contacts = contacts.filter((c) => c.name.trim()).map(clean);
  body.addresses = addresses.filter((a) => a.line1.trim()).map(clean);
  return body;
}
