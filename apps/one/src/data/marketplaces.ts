/**
 * Marketplaces (module 5, backend/app/modules/marketplaces):
 * - GET   /api/v1/marketplaces/channels                       the four channels (Demo or Live)
 * - GET   /api/v1/marketplaces/channels/{id}                  listings and recent orders
 * - PATCH /api/v1/marketplaces/channels/{id}                  mode, warehouse, on/off
 * - POST  /api/v1/marketplaces/channels/{id}/listings         map a channel SKU to a product
 * - PATCH /api/v1/marketplaces/listings/{id}                  push on/off, product type, ASIN
 * - POST  /api/v1/marketplaces/channels/{id}/simulate-order   Demo: an order arrives
 * - POST  /api/v1/marketplaces/channels/{id}/sync             fetch orders, push free stock
 */

import { useQuery } from "@tanstack/react-query";
import { api, requestUntyped, type ApiClient } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import type { components } from "@/lib/api/schema";

type S = components["schemas"];
export type Channel = S["ChannelRead"];
export type ChannelDetail = S["ChannelDetail"];
export type Listing = S["ListingRead"];
export type MarketplaceOrder = S["OrderRead"];
export type SyncSummary = S["SyncSummary"];

const BASE = "/api/v1/marketplaces";
const channelPath = (id: string): `/api/v1/${string}` => `${BASE}/channels/${encodeURIComponent(id)}`;

export const marketplaceKeys = {
  channels: () => ["marketplaces", "channels"] as const,
  channel: (id: string) => ["marketplaces", "channel", { id }] as const,
};
export const MARKETPLACE_INVALIDATE = [["marketplaces"] as const, queryKeys.inventory.all(), ["stock-categories"] as const] as const;

export function useChannels() {
  return useQuery({ queryKey: marketplaceKeys.channels(), queryFn: ({ signal }) => requestUntyped<Channel[]>(api, "get", `${BASE}/channels`, { signal }) });
}

export function useChannel(id: string) {
  return useQuery({ queryKey: marketplaceKeys.channel(id), queryFn: ({ signal }) => requestUntyped<ChannelDetail>(api, "get", channelPath(id), { signal }) });
}

export function updateChannel(id: string, body: { expected_version: number; mode?: "demo" | "live"; warehouse_id?: string; is_active?: boolean }, client: ApiClient = api) {
  return requestUntyped<ChannelDetail>(client, "patch", channelPath(id), { body });
}

export function createListing(
  id: string,
  body: { product_id: string; channel_sku: string; external_id?: string | null; product_type?: string | null; push_stock?: boolean },
  client: ApiClient = api,
) {
  return requestUntyped<ChannelDetail>(client, "post", `${channelPath(id)}/listings`, { body });
}

export function updateListing(id: string, body: { expected_version: number; push_stock?: boolean; is_active?: boolean }, client: ApiClient = api) {
  return requestUntyped<ChannelDetail>(client, "patch", `${BASE}/listings/${encodeURIComponent(id)}` as `/api/v1/${string}`, { body });
}

export function simulateOrder(id: string, body: { channel_sku: string; quantity: number }, client: ApiClient = api) {
  return requestUntyped<MarketplaceOrder>(client, "post", `${channelPath(id)}/simulate-order`, { body });
}

export function syncChannel(id: string, client: ApiClient = api) {
  return requestUntyped<SyncSummary>(client, "post", `${channelPath(id)}/sync`, {});
}
