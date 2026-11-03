"use client";

/**
 * The party picker of the challan header: parties (GET /api/v1/parties/parties) filtered on the server by the role the
 * destination type expects (customer, fabricator, vendor; any role for a transporter). At most ten matches, at least
 * two characters, 250 ms debounce. Products come from the quote screens' product search.
 */

import { useQuery } from "@tanstack/react-query";
import { parsePartyOptions } from "@/features/sales/pickers";
import { api, requestUntyped, type ApiClient } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { useDebouncedValue } from "@/lib/hooks";
import type { PartyChoice } from "./form-model";

export { useProductSearch, type ProductOption } from "@/features/sales/pickers";

export async function searchPartiesByRole(q: string, role: string | null, signal?: AbortSignal, client: ApiClient = api): Promise<PartyChoice[]> {
  const raw = await requestUntyped<unknown>(client, "get", "/api/v1/parties/parties", {
    params: { query: { q: q.trim() || undefined, role: role ?? undefined, limit: 10 } },
    signal,
  });
  return parsePartyOptions(raw).map((party) => ({ id: party.id, party_number: party.party_number, display_name: party.display_name }));
}

export function useRolePartySearch(text: string, role: string | null | "any") {
  const q = useDebouncedValue(text.trim(), 250);
  const wanted = role === "any" ? null : role;
  return useQuery({
    queryKey: queryKeys.parties.search(`${wanted ?? "*"}:${q}`),
    queryFn: ({ signal }) => searchPartiesByRole(q, wanted, signal),
    enabled: role !== null && q.length >= 2,
    staleTime: 30_000,
  });
}
