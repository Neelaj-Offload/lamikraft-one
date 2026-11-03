/**
 * Customer types and party archive/restore (catalogue lane, Slice 2; INTERIM(api-generate): untyped calls).
 * - GET|POST /api/v1/parties/customer-types, PATCH /api/v1/parties/customer-types/{id} (`parties.customer_type.manage`)
 * - POST /api/v1/parties/parties/{id}/archive|restore (`parties.party.archive`)
 */

import { api, requestUntyped, type ApiClient } from "@/lib/api/client";

const PARTIES = "/api/v1/parties";

export interface CustomerTypeCapability {
  allowed: boolean;
  reason_code: string | null;
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
  capabilities: Record<string, CustomerTypeCapability>;
}

export const fetchCustomerTypes = (signal?: AbortSignal, client: ApiClient = api): Promise<CustomerTypeRead[]> =>
  requestUntyped(client, "get", `${PARTIES}/customer-types`, { signal });

export const createCustomerType = (body: Record<string, unknown>, client: ApiClient = api): Promise<CustomerTypeRead> =>
  requestUntyped(client, "post", `${PARTIES}/customer-types`, { body });

export const updateCustomerType = (id: string, body: Record<string, unknown>, client: ApiClient = api): Promise<CustomerTypeRead> =>
  requestUntyped(client, "patch", `${PARTIES}/customer-types/${encodeURIComponent(id)}`, { body });

/** Archive or restore a party; the server answers with the party record (raw; callers re-read through the query). */
export const setPartyArchived = (id: string, archived: boolean, version: number, client: ApiClient = api): Promise<unknown> =>
  requestUntyped(client, "post", `${PARTIES}/parties/${encodeURIComponent(id)}/${archived ? "archive" : "restore"}`, { body: { expected_version: version } });
