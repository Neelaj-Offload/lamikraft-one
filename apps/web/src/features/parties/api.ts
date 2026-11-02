/**
 * The parties API (INTERIM(api-generate): see types.ts). Paths follow backend/app/modules/parties/router.py:
 * - parties_list_parties        GET   /api/v1/parties/parties           (q, role, country_code, customer_type, status, include_archived)
 * - parties_create_party        POST  /api/v1/parties/parties           (Idempotency-Key)
 * - parties_get_party           GET   /api/v1/parties/parties/{party_id}
 * - parties_update_party        PATCH /api/v1/parties/parties/{party_id} (`expected_version`, dirty fields; 409 version_conflict)
 * - parties_get_party_by_number GET   /api/v1/parties/parties/lookup?party_number=
 * The quotes of a customer come from the sales API (`GET /sales/quotes?party_id=`).
 */

import { fetchQuotes, type QuoteListParams } from "@/features/sales/api";
import type { Page, QuoteSummary } from "@/features/sales/types";
import { api, idempotencyHeaders, requestUntyped, type ApiClient } from "@/lib/api/client";
import { parsePartyDetail, parsePartyPage } from "./parse";
import type { CustomerType, PartyCreateRequest, PartyDetail, PartyRole, PartyStatus, PartySummary, PartyUpdateRequest } from "./types";

export const PARTIES_PATH = "/api/v1/parties/parties";
export const PARTIES_PAGE_SIZE = 25;
/** The quotes shown on a customer's record. */
export const PARTY_QUOTES_SHOWN = 5;

const partyPath = (partyId: string): `/api/v1/${string}` => `${PARTIES_PATH}/${encodeURIComponent(partyId)}`;

export interface PartyListParams {
  q?: string | null;
  role?: PartyRole | null;
  status?: PartyStatus | null;
  country_code?: string | null;
  customer_type?: CustomerType | null;
  include_archived?: boolean | null;
  offset?: number | null;
}

/** The query string the list sends (also used by the server prefetch, so both hit the same URL). */
export function partyListQuery(params: PartyListParams): Record<string, string | number | boolean | undefined> {
  return {
    q: params.q?.trim() || undefined,
    role: params.role || undefined,
    status: params.status || undefined,
    country_code: params.country_code || undefined,
    customer_type: params.customer_type || undefined,
    include_archived: params.include_archived ? true : undefined,
    offset: params.offset ?? 0,
    limit: PARTIES_PAGE_SIZE,
  };
}

export async function fetchParties(params: PartyListParams, signal?: AbortSignal, client: ApiClient = api): Promise<Page<PartySummary>> {
  const raw = await requestUntyped<unknown>(client, "get", PARTIES_PATH, { params: { query: partyListQuery(params) }, signal });
  return parsePartyPage(raw);
}

export async function fetchParty(partyId: string, signal?: AbortSignal, client: ApiClient = api): Promise<PartyDetail> {
  return parsePartyDetail(await requestUntyped<unknown>(client, "get", partyPath(partyId), { signal }));
}

export async function createParty(body: PartyCreateRequest, idempotencyKey: string, client: ApiClient = api): Promise<PartyDetail> {
  return parsePartyDetail(await requestUntyped<unknown>(client, "post", PARTIES_PATH, { body, headers: idempotencyHeaders(idempotencyKey) }));
}

/** `PATCH` with `expected_version` and only the dirty fields; the answer is the updated party. */
export async function updateParty(partyId: string, body: PartyUpdateRequest, idempotencyKey: string, client: ApiClient = api): Promise<PartyDetail> {
  return parsePartyDetail(await requestUntyped<unknown>(client, "patch", partyPath(partyId), { body, headers: idempotencyHeaders(idempotencyKey) }));
}

/** The newest quotes of one customer, across everyone's quotes the person may see. */
export function partyQuotesParams(partyId: string): QuoteListParams {
  return { party_id: partyId, scope: "all", offset: 0 };
}

export async function fetchPartyQuotes(partyId: string, signal?: AbortSignal, client: ApiClient = api): Promise<Page<QuoteSummary>> {
  return fetchQuotes(partyQuotesParams(partyId), signal, client);
}
