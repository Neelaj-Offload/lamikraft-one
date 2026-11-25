"use client";

/**
 * Data hooks for the Stock screens (stock on hand, movements, stock takes, pick lists, stock
 * documents and reservations).
 *
 * The API calls, types, list state and the command hook come from the old app's non-visual modules
 * (`@/features/inventory/api`, `list-state`, `use-command`). The old screens ran their queries
 * inline in view files, so the queries live here: same endpoints, same parameters and the same
 * query keys, so the caches the command hook refreshes stay the ones these screens read.
 */

import { useQuery } from "@tanstack/react-query";
import type { Route } from "next";
import {
  fetchCount,
  fetchDocument,
  fetchDocuments,
  fetchMovements,
  fetchPickList,
  fetchReservations,
  fetchShortages,
  fetchStock,
  fetchWarehouses,
  type DocumentKind,
} from "@/features/inventory/api";
import type { StockState } from "@/features/inventory/list-state";
import { queryKeys } from "@/lib/api/query-keys";
import { canAccessRoute, matchRoute } from "@/lib/routes";
import { useSession } from "@/lib/session/context";

/** `router.push` and `Link` want typed routes; API paths and built URLs are plain strings. */
export const asRoute = (path: string) => path as Route;

/** Whether this person may open an in-app path (checked against the shared route manifest), so links never lead to a refusal. */
export function useCanOpen(): (path: string) => boolean {
  const { permissionKeys } = useSession();
  return (path) => {
    const route = matchRoute(path.split("?")[0] ?? path);
    return route !== null && canAccessRoute(route, permissionKeys);
  };
}

export function useWarehouses() {
  return useQuery({ queryKey: queryKeys.inventory.warehouses(), queryFn: ({ signal }) => fetchWarehouses(signal) });
}

export function useStock(state: StockState) {
  return useQuery({
    queryKey: queryKeys.inventory.stock({ q: state.q, warehouse: state.warehouse, short: state.short, offset: state.offset }),
    queryFn: ({ signal }) => fetchStock({ q: state.q, warehouse_id: state.warehouse, short_only: state.short, offset: state.offset }, signal),
  });
}

export function useMovements(offset: number) {
  return useQuery({ queryKey: queryKeys.inventory.movements({ offset }), queryFn: ({ signal }) => fetchMovements({ offset }, signal) });
}

export const reservationsKey = (status: string | null, offset: number) => queryKeys.inventory.reservations({ status, offset });

export function useReservations(status: string | null, offset: number) {
  return useQuery({ queryKey: reservationsKey(status, offset), queryFn: ({ signal }) => fetchReservations({ status, offset }, signal) });
}

export function useShortages() {
  return useQuery({ queryKey: queryKeys.inventory.shortages(), queryFn: ({ signal }) => fetchShortages(signal) });
}

export const stockTakesKey = () => queryKeys.inventory.documents("stock_count");

export function useStockTakes() {
  return useQuery({ queryKey: stockTakesKey(), queryFn: ({ signal }) => fetchDocuments("stock_count", signal) });
}

export function useStockTake(countId: string) {
  return useQuery({ queryKey: queryKeys.inventory.count(countId), queryFn: ({ signal }) => fetchCount(countId, signal) });
}

export function usePickList(pickListId: string) {
  return useQuery({ queryKey: queryKeys.inventory.pickList(pickListId), queryFn: ({ signal }) => fetchPickList(pickListId, signal) });
}

export function useStockDocument(kind: DocumentKind, id: string) {
  return useQuery({ queryKey: queryKeys.inventory.document(kind, id), queryFn: ({ signal }) => fetchDocument(kind, id, signal) });
}
